import asyncio
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import func, select

from app.db.models import GradingResult, GradingRun, TeacherCorrection
from app.graph.builder import build_grading_graph
from app.graph.checkpointer import create_checkpointer
from app.graph.nodes.apply_corrections import make_apply_corrections_node
from app.schemas.grading import (
    ErrorAnalysisOutput,
    GradeOutput,
    PointResult,
    QuestionStructure,
    ReportNarrative,
    RubricOutput,
    RubricPoint,
)
from app.services.grading import GradingConflictError, GradingService
from app.services.llm import LLMOutputError
from tests.fakes import FakeLLMClient


def _low_confidence_llm():
    return FakeLLMClient(
        {
            "structure": QuestionStructure(
                task_type="概括题",
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
            "grade": GradeOutput(
                score=4,
                confidence=0.5,
                point_results=[
                    PointResult(point_id="p1", hit=True, score=2),
                    PointResult(point_id="p2", hit=True, score=2),
                    PointResult(point_id="p3", hit=False, score=0),
                ],
                rationale="低置信度",
            ),
            "error_analysis": ErrorAnalysisOutput(
                primary_error_type="incomplete_summary",
                evidence="缺一点",
                suggestion="分点",
            ),
            "student_report": ReportNarrative(
                summary="x",
                weaknesses=[],
                suggestions=[],
            ),
            "class_report": ReportNarrative(
                summary="x",
                weaknesses=[],
                suggestions=[],
            ),
        }
    )


async def _create_run(session_factory, submission_id: int) -> tuple[int, str]:
    thread_id = f"review-{uuid4().hex}"
    async with session_factory() as session:
        run = GradingRun(
            submission_id=submission_id,
            graph_thread_id=thread_id,
        )
        session.add(run)
        await session.commit()
        return run.id, thread_id


async def test_low_confidence_triggers_interrupt_and_resume(
    test_session_factory,
    sample_submission,
    settings,
):
    run_id, thread_id = await _create_run(
        test_session_factory,
        sample_submission["submission_id"],
    )
    graph = build_grading_graph(
        _low_confidence_llm(),
        test_session_factory,
        settings,
        InMemorySaver(),
    )
    config = {"configurable": {"thread_id": thread_id}}
    first = await graph.ainvoke(
        {
            "submission_id": sample_submission["submission_id"],
            "grading_run_id": run_id,
        },
        config,
    )
    assert "__interrupt__" in first

    items = first["__interrupt__"][0].value["items"]
    assert len(items) == 1
    assert items[0]["question_number"] == 3
    result_id = items[0]["result_id"]

    second = await graph.ainvoke(
        Command(
            resume={
                "corrections": [
                    {
                        "result_id": result_id,
                        "final_score": 5,
                        "instruction": "补一点",
                        "new_rationale": "补一点",
                    }
                ]
            }
        ),
        config,
    )
    corrected = next(
        result
        for result in second["corrected_results"]
        if result["question_number"] == 3
    )
    assert corrected["final_score"] == 5

    async with test_session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(TeacherCorrection))
        ).scalar()
    assert count == 1


async def test_service_resume_twice_conflicts(
    test_session_factory,
    sample_submission,
    settings,
):
    run_id, _ = await _create_run(
        test_session_factory,
        sample_submission["submission_id"],
    )
    service = GradingService(
        build_grading_graph(
            _low_confidence_llm(),
            test_session_factory,
            settings,
            InMemorySaver(),
        ),
        test_session_factory,
        settings,
    )
    await service.run(run_id)
    run = await service.get_run(run_id)
    assert run is not None
    assert run.status == "awaiting_review"
    result_id = run.review_items[0]["result_id"]

    corrections = [
        {
            "result_id": result_id,
            "final_score": 5,
            "instruction": "补一点",
        }
    ]
    await service.resume(run_id, corrections)
    with pytest.raises(GradingConflictError):
        await service.resume(run_id, corrections)


async def test_review_endpoint_rejects_completed_run(
    app_client,
    test_session_factory,
    sample_submission,
):
    run_id, _ = await _create_run(
        test_session_factory,
        sample_submission["submission_id"],
    )
    async with test_session_factory() as session:
        run = await session.get(GradingRun, run_id)
        run.status = "completed"
        await session.commit()

    response = await app_client.post(
        f"/api/grading-runs/{run_id}/review",
        json={"corrections": []},
    )
    assert response.status_code == 409


async def test_checkpoint_survives_new_graph(
    test_session_factory,
    sample_submission,
    test_settings,
):
    run_id, thread_id = await _create_run(
        test_session_factory,
        sample_submission["submission_id"],
    )
    config = {"configurable": {"thread_id": thread_id}}

    async with create_checkpointer(test_settings) as saver:
        graph_one = build_grading_graph(
            _low_confidence_llm(),
            test_session_factory,
            test_settings,
            saver,
        )
        first = await graph_one.ainvoke(
            {
                "submission_id": sample_submission["submission_id"],
                "grading_run_id": run_id,
            },
            config,
        )
        assert "__interrupt__" in first
        result_id = first["__interrupt__"][0].value["items"][0]["result_id"]

        graph_two = build_grading_graph(
            _low_confidence_llm(),
            test_session_factory,
            test_settings,
            saver,
        )
        second = await graph_two.ainvoke(
            Command(
                resume={
                    "corrections": [
                        {
                            "result_id": result_id,
                            "final_score": 5,
                            "instruction": "补一点",
                        }
                    ]
                }
            ),
            config,
        )
        corrected = next(
            result
            for result in second["corrected_results"]
            if result["question_number"] == 3
        )
        assert corrected["final_score"] == 5


async def test_resume_with_report_failure_completes(
    test_session_factory,
    sample_submission,
    settings,
):
    run_id, thread_id = await _create_run(
        test_session_factory,
        sample_submission["submission_id"],
    )
    llm = _low_confidence_llm()
    llm.responses["student_report"] = LLMOutputError("report failed")
    graph = build_grading_graph(
        llm,
        test_session_factory,
        settings,
        InMemorySaver(),
    )
    config = {"configurable": {"thread_id": thread_id}}
    first = await graph.ainvoke(
        {
            "submission_id": sample_submission["submission_id"],
            "grading_run_id": run_id,
        },
        config,
    )
    result_id = first["__interrupt__"][0].value["items"][0]["result_id"]

    second = await graph.ainvoke(
        Command(
            resume={
                "corrections": [
                    {
                        "result_id": result_id,
                        "final_score": 5,
                        "instruction": "补一点",
                    }
                ]
            }
        ),
        config,
    )
    assert "报告生成失败" in second["report"]["content_markdown"]

    async with test_session_factory() as session:
        run = await session.get(GradingRun, run_id)
    assert run.status == "completed"


async def test_concurrent_resume_claims_once(
    test_session_factory,
    sample_submission,
    settings,
):
    run_id, _ = await _create_run(
        test_session_factory,
        sample_submission["submission_id"],
    )
    service = GradingService(
        build_grading_graph(
            _low_confidence_llm(),
            test_session_factory,
            settings,
            InMemorySaver(),
        ),
        test_session_factory,
        settings,
    )
    await service.run(run_id)
    run = await service.get_run(run_id)
    assert run is not None
    result_id = run.review_items[0]["result_id"]
    corrections = [
        {
            "result_id": result_id,
            "final_score": 5,
            "instruction": "补一点",
        }
    ]

    outcomes = await asyncio.gather(
        service.resume(run_id, corrections),
        service.resume(run_id, corrections),
        return_exceptions=True,
    )
    assert sum(isinstance(outcome, GradingConflictError) for outcome in outcomes) == 1

    async with test_session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(TeacherCorrection)
            )
        ).scalar()
    assert count == 1


async def test_apply_corrections_is_idempotent(
    test_session_factory,
    sample_exam,
    sample_submission,
):
    question_id = sample_exam["questions"][2]["id"]
    async with test_session_factory() as session:
        run = GradingRun(
            submission_id=sample_submission["submission_id"],
            graph_thread_id="idempotent-corrections",
            status="completed",
        )
        session.add(run)
        await session.flush()
        stored = GradingResult(
            run_id=run.id,
            question_id=question_id,
            ai_score=4,
            max_score=6,
            confidence=0.9,
            needs_review=True,
            rationale="原评分",
            point_results=[],
            knowledge_points=[],
            error_type="incomplete_summary",
            final_score=4,
            reviewed=False,
        )
        session.add(stored)
        await session.commit()
        run_id = run.id
        result_id = stored.id

    result = {
        "question_id": question_id,
        "question_number": 3,
        "question_type": "subjective",
        "ai_score": 4.0,
        "max_score": 6.0,
        "confidence": 0.9,
        "needs_review": True,
        "rationale": "原评分",
        "student_answer": "只答出第一点",
        "point_results": [],
        "knowledge_points": [],
        "rubric_id": None,
        "error_type": "incomplete_summary",
        "error_evidence": None,
        "final_score": None,
        "reviewed": False,
    }
    state = {
        "grading_run_id": run_id,
        "submission_id": sample_submission["submission_id"],
        "results": [result],
        "corrections": [
            {
                "result_id": result_id,
                "final_score": 5,
                "instruction": "补一点",
            }
        ],
    }
    node = make_apply_corrections_node(test_session_factory)
    await node(state)
    await node(state)

    async with test_session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(TeacherCorrection)
            )
        ).scalar()
        updated = await session.get(GradingResult, result_id)
    assert count == 1
    assert float(updated.final_score) == 5
