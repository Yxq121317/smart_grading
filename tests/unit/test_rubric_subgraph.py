from app.graph.subgraphs.rubric import (
    build_rubric_subgraph,
    fallback_rubric,
    mcq_rubric,
    validate_rubric,
)
from app.schemas.grading import RubricOutput, RubricPoint
from tests.fakes import FakeLLMClient


def test_validate_rubric_rejects_wrong_sum():
    rubric = RubricOutput(
        max_score=6,
        points=[
            RubricPoint(id="p1", description="点1", score=2),
            RubricPoint(id="p2", description="点2", score=2),
        ],
    )
    assert validate_rubric(rubric, 6) == ["细则分数之和 4.0 不等于 6.0"]


def test_fallback_rubric_sums_to_max(question_context):
    rubric = fallback_rubric(question_context, 6)
    assert rubric.max_score == 6
    assert sum(point.score for point in rubric.points) == 6
    assert len(rubric.points) == 3


def test_mcq_rubric():
    rubric = mcq_rubric(3)
    assert rubric.points[0].score == 3
    assert rubric.scoring_rules.startswith("答案与正确选项一致")


async def test_rubric_subgraph_valid(question_context):
    llm = FakeLLMClient(
        {
            "rubric": RubricOutput(
                max_score=6,
                points=[
                    RubricPoint(id="p1", description="点1", score=2),
                    RubricPoint(id="p2", description="点2", score=2),
                    RubricPoint(id="p3", description="点3", score=2),
                ],
            )
        }
    )
    graph = build_rubric_subgraph(llm)
    result = await graph.ainvoke({"context": question_context})
    assert result["rubric_fallback"] is False
    assert sum(point["score"] for point in result["rubric"]["points"]) == 6


async def test_rubric_subgraph_falls_back(question_context):
    llm = FakeLLMClient(
        {
            "rubric": RubricOutput(
                max_score=6,
                points=[
                    RubricPoint(id="p1", description="点1", score=2),
                    RubricPoint(id="p2", description="点2", score=2),
                ],
            )
        }
    )
    graph = build_rubric_subgraph(llm)
    result = await graph.ainvoke({"context": question_context})
    assert result["rubric_fallback"] is True
    assert sum(point["score"] for point in result["rubric"]["points"]) == 6
    assert llm.calls.count("rubric") == 2
