from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import get_active_rubric, save_rubric, update_run_heartbeat
from app.graph.state import GradingState
from app.schemas.grading import RubricOutput


def make_prepare_questions_node(
    rubric_graph,
    session_factory: async_sessionmaker[AsyncSession],
):
    async def node(state: GradingState) -> dict:
        contexts = [dict(context) for context in state["question_contexts"]]
        async with session_factory() as session:
            for context in contexts:
                rubric = await get_active_rubric(
                    session,
                    context["question_id"],
                    state.get("requested_rubric_version_id"),
                )
                if rubric is not None:
                    context["rubric"] = {
                        "max_score": float(rubric.total_score),
                        "points": rubric.points,
                        "scoring_rules": "",
                    }
                    context["rubric_id"] = rubric.id
                    context["rubric_fallback"] = False
                    continue
                if context["question_type"] == "single_choice":
                    continue

                result = await rubric_graph.ainvoke({"context": context})
                rubric_data = result.get("rubric")
                if not rubric_data:
                    continue
                rubric_fallback = result.get("rubric_fallback", False)
                context["rubric"] = rubric_data
                context["rubric_fallback"] = rubric_fallback
                if rubric_fallback:
                    context["rubric_id"] = None
                    continue
                output = RubricOutput.model_validate(rubric_data)
                saved = await save_rubric(
                    session,
                    context["question_id"],
                    [point.model_dump() for point in output.points],
                    output.max_score,
                    source="ai",
                )
                context["rubric_id"] = saved.id

            await update_run_heartbeat(session, state["grading_run_id"])

        return {"question_contexts": contexts}

    return node
