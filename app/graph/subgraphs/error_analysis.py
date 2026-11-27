from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.graph.state import QuestionContext, QuestionResult
from app.schemas.grading import ERROR_TYPES, ErrorAnalysisOutput
from app.services.llm import LLMOutputError, LLMProtocol

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "error_analysis.md"


class ErrorState(TypedDict, total=False):
    context: QuestionContext
    result: QuestionResult
    error_type: str | None
    error_evidence: str | None
    suggestion: str | None
    error_fallback: bool


def fallback_error_analysis(
    context: QuestionContext,
    result: QuestionResult,
) -> ErrorAnalysisOutput:
    if context["question_type"] == "single_choice":
        return ErrorAnalysisOutput(
            primary_error_type="mcq_wrong",
            evidence="选择题答案错误或无法识别",
            suggestion="对照原文逐项排除干扰项",
        )
    if not (context.get("student_answer") or "").strip():
        return ErrorAnalysisOutput(
            primary_error_type="blank",
            evidence="学生答案为空",
            suggestion="先读题干，再回到原文找答题区间",
        )
    return ErrorAnalysisOutput(
        primary_error_type="incomplete_summary",
        evidence="未答出全部采分点",
        suggestion="分点概括，先找全信息再组织语言",
    )


def _build_prompt(context: QuestionContext, result: QuestionResult) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        stem=context["stem"],
        question_type=context["question_type"],
        correct_answer=context["correct_answer"] or "",
        student_answer=context.get("student_answer") or "（空）",
        ai_score=result["ai_score"],
        max_score=result["max_score"],
        rationale=result.get("rationale") or "",
    )


def _fallback_state(context: QuestionContext, result: QuestionResult) -> dict:
    output = fallback_error_analysis(context, result)
    return {
        "error_type": output.primary_error_type,
        "error_evidence": output.evidence,
        "suggestion": output.suggestion,
        "error_fallback": True,
    }


def build_error_analysis_subgraph(llm: LLMProtocol):
    async def classify_node(state: ErrorState) -> dict:
        context = state["context"]
        result = state["result"]
        try:
            response = await llm.complete_json(
                _build_prompt(context, result),
                ErrorAnalysisOutput,
                trace_name="error_analysis",
            )
            return {
                "error_type": response.value.primary_error_type,
                "error_evidence": response.value.evidence,
                "suggestion": response.value.suggestion,
                "error_fallback": False,
            }
        except LLMOutputError:
            return _fallback_state(context, result)

    async def validate_node(state: ErrorState) -> dict:
        if state.get("error_type") in ERROR_TYPES:
            return {}
        return _fallback_state(state["context"], state["result"])

    async def finalize_node(state: ErrorState) -> dict:
        return {}

    graph = StateGraph(ErrorState)
    graph.add_node("classify", classify_node)
    graph.add_node("validate", validate_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "validate")
    graph.add_edge("validate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
