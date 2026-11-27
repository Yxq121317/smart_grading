import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from langgraph.types import Command
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import (
    GradingResult,
    GradingRun,
    Question,
    StudentAnswer,
    Submission,
    TeacherCorrection,
)
from app.schemas.submission import GradingRunRead
from app.services.observability import trace_score, traceable

logger = logging.getLogger(__name__)


class GradingConflictError(Exception):
    pass


class GradingService:
    def __init__(self, graph, session_factory, settings: Settings) -> None:
        self.graph = graph
        self.session_factory = session_factory
        self.settings = settings
        self.run = traceable("grade_submission", settings)(self.run)
        self.resume = traceable("review_grading_run", settings)(self.resume)

    async def create_run(
        self,
        submission_id: int,
        requested_rubric_version_id: int | None = None,
    ) -> int:
        async with self.session_factory() as session:
            submission = await session.get(Submission, submission_id)
            if submission is None:
                raise ValueError(f"submission {submission_id} not found")
            run = GradingRun(
                submission_id=submission_id,
                rubric_version_id=requested_rubric_version_id,
                status="pending",
                graph_thread_id=uuid4().hex,
                model=self.settings.model_name,
                prompt_version=self.settings.prompt_version,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run.id

    async def run(self, run_id: int) -> None:
        async with self.session_factory() as session:
            run = await session.get(GradingRun, run_id)
            if run is None:
                return
            if run.status not in {"pending", "running"}:
                return
            run.status = "running"
            run.started_at = datetime.now(UTC)
            run.heartbeat_at = datetime.now(UTC)
            await session.commit()
            submission = await session.get(Submission, run.submission_id)
            if submission is None:
                run.status = "failed"
                run.error = "submission not found"
                await session.commit()
                return
            initial_state = {
                "exam_id": submission.exam_id,
                "submission_id": submission.id,
                "grading_run_id": run.id,
                "requested_rubric_version_id": run.rubric_version_id,
                "results": [],
                "corrections": [],
            }
            config = {"configurable": {"thread_id": run.graph_thread_id}}

            try:
                result = await self.graph.ainvoke(initial_state, config)
                if "__interrupt__" in result:
                    run.status = "awaiting_review"
                    await session.execute(
                        update(Submission)
                        .where(Submission.id == run.submission_id)
                        .values(status="awaiting_review")
                    )
                else:
                    run.status = "completed"
                run.finished_at = datetime.now(UTC)
                run.heartbeat_at = datetime.now(UTC)
                await session.commit()
                trace_score(
                    "task_completed",
                    1 if run.status == "completed" else 0,
                    self.settings,
                )
                trace_score(
                    "needs_review",
                    1 if run.status == "awaiting_review" else 0,
                    self.settings,
                )
            except Exception as exc:
                logger.exception("grading run %s failed", run_id)
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = datetime.now(UTC)
                await session.commit()
                trace_score("task_completed", 0, self.settings)

    async def resume(self, run_id: int, corrections: list[dict]) -> None:
        async with self.session_factory() as session:
            claim = await session.execute(
                update(GradingRun)
                .where(
                    GradingRun.id == run_id,
                    GradingRun.status == "awaiting_review",
                )
                .values(status="running")
                .returning(GradingRun.id)
            )
            claimed = claim.scalar_one_or_none()
            await session.commit()
            if claimed is None:
                raise GradingConflictError("grading run is not awaiting review")
            run = await session.get(GradingRun, run_id)
            if run is None:
                raise ValueError(f"grading run {run_id} not found")
            config = {"configurable": {"thread_id": run.graph_thread_id}}
            try:
                await self.graph.ainvoke(
                    Command(resume={"corrections": corrections}),
                    config,
                )
                run.status = "completed"
                run.finished_at = datetime.now(UTC)
                run.heartbeat_at = datetime.now(UTC)
                await session.commit()
                corrections_rows = (
                    await session.execute(
                        select(TeacherCorrection)
                        .join(
                            GradingResult,
                            GradingResult.id == TeacherCorrection.result_id,
                        )
                        .where(GradingResult.run_id == run_id)
                    )
                ).scalars().all()
                override = any(
                    correction.new_score is not None
                    and correction.old_score is not None
                    and abs(
                        float(correction.new_score) - float(correction.old_score)
                    )
                    >= 0.01
                    for correction in corrections_rows
                )
                trace_score(
                    "teacher_override",
                    1 if override else 0,
                    self.settings,
                )
                trace_score("task_completed", 1, self.settings)
            except Exception as exc:
                logger.exception("grading run %s resume failed", run_id)
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = datetime.now(UTC)
                await session.commit()
                trace_score("task_completed", 0, self.settings)

    async def get_run(self, run_id: int) -> GradingRunRead | None:
        async with self.session_factory() as session:
            run = await session.get(GradingRun, run_id)
            if run is None:
                return None
            rows = (
                await session.execute(
                    select(GradingResult, Question)
                    .join(Question, Question.id == GradingResult.question_id)
                    .where(GradingResult.run_id == run_id)
                    .order_by(Question.order_index)
                )
            ).all()
            answer_rows = (
                await session.execute(
                    select(StudentAnswer).where(
                        StudentAnswer.submission_id == run.submission_id
                    )
                )
            ).scalars().all()
            answer_map = {answer.question_id: answer for answer in answer_rows}

            results: list[dict] = []
            review_items: list[dict] = []
            for result, question in rows:
                item = {
                    "id": result.id,
                    "question_id": question.id,
                    "question_number": question.question_number,
                    "question_type": question.question_type,
                    "ai_score": float(result.ai_score),
                    "max_score": float(result.max_score),
                    "confidence": float(result.confidence),
                    "needs_review": result.needs_review,
                    "rationale": result.rationale,
                    "point_results": result.point_results,
                    "knowledge_points": result.knowledge_points,
                    "error_type": result.error_type,
                    "error_evidence": result.error_evidence,
                    "final_score": (
                        float(result.final_score)
                        if result.final_score is not None
                        else float(result.ai_score)
                    ),
                    "reviewed": result.reviewed,
                }
                results.append(item)
                if result.needs_review and not result.reviewed:
                    answer = answer_map.get(question.id)
                    review_items.append(
                        {
                            "result_id": result.id,
                            "question_id": question.id,
                            "question_number": question.question_number,
                            "question_type": question.question_type,
                            "student_answer": (
                                answer.answer_text if answer is not None else None
                            ),
                            "ai_score": float(result.ai_score),
                            "max_score": float(result.max_score),
                            "confidence": float(result.confidence),
                            "rationale": result.rationale or "",
                            "point_results": result.point_results or [],
                        }
                    )

            return GradingRunRead(
                id=run.id,
                submission_id=run.submission_id,
                status=run.status,
                model=run.model,
                error=run.error,
                results=results,
                review_items=review_items,
            )


async def mark_stale_runs(
    session_factory: async_sessionmaker[AsyncSession],
    older_than_minutes: int = 30,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    async with session_factory() as session:
        result = await session.execute(
            update(GradingRun)
            .where(
                GradingRun.status == "running",
                or_(
                    GradingRun.heartbeat_at.is_(None),
                    GradingRun.heartbeat_at < cutoff,
                ),
            )
            .values(
                status="failed",
                error="stale heartbeat",
                finished_at=func.now(),
            )
        )
        await session.commit()
        return result.rowcount
