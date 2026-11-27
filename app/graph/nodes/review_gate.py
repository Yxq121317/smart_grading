from app.graph.state import GradingState


def review_gate(state: GradingState) -> str:
    if state.get("review_items"):
        return "human_review"
    return "build_report"
