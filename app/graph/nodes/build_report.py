import logging

from app.graph.state import GradingState
from app.services.llm import LLMProtocol
from app.services.reports import generate_student_report

logger = logging.getLogger(__name__)


def make_build_report_node(llm: LLMProtocol):
    async def node(state: GradingState) -> dict:
        results = state.get("corrected_results") or state["results"]
        try:
            report = await generate_student_report(
                llm,
                state["student_name"],
                state["exam_code"],
                results,
                state.get("question_contexts", []),
            )
        except Exception:
            logger.exception("student report generation failed")
            report = {
                "content_markdown": "## 总体\n报告生成失败，请查看逐题结果。",
                "data": {"results": results},
            }
        return {"report": report}

    return node
