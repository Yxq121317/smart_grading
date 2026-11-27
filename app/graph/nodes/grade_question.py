from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import update_run_heartbeat


def make_grade_question_node(
    question_graph,
    session_factory: async_sessionmaker[AsyncSession],
):
    async def node(payload: dict) -> dict:
        result = await question_graph.ainvoke({"context": payload["context"]})
        run_id = payload.get("grading_run_id")
        if run_id is not None:
            async with session_factory() as session:
                await update_run_heartbeat(session, run_id)
        return {"results": [result["result"]]}

    return node
