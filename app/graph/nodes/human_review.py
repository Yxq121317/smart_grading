from langgraph.types import interrupt

from app.graph.state import GradingState


async def human_review_node(state: GradingState) -> dict:
    resume_value = interrupt({"items": state.get("review_items", [])})
    return {"corrections": resume_value.get("corrections", [])}
