from app.graph.state import GradingState


def collect_results_node(state: GradingState) -> dict:
    results = state["results"]
    total_score = sum(
        result["final_score"] if result["final_score"] is not None else result["ai_score"]
        for result in results
    )
    max_score = sum(result["max_score"] for result in results)
    return {"total_score": total_score, "max_score": max_score}
