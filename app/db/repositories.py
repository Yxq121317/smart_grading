from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Exam,
    GradingResult,
    GradingRun,
    Passage,
    Question,
    Rubric,
    Student,
    StudentAnswer,
    Submission,
)
from app.graph.state import QuestionResult, ReviewItem
from app.schemas.exam import ExamDetail, ExamSummary, PassageRead, QuestionRead


async def list_exams(session: AsyncSession) -> list[ExamSummary]:
    statement = (
        select(Exam, func.count(Question.id).label("question_count"))
        .outerjoin(Question, Question.exam_id == Exam.id)
        .group_by(Exam.id)
        .order_by(Exam.source_index)
    )
    rows = (await session.execute(statement)).all()
    return [
        ExamSummary(
            id=exam.id,
            exam_code=exam.exam_code,
            year=exam.year,
            paper_name=exam.paper_name,
            question_count=question_count,
        )
        for exam, question_count in rows
    ]


async def get_exam_detail(session: AsyncSession, exam_id: int) -> ExamDetail | None:
    statement = (
        select(Exam)
        .where(Exam.id == exam_id)
        .options(selectinload(Exam.passages), selectinload(Exam.questions))
    )
    exam = (await session.execute(statement)).scalar_one_or_none()
    if exam is None or not exam.passages:
        return None

    passage = min(exam.passages, key=lambda item: item.order_index)
    question_ids = [question.id for question in exam.questions]
    active_rubrics: dict[int, dict] = {}
    if question_ids:
        rubric_statement = select(Rubric).where(
            Rubric.question_id.in_(question_ids),
            Rubric.active.is_(True),
        )
        for rubric in (await session.execute(rubric_statement)).scalars():
            active_rubrics[rubric.question_id] = {
                "id": rubric.id,
                "version": rubric.version,
                "points": rubric.points,
                "total_score": float(rubric.total_score),
                "source": rubric.source,
            }

    questions = [
        QuestionRead(
            id=question.id,
            question_number=question.question_number,
            order_index=question.order_index,
            stem=question.stem,
            question_type=question.question_type,
            options=question.options,
            correct_answer=question.correct_answer,
            answer_points=question.answer_points,
            explanation=question.explanation,
            max_score=float(question.max_score) if question.max_score is not None else None,
            active_rubric=active_rubrics.get(question.id),
        )
        for question in sorted(exam.questions, key=lambda item: item.order_index)
    ]

    return ExamDetail(
        id=exam.id,
        exam_code=exam.exam_code,
        year=exam.year,
        paper_name=exam.paper_name,
        passage=PassageRead.model_validate(passage),
        questions=questions,
    )


async def get_submission_bundle(
    session: AsyncSession,
    submission_id: int,
) -> dict | None:
    submission = await session.get(Submission, submission_id)
    if submission is None:
        return None
    exam = await session.get(Exam, submission.exam_id)
    student = await session.get(Student, submission.student_id)
    if exam is None or student is None:
        return None

    passage = (
        await session.execute(
            select(Passage)
            .where(Passage.exam_id == exam.id)
            .order_by(Passage.order_index)
        )
    ).scalars().first()
    questions = (
        await session.execute(
            select(Question)
            .where(Question.exam_id == exam.id)
            .order_by(Question.order_index)
        )
    ).scalars().all()
    answers = (
        await session.execute(
            select(StudentAnswer).where(StudentAnswer.submission_id == submission.id)
        )
    ).scalars().all()
    answer_map = {
        answer.question_id: {
            "selected_options": answer.selected_options or [],
            "answer_text": answer.answer_text,
            "synthetic_profile": answer.synthetic_profile,
        }
        for answer in answers
    }

    return {
        "submission_id": submission.id,
        "submission_status": submission.status,
        "exam_id": exam.id,
        "exam_code": exam.exam_code,
        "student_id": student.id,
        "student_name": student.name,
        "passage": passage.content if passage is not None else "",
        "questions": [
            {
                "id": question.id,
                "number": question.question_number,
                "type": question.question_type,
                "stem": question.stem,
                "options": question.options,
                "correct_answer": question.correct_answer,
                "answer_points": question.answer_points,
                "explanation": question.explanation,
                "max_score": (
                    float(question.max_score) if question.max_score is not None else None
                ),
            }
            for question in questions
        ],
        "answers": answer_map,
    }


async def get_active_rubric(
    session: AsyncSession,
    question_id: int,
    requested_rubric_id: int | None = None,
) -> Rubric | None:
    if requested_rubric_id is not None:
        requested = await session.get(Rubric, requested_rubric_id)
        if requested is not None and requested.question_id == question_id:
            return requested
    return (
        await session.execute(
            select(Rubric).where(
                Rubric.question_id == question_id,
                Rubric.active.is_(True),
            )
        )
    ).scalars().first()


async def save_rubric(
    session: AsyncSession,
    question_id: int,
    points: list[dict],
    total_score: float,
    *,
    source: str = "ai",
    instruction: str | None = None,
) -> Rubric:
    await session.execute(
        update(Rubric)
        .where(Rubric.question_id == question_id, Rubric.active.is_(True))
        .values(active=False)
    )
    max_version = (
        await session.execute(
            select(func.max(Rubric.version)).where(Rubric.question_id == question_id)
        )
    ).scalar() or 0
    rubric = Rubric(
        question_id=question_id,
        version=max_version + 1,
        points=points,
        total_score=total_score,
        source=source,
        instruction=instruction,
        active=True,
    )
    session.add(rubric)
    await session.commit()
    await session.refresh(rubric)
    return rubric


async def save_grading_results(
    session: AsyncSession,
    run_id: int,
    results: list[QuestionResult],
) -> list[ReviewItem]:
    if not results:
        return []

    rows = [
        {
            "run_id": run_id,
            "question_id": result["question_id"],
            "rubric_id": result.get("rubric_id"),
            "ai_score": result["ai_score"],
            "max_score": result["max_score"],
            "confidence": result["confidence"],
            "needs_review": result["needs_review"],
            "rationale": result["rationale"],
            "point_results": result["point_results"],
            "knowledge_points": result["knowledge_points"],
            "error_type": result["error_type"],
            "error_evidence": result["error_evidence"],
            "final_score": (
                result["final_score"]
                if result["final_score"] is not None
                else result["ai_score"]
            ),
            "reviewed": result["reviewed"],
        }
        for result in results
    ]
    statement = insert(GradingResult).values(rows)
    update_columns = {
        name: getattr(statement.excluded, name)
        for name in [
            "rubric_id",
            "ai_score",
            "max_score",
            "confidence",
            "needs_review",
            "rationale",
            "point_results",
            "knowledge_points",
            "error_type",
            "error_evidence",
            "final_score",
            "reviewed",
        ]
    }
    statement = statement.on_conflict_do_update(
        index_elements=[GradingResult.run_id, GradingResult.question_id],
        set_=update_columns,
    )
    await session.execute(statement)
    await session.commit()

    stored = (
        await session.execute(
            select(GradingResult).where(GradingResult.run_id == run_id)
        )
    ).scalars().all()
    by_question = {row.question_id: row for row in stored}

    review_items: list[ReviewItem] = []
    for result in results:
        row = by_question.get(result["question_id"])
        if row is None:
            continue
        if result["needs_review"] and not result["reviewed"]:
            review_items.append(
                {
                    "result_id": row.id,
                    "question_id": result["question_id"],
                    "question_number": result["question_number"],
                    "question_type": result["question_type"],
                    "student_answer": result.get("student_answer"),
                    "ai_score": float(row.ai_score),
                    "max_score": float(row.max_score),
                    "confidence": float(row.confidence),
                    "rationale": row.rationale or "",
                    "point_results": row.point_results or [],
                }
            )
    return review_items


async def update_run_heartbeat(session: AsyncSession, run_id: int) -> None:
    await session.execute(
        update(GradingRun).where(GradingRun.id == run_id).values(heartbeat_at=func.now())
    )
    await session.commit()


async def list_submission_ids_for_exam(
    session: AsyncSession,
    exam_id: int,
) -> list[int]:
    return list(
        (
            await session.execute(
                select(Submission.id).where(Submission.exam_id == exam_id)
            )
        ).scalars()
    )
