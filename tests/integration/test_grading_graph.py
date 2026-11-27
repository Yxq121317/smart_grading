from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select

from app.db.models import GradingResult, GradingRun, Rubric
from app.graph.builder import build_grading_graph
from app.graph.nodes.prepare_questions import make_prepare_questions_node
from tests.fakes import make_question_context


async def test_graph_grades_all_questions(
    test_session_factory,
    sample_submission,
    fake_llm,
    settings,
):
    async with test_session_factory() as session:
        run = GradingRun(
            submission_id=sample_submission["submission_id"],
            graph_thread_id="test-graph",
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    graph = build_grading_graph(
        fake_llm,
        test_session_factory,
        settings,
        InMemorySaver(),
    )
    result = (
        await graph.ainvoke(
            {
                "submission_id": sample_submission["submission_id"],
                "grading_run_id": run_id,
            },
            {"configurable": {"thread_id": "test-graph"}},
        )
    )
    assert len(result["results"]) == 3
    assert result["results"][0]["ai_score"] == 3
    assert result["results"][2]["question_type"] == "subjective"

    async with test_session_factory() as session:
        rows = (await session.execute(select(GradingResult))).scalars().all()
    assert len(rows) == 3


class _FallbackRubricGraph:
    async def ainvoke(self, state):
        return {
            "rubric": {
                "max_score": 6,
                "points": [
                    {"id": "p1", "description": "答出要点", "score": 6},
                ],
                "scoring_rules": "",
            },
            "rubric_fallback": True,
        }


async def test_prepare_questions_does_not_persist_fallback_rubric(
    test_session_factory,
    sample_exam,
    sample_submission,
):
    async with test_session_factory() as session:
        run = GradingRun(
            submission_id=sample_submission["submission_id"],
            graph_thread_id="fallback-rubric",
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    node = make_prepare_questions_node(
        _FallbackRubricGraph(),
        test_session_factory,
    )
    context = make_question_context(
        sample_exam,
        2,
        student_answer="只答出第一点",
    )
    result = await node(
        {
            "question_contexts": [context],
            "grading_run_id": run_id,
            "requested_rubric_version_id": None,
        }
    )
    updated = result["question_contexts"][0]
    assert updated["rubric_fallback"] is True
    assert updated["rubric_id"] is None

    async with test_session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(Rubric))
        ).scalar()
    assert count == 0
