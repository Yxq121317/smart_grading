from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Report
from app.graph.state import GradingState


def make_persist_report_node(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def node(state: GradingState) -> dict:
        report = state["report"]
        async with session_factory() as session:
            session.add(
                Report(
                    scope_type="student",
                    scope_id=state["student_id"],
                    exam_id=state["exam_id"],
                    grading_run_id=state["grading_run_id"],
                    content_markdown=report["content_markdown"],
                    data=report["data"],
                )
            )
            await session.commit()
        return {}

    return node
