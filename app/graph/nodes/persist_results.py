from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import save_grading_results, update_run_heartbeat
from app.graph.state import GradingState


def make_persist_results_node(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def node(state: GradingState) -> dict:
        async with session_factory() as session:
            review_items = await save_grading_results(
                session,
                state["grading_run_id"],
                state["results"],
            )
            await update_run_heartbeat(session, state["grading_run_id"])
        return {"review_items": review_items}

    return node
