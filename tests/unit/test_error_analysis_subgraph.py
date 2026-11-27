from app.graph.subgraphs.error_analysis import (
    build_error_analysis_subgraph,
    fallback_error_analysis,
)
from app.schemas.grading import ErrorAnalysisOutput
from app.services.llm import LLMOutputError
from tests.fakes import FakeLLMClient


async def test_error_analysis_valid(question_context, low_score_result):
    llm = FakeLLMClient(
        {
            "error_analysis": ErrorAnalysisOutput(
                primary_error_type="incomplete_summary",
                evidence="只答出第一个采分点",
                suggestion="分点概括",
            )
        }
    )
    graph = build_error_analysis_subgraph(llm)
    result = await graph.ainvoke(
        {"context": question_context, "result": low_score_result}
    )
    assert result["error_type"] == "incomplete_summary"
    assert result["error_fallback"] is False


async def test_error_analysis_llm_failure_falls_back(question_context, low_score_result):
    question_context["student_answer"] = "只答出一点"
    llm = FakeLLMClient({"error_analysis": LLMOutputError("bad")})
    graph = build_error_analysis_subgraph(llm)
    result = await graph.ainvoke(
        {"context": question_context, "result": low_score_result}
    )
    assert result["error_type"] == "incomplete_summary"
    assert result["error_fallback"] is True


def test_blank_falls_back_to_blank(question_context, low_score_result):
    question_context["student_answer"] = ""
    output = fallback_error_analysis(question_context, low_score_result)
    assert output.primary_error_type == "blank"


def test_mcq_falls_back_to_mcq_wrong(question_context, low_score_result):
    question_context["question_type"] = "single_choice"
    output = fallback_error_analysis(question_context, low_score_result)
    assert output.primary_error_type == "mcq_wrong"
