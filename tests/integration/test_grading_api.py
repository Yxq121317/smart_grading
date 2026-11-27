from datetime import UTC, datetime, timedelta

from app.db.models import GradingRun
from app.services.grading import GradingService, mark_stale_runs


async def test_create_submission_and_grade(
    app_client,
    app,
    sample_exam,
    test_session_factory,
):
    response = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/submissions",
        json={
            "student_id": sample_exam["student_id"],
            "answers": [
                {
                    "question_id": sample_exam["questions"][0]["id"],
                    "selected_options": ["C"],
                },
                {
                    "question_id": sample_exam["questions"][2]["id"],
                    "answer_text": "只答出第一点",
                },
            ],
        },
    )
    assert response.status_code == 201
    submission_id = response.json()["id"]

    response = await app_client.post(f"/api/submissions/{submission_id}/grade")
    assert response.status_code == 202
    run_id = response.json()["grading_run_id"]

    async with test_session_factory() as session:
        run = await session.get(GradingRun, run_id)
        assert run is not None
        service = GradingService(
            app.state.graph,
            test_session_factory,
            app.state.settings,
        )
        await service.run(run_id)

    response = await app_client.get(f"/api/grading-runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] in {"completed", "awaiting_review"}


async def test_mark_stale_runs(test_session_factory, sample_submission):
    async with test_session_factory() as session:
        run = GradingRun(
            submission_id=sample_submission["submission_id"],
            graph_thread_id="stale-run",
            status="running",
            heartbeat_at=datetime.now(UTC) - timedelta(minutes=31),
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    updated = await mark_stale_runs(test_session_factory)
    assert updated == 1

    async with test_session_factory() as session:
        updated_run = await session.get(GradingRun, run_id)
        assert updated_run.status == "failed"
