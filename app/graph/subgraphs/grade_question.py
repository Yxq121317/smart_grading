import json
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.state import QuestionContext, QuestionResult, QuestionState
from app.graph.subgraphs.error_analysis import build_error_analysis_subgraph
from app.graph.subgraphs.rubric import build_rubric_subgraph
from app.graph.subgraphs.structure import build_structure_subgraph
from app.schemas.grading import GradeOutput
from app.services.llm import LLMOutputError, LLMProtocol

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "grade.md"


def _result(
    context: QuestionContext,
    *,
    ai_score: float,
    confidence: float,
    needs_review: bool,
    rationale: str,
    point_results: list[dict] | None = None,
    knowledge_points: list[str] | None = None,
    error_type: str | None = None,
    error_evidence: str | None = None,
) -> QuestionResult:
    return {
        "question_id": context["question_id"],
        "question_number": context["question_number"],
        "question_type": context["question_type"],
        "ai_score": float(ai_score),
        "max_score": float(context["max_score"]),
        "confidence": float(confidence),
        "needs_review": needs_review,
        "rationale": rationale,
        "student_answer": context.get("student_answer"),
        "point_results": point_results or [],
        "knowledge_points": knowledge_points or [],
        "rubric_id": context.get("rubric_id"),
        "error_type": error_type,
        "error_evidence": error_evidence,
        "final_score": None,
        "reviewed": False,
    }


def _grade_errors(
    output: GradeOutput,
    rubric: dict,
    max_score: float,
) -> list[str]:
    point_ids = {point.get("id") for point in rubric.get("points", [])}
    errors: list[str] = []
    if any(point.point_id not in point_ids for point in output.point_results):
        errors.append("point_id 不在细则里")
    if abs(output.score - sum(point.score for point in output.point_results)) > 1e-6:
        errors.append("分数加总不一致")
    if output.score < 0 or output.score > max_score:
        errors.append("分数超出范围")
    return errors


def grade_mcq(context: QuestionContext, settings: Settings) -> QuestionResult:
    del settings
    labels = {option.get("label") for option in context["options"]}
    selected = context.get("selected_options") or []
    max_score = float(context["max_score"])

    if len(selected) != 1 or selected[0] not in labels:
        return _result(
            context,
            ai_score=0,
            confidence=0,
            needs_review=True,
            rationale="选择题答案无法识别",
            error_type="mcq_wrong",
            error_evidence=f"学生答案：{selected}",
        )

    chosen = selected[0]
    correct = context.get("correct_answer")
    if chosen == correct:
        return _result(
            context,
            ai_score=max_score,
            confidence=1,
            needs_review=False,
            rationale=f"学生选择 {chosen}，与参考答案一致。",
        )

    return _result(
        context,
        ai_score=0,
        confidence=1,
        needs_review=False,
        rationale=f"学生选择 {chosen}，参考答案是 {correct}。",
        error_type="mcq_wrong",
        error_evidence=f"学生选 {chosen}，正确答案 {correct}",
    )


def confidence_for(
    output: GradeOutput,
    context: QuestionContext,
    *,
    repaired: bool,
    rubric_fallback: bool,
) -> float:
    confidence = output.confidence
    if repaired:
        confidence -= 0.1
    if rubric_fallback:
        confidence -= 0.2
    max_score = float(context["max_score"])
    if (
        output.score == 0 or abs(output.score - max_score) < 1e-6
    ) and len(context.get("student_answer") or "") < 20:
        confidence -= 0.15
    return max(0.0, min(1.0, confidence))


def needs_review(result: QuestionResult, settings: Settings) -> bool:
    short_boundary = (
        result["question_type"] == "subjective"
        and (result["ai_score"] == 0 or result["ai_score"] == result["max_score"])
        and len(result.get("student_answer") or "") < 20
    )
    return bool(
        result["needs_review"]
        or result["confidence"] < settings.review_confidence_threshold
        or short_boundary
    )


def _invalid_result(
    context: QuestionContext,
    knowledge_points: list[str],
) -> QuestionResult:
    return _result(
        context,
        ai_score=0,
        confidence=0,
        needs_review=True,
        rationale="评分输出无法解析",
        knowledge_points=knowledge_points,
    )


def _build_prompt(context: QuestionContext, rubric: dict) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        stem=context["stem"],
        question_type=context["question_type"],
        correct_answer=context["correct_answer"] or "",
        rubric=json.dumps(rubric, ensure_ascii=False),
        student_answer=context.get("student_answer") or "（空）",
        max_score=context["max_score"],
    )


def build_question_subgraph(llm: LLMProtocol, settings: Settings):
    structure_graph = build_structure_subgraph(llm)
    rubric_graph = build_rubric_subgraph(llm)
    error_graph = build_error_analysis_subgraph(llm)

    async def grade_mcq_node(state: QuestionState) -> dict:
        return {"result": grade_mcq(state["context"], settings)}

    async def blank_node(state: QuestionState) -> dict:
        context = state["context"]
        return {
            "result": _result(
                context,
                ai_score=0,
                confidence=0,
                needs_review=True,
                rationale="学生答案为空",
                error_type="blank",
                error_evidence="学生答案为空",
            )
        }

    async def rubric_node(state: QuestionState) -> dict:
        context = state["context"]
        if context.get("rubric"):
            return {
                "rubric": context["rubric"],
                "rubric_fallback": context.get("rubric_fallback", False),
            }
        result = await rubric_graph.ainvoke({"context": context})
        return {
            "rubric": result.get("rubric"),
            "rubric_fallback": result.get("rubric_fallback", False),
        }

    async def grade_node(state: QuestionState) -> dict:
        context = state["context"]
        rubric = state.get("rubric") or {}
        structure = state.get("structure") or {}
        knowledge_points = structure.get("knowledge_points", [])
        prompt = _build_prompt(context, rubric)
        semantic_retry = False

        try:
            response = await llm.complete_json(
                prompt,
                GradeOutput,
                trace_name="grade",
            )
            output = response.value
            errors = _grade_errors(output, rubric, float(context["max_score"]))
            if errors:
                semantic_retry = True
                repair_prompt = (
                    prompt
                    + "\n上一次评分有问题："
                    + "；".join(errors)
                    + "\n上一次输出："
                    + output.model_dump_json()
                    + "\n请修正后重新输出完整 JSON。"
                )
                response = await llm.complete_json(
                    repair_prompt,
                    GradeOutput,
                    trace_name="grade",
                )
                output = response.value
                errors = _grade_errors(
                    output,
                    rubric,
                    float(context["max_score"]),
                )
        except LLMOutputError:
            return {"result": _invalid_result(context, knowledge_points)}

        if errors:
            return {"result": _invalid_result(context, knowledge_points)}

        confidence = confidence_for(
            output,
            context,
            repaired=response.repaired or semantic_retry,
            rubric_fallback=state.get("rubric_fallback", False),
        )
        base_result = _result(
            context,
            ai_score=output.score,
            confidence=confidence,
            needs_review=output.needs_review,
            rationale=output.rationale,
            point_results=[point.model_dump() for point in output.point_results],
            knowledge_points=knowledge_points,
        )
        needs = (
            needs_review(base_result, settings)
            or response.repaired
            or semantic_retry
            or state.get("rubric_fallback", False)
        )
        if not (context.get("student_answer") or "").strip():
            needs = True
        base_result["needs_review"] = needs
        return {"result": base_result}

    def route_start(state: QuestionState) -> str:
        context = state["context"]
        if context["question_type"] == "single_choice":
            return "mcq"
        if not (context.get("student_answer") or "").strip():
            return "blank"
        return "subjective"

    def route_after_grade(state: QuestionState) -> str:
        result = state["result"]
        if result["ai_score"] < result["max_score"]:
            return "error"
        return "done"

    async def finalize_node(state: QuestionState) -> dict:
        result = dict(state["result"])
        structure = state.get("structure") or {}
        if structure.get("knowledge_points"):
            result["knowledge_points"] = structure["knowledge_points"]
        if state.get("error_type") is not None:
            result["error_type"] = state["error_type"]
            result["error_evidence"] = state.get("error_evidence")
        result["needs_review"] = needs_review(result, settings)
        return {"result": result}

    graph = StateGraph(QuestionState)
    graph.add_node("grade_mcq", grade_mcq_node)
    graph.add_node("blank", blank_node)
    graph.add_node("structure", structure_graph)
    graph.add_node("rubric", rubric_node)
    graph.add_node("grade", grade_node)
    graph.add_node("error_analysis", error_graph)
    graph.add_node("finalize", finalize_node)
    graph.add_conditional_edges(
        START,
        route_start,
        {"mcq": "grade_mcq", "blank": "blank", "subjective": "structure"},
    )
    graph.add_edge("structure", "rubric")
    graph.add_edge("rubric", "grade")
    graph.add_conditional_edges(
        "grade",
        route_after_grade,
        {"error": "error_analysis", "done": "finalize"},
    )
    graph.add_edge("error_analysis", "finalize")
    graph.add_edge("grade_mcq", "finalize")
    graph.add_edge("blank", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
