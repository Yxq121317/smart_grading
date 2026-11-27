from app.graph.subgraphs.structure import build_structure_subgraph
from app.schemas.grading import QuestionStructure
from app.services.llm import LLMOutputError
from tests.fakes import FakeLLMClient


async def test_structure_subgraph_valid(question_context):
    llm = FakeLLMClient(
        {
            "structure": QuestionStructure(
                task_type="概括题",
                answer_requirements=["分点作答"],
                knowledge_points=["筛选并整合信息"],
                scoring_mode="rubric",
            )
        }
    )
    graph = build_structure_subgraph(llm)
    result = await graph.ainvoke({"context": question_context})
    assert result["structure"]["task_type"] == "概括题"
    assert result["structure_fallback"] is False


async def test_structure_subgraph_falls_back(question_context):
    llm = FakeLLMClient({"structure": LLMOutputError("bad")})
    graph = build_structure_subgraph(llm)
    result = await graph.ainvoke({"context": question_context})
    assert result["structure_fallback"] is True
    assert result["structure"]["scoring_mode"] == "rubric"
