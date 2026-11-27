from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.graph.state import QuestionContext, QuestionState
from app.schemas.grading import QuestionStructure
from app.services.llm import LLMOutputError, LLMProtocol

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "structure.md"


def _build_prompt(context: QuestionContext) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        stem=context["stem"],
        question_type=context["question_type"],
        correct_answer=context["correct_answer"] or "",
        answer_points="\n".join(context["answer_points"]) or "（无）",
        explanation=context["explanation"] or "",
    )


def fallback_structure(context: QuestionContext) -> QuestionStructure:
    if context["question_type"] == "subjective":
        return QuestionStructure(task_type="主观题", scoring_mode="rubric")
    return QuestionStructure(task_type="选择题", scoring_mode="exact_match")


def build_structure_subgraph(llm: LLMProtocol):
    async def structure_node(state: QuestionState) -> dict:
        context = state["context"]
        try:
            response = await llm.complete_json(
                _build_prompt(context),
                QuestionStructure,
                trace_name="structure",
            )
            return {"structure": response.value.model_dump()}
        except LLMOutputError:
            return {
                "structure": fallback_structure(context).model_dump(),
                "structure_fallback": True,
            }

    async def validate_node(state: QuestionState) -> dict:
        context = state["context"]
        structure = state.get("structure") or {}
        fallback = state.get("structure_fallback", False)
        valid = bool(structure.get("task_type")) and structure.get("scoring_mode") in {
            "exact_match",
            "rubric",
        }
        if not valid:
            structure = fallback_structure(context).model_dump()
            fallback = True
        return {"structure": structure, "structure_fallback": fallback}

    graph = StateGraph(QuestionState)
    graph.add_node("structure", structure_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "structure")
    graph.add_edge("structure", "validate")
    graph.add_edge("validate", END)
    return graph.compile()
