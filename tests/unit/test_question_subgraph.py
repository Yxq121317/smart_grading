from app.graph.subgraphs.grade_question import (
    build_question_subgraph,
    confidence_for,
    grade_mcq,
    needs_review,
)
from app.schemas.grading import (
    ErrorAnalysisOutput,
    GradeOutput,
    PointResult,
    QuestionStructure,
    RubricOutput,
    RubricPoint,
)
from tests.fakes import FakeLLMClient, make_question_context


def test_mcq_correct(sample_exam, settings):
    context = make_question_context(sample_exam, 0, selected_options=["C"])
    result = grade_mcq(context, settings)
    assert result["ai_score"] == 3
    assert result["confidence"] == 1
    assert result["needs_review"] is False


def test_mcq_invalid_selection_is_reviewed(sample_exam, settings):
    context = make_question_context(sample_exam, 0, selected_options=["Z"])
    result = grade_mcq(context, settings)
    assert result["ai_score"] == 0
    assert result["needs_review"] is True


def test_confidence_rules(question_context):
    output = GradeOutput(score=0, confidence=0.9, point_results=[], rationale="x")
    context = question_context.copy()
    context["student_answer"] = "太短"
    assert confidence_for(output, context, repaired=True, rubric_fallback=False) < 0.7


def _subjective_responses(grade_output, error_type="incomplete_summary"):
    return {
        "structure": QuestionStructure(
            task_type="概括题",
            knowledge_points=["筛选并整合信息"],
            scoring_mode="rubric",
        ),
        "rubric": RubricOutput(
            max_score=6,
            points=[
                RubricPoint(id="p1", description="点1", score=2),
                RubricPoint(id="p2", description="点2", score=2),
                RubricPoint(id="p3", description="点3", score=2),
            ],
        ),
        "grade": grade_output,
        "error_analysis": ErrorAnalysisOutput(
            primary_error_type=error_type,
            evidence="测试",
            suggestion="测试",
        ),
    }


async def test_question_subgraph_normal(sample_exam, settings):
    context = make_question_context(
        sample_exam,
        2,
        student_answer="只答出第一点和第二点，第三点没有写",
    )
    llm = FakeLLMClient(
        _subjective_responses(
            GradeOutput(
                score=4,
                confidence=0.9,
                point_results=[
                    PointResult(point_id="p1", hit=True, score=2),
                    PointResult(point_id="p2", hit=True, score=2),
                    PointResult(point_id="p3", hit=False, score=0),
                ],
                rationale="答出两点",
            )
        )
    )
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["ai_score"] == 4
    assert result["confidence"] == 0.9
    assert result["needs_review"] is False
    assert result["error_type"] == "incomplete_summary"
    assert result["knowledge_points"] == ["筛选并整合信息"]


async def test_question_subgraph_low_confidence(sample_exam, settings):
    context = make_question_context(
        sample_exam,
        2,
        student_answer="只答出第一点和第二点，第三点没有写",
    )
    llm = FakeLLMClient(
        _subjective_responses(
            GradeOutput(
                score=4,
                confidence=0.5,
                point_results=[
                    PointResult(point_id="p1", hit=True, score=2),
                    PointResult(point_id="p2", hit=True, score=2),
                    PointResult(point_id="p3", hit=False, score=0),
                ],
                rationale="不太确定",
            )
        )
    )
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["needs_review"] is True


async def test_question_subgraph_blank(sample_exam, settings):
    context = make_question_context(sample_exam, 2, student_answer="")
    llm = FakeLLMClient(
        _subjective_responses(
            GradeOutput(
                score=0,
                confidence=0.9,
                point_results=[
                    PointResult(point_id="p1", hit=False, score=0),
                    PointResult(point_id="p2", hit=False, score=0),
                    PointResult(point_id="p3", hit=False, score=0),
                ],
                rationale="没有作答",
            ),
            error_type="blank",
        )
    )
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["ai_score"] == 0
    assert result["error_type"] == "blank"
    assert result["needs_review"] is True
    assert llm.calls == []


async def test_question_subgraph_full_score_skips_error_analysis(sample_exam, settings):
    context = make_question_context(
        sample_exam,
        2,
        student_answer="第一点、第二点、第三点都答到了，表达完整。",
    )
    responses = _subjective_responses(
        GradeOutput(
            score=6,
            confidence=0.9,
            point_results=[
                PointResult(point_id="p1", hit=True, score=2),
                PointResult(point_id="p2", hit=True, score=2),
                PointResult(point_id="p3", hit=True, score=2),
            ],
            rationale="全部答出",
        )
    )
    responses.pop("error_analysis")
    llm = FakeLLMClient(responses)
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["ai_score"] == 6
    assert result["error_type"] is None
    assert "error_analysis" not in llm.calls


async def test_question_subgraph_invalid_grade_falls_back(sample_exam, settings):
    context = make_question_context(
        sample_exam,
        2,
        student_answer="只答出第一点和第二点，第三点没有写",
    )
    llm = FakeLLMClient(
        _subjective_responses(
            [
                GradeOutput(
                    score=4,
                    confidence=0.9,
                    point_results=[
                        PointResult(point_id="p1", hit=True, score=2),
                        PointResult(point_id="p9", hit=True, score=2),
                    ],
                    rationale="point id 不存在",
                ),
                GradeOutput(
                    score=4,
                    confidence=0.9,
                    point_results=[
                        PointResult(point_id="p1", hit=True, score=2),
                        PointResult(point_id="p9", hit=True, score=2),
                    ],
                    rationale="仍然不合法",
                ),
            ]
        )
    )
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["ai_score"] == 0
    assert result["confidence"] == 0
    assert result["needs_review"] is True
    assert llm.calls.count("grade") == 2


async def test_question_subgraph_semantic_retry(sample_exam, settings):
    context = make_question_context(
        sample_exam,
        2,
        student_answer="只答出第一点和第二点，第三点没有写",
    )
    llm = FakeLLMClient(
        _subjective_responses(
            [
                GradeOutput(
                    score=4,
                    confidence=0.9,
                    point_results=[
                        PointResult(point_id="p9", hit=True, score=4),
                    ],
                    rationale="point id 不存在",
                ),
                GradeOutput(
                    score=4,
                    confidence=0.9,
                    point_results=[
                        PointResult(point_id="p1", hit=True, score=2),
                        PointResult(point_id="p2", hit=True, score=2),
                        PointResult(point_id="p3", hit=False, score=0),
                    ],
                    rationale="修正后的合法评分",
                ),
            ]
        )
    )
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["ai_score"] == 4
    assert llm.calls.count("grade") == 2
    assert result["needs_review"] is True


async def test_rubric_fallback_forces_review(sample_exam, settings):
    context = make_question_context(
        sample_exam,
        2,
        student_answer="这是一段足够长的学生答案，用来避免短答案边界规则触发复核。",
    )
    context["rubric"] = {
        "max_score": 6,
        "points": [
            {"id": "p1", "description": "答出要点", "score": 6},
        ],
        "scoring_rules": "",
    }
    context["rubric_fallback"] = True
    llm = FakeLLMClient(
        _subjective_responses(
            GradeOutput(
                score=6,
                confidence=1.0,
                point_results=[
                    PointResult(point_id="p1", hit=True, score=6),
                ],
                rationale="满分",
            )
        )
    )
    graph = build_question_subgraph(llm, settings)
    result = (await graph.ainvoke({"context": context}))["result"]
    assert result["ai_score"] == 6
    assert result["needs_review"] is True


def test_short_boundary_forces_review(settings):
    result = {
        "question_id": 1,
        "question_number": 1,
        "question_type": "subjective",
        "ai_score": 6,
        "max_score": 6,
        "confidence": 0.95,
        "needs_review": False,
        "rationale": "好",
        "student_answer": "答得不错",
        "point_results": [],
        "knowledge_points": [],
        "rubric_id": None,
        "error_type": None,
        "error_evidence": None,
        "final_score": None,
        "reviewed": False,
    }
    assert needs_review(result, settings) is True
