from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import GradingRun, Submission
from app.graph.state import GradingState


def make_finalize_node(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def node(state: GradingState) -> dict:
        results = state.get("corrected_results") or state["results"]
        total_score = sum(
            result["final_score"]
            if result["final_score"] is not None
            else result["ai_score"]
            for result in results
        )
        max_score = sum(result["max_score"] for result in results)

        async with session_factory() as session:
            await session.execute(
                update(GradingRun)
                .where(GradingRun.id == state["grading_run_id"])
                .values(
                    status="completed",
                    finished_at=func.now(),
                    heartbeat_at=func.now(),
                )
            )
            await session.execute(
                update(Submission)
                .where(Submission.id == state["submission_id"])
                .values(
                    status="completed",
                    total_score=total_score,
                    max_score=max_score,
                    graded_at=func.now(),
                )
            )
            await session.commit()

        return {"total_score": total_score, "max_score": max_score}

    return node
