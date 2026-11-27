import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.graph.state import QuestionContext
from app.schemas.grading import RubricOutput, RubricPoint
from app.services.llm import LLMOutputError, LLMProtocol

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "rubric.md"


class RubricState(TypedDict, total=False):
    context: QuestionContext
    instruction: str | None
    rubric: dict | None
    rubric_fallback: bool
    rubric_errors: list[str]
    repair_attempts: int


def validate_rubric(rubric: RubricOutput, max_score: float) -> list[str]:
    errors: list[str] = []
    if not rubric.points:
        errors.append("细则没有采分点")
    point_ids = [point.id for point in rubric.points]
    if len(point_ids) != len(set(point_ids)):
        errors.append("采分点 id 重复")
    for point in rubric.points:
        if point.score <= 0:
            errors.append(f"采分点 {point.id} 分数必须大于 0")
    total = sum(point.score for point in rubric.points)
    if abs(total - max_score) > 1e-6:
        errors.append(f"细则分数之和 {total:.1f} 不等于 {max_score:.1f}")
    if abs(rubric.max_score - max_score) > 1e-6:
        errors.append(
            f"细则 max_score {rubric.max_score:.1f} 与题目分值 {max_score:.1f} 不一致"
        )
    return errors


def fallback_rubric(context: QuestionContext, max_score: float) -> RubricOutput:
    answer_points = context["answer_points"]
    if not answer_points:
        return RubricOutput(
            max_score=max_score,
            points=[
                RubricPoint(
                    id="p1",
                    description="答出参考答案要点",
                    score=max_score,
                )
            ],
            scoring_rules="按参考答案要点给分",
        )

    count = len(answer_points)
    raw_score = max_score / count
    point_score = round(raw_score * 2) / 2
    scores = [point_score] * count
    scores[-1] += max_score - sum(scores)
    if any(score <= 0 for score in scores):
        return RubricOutput(
            max_score=max_score,
            points=[
                RubricPoint(
                    id="p1",
                    description="答出参考答案要点",
                    score=max_score,
                )
            ],
            scoring_rules="按参考答案要点给分",
        )

    return RubricOutput(
        max_score=max_score,
        points=[
            RubricPoint(
                id=f"p{index + 1}",
                description=description,
                score=scores[index],
            )
            for index, description in enumerate(answer_points)
        ],
        scoring_rules="按采分点给分，同义表达可给分",
    )


def mcq_rubric(max_score: float) -> RubricOutput:
    return RubricOutput(
        max_score=max_score,
        points=[
            RubricPoint(
                id="correct",
                description="选出正确选项",
                score=max_score,
            )
        ],
        scoring_rules="答案与正确选项一致得满分，否则 0 分",
    )


def _build_prompt(context: QuestionContext, instruction: str | None) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        stem=context["stem"],
        question_type=context["question_type"],
        correct_answer=context["correct_answer"] or "",
        answer_points="\n".join(context["answer_points"]) or "（无）",
        explanation=context["explanation"] or "",
        max_score=context["max_score"],
        instruction=instruction or "无",
    )


def build_rubric_subgraph(llm: LLMProtocol, allow_fallback: bool = True):
    async def draft_node(state: RubricState) -> dict:
        context = state["context"]
        try:
            response = await llm.complete_json(
                _build_prompt(context, state.get("instruction")),
                RubricOutput,
                trace_name="rubric",
            )
            return {"rubric": response.value.model_dump(), "rubric_errors": []}
        except LLMOutputError as exc:
            return {"rubric": None, "rubric_errors": [str(exc)]}

    async def validate_node(state: RubricState) -> dict:
        rubric_data = state.get("rubric")
        if not rubric_data:
            return {
                "rubric_errors": state.get("rubric_errors") or ["细则为空"],
            }
        try:
            rubric = RubricOutput.model_validate(rubric_data)
        except ValidationError as exc:
            return {"rubric_errors": [str(exc)]}
        errors = validate_rubric(rubric, state["context"]["max_score"])
        return {"rubric_errors": errors, "rubric_fallback": False}

    async def repair_node(state: RubricState) -> dict:
        attempts = state.get("repair_attempts", 0) + 1
        context = state["context"]
        repair_prompt = (
            _build_prompt(context, state.get("instruction"))
            + "\n上一次细则有问题："
            + "；".join(state.get("rubric_errors", []))
            + "\n上一次细则："
            + json.dumps(state.get("rubric"), ensure_ascii=False)
            + "\n请修正后重新输出完整 JSON。"
        )
        try:
            response = await llm.complete_json(
                repair_prompt,
                RubricOutput,
                trace_name="rubric",
            )
            return {
                "rubric": response.value.model_dump(),
                "rubric_errors": [],
                "repair_attempts": attempts,
            }
        except LLMOutputError as exc:
            return {
                "rubric_errors": [str(exc)],
                "repair_attempts": attempts,
            }

    async def fallback_node(state: RubricState) -> dict:
        if not allow_fallback:
            return {"rubric": None, "rubric_fallback": True}
        context = state["context"]
        rubric = fallback_rubric(context, context["max_score"])
        return {
            "rubric": rubric.model_dump(),
            "rubric_fallback": True,
        }

    def route_after_validate(state: RubricState) -> str:
        if not state.get("rubric_errors"):
            return "end"
        if state.get("repair_attempts", 0) < 1:
            return "repair"
        return "fallback"

    graph = StateGraph(RubricState)
    graph.add_node("draft", draft_node)
    graph.add_node("validate", validate_node)
    graph.add_node("repair", repair_node)
    graph.add_node("fallback", fallback_node)
    graph.add_edge(START, "draft")
    graph.add_edge("draft", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"end": END, "repair": "repair", "fallback": "fallback"},
    )
    graph.add_edge("repair", "validate")
    graph.add_edge("fallback", END)
    return graph.compile()
