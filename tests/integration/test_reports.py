from app.db.models import Report


async def test_class_report_uses_latest_completed_run(
    app_client,
    seeded_two_runs_same_submission,
):
    response = await app_client.get(
        f"/api/classes/{seeded_two_runs_same_submission['class_id']}/report",
        params={"exam_id": seeded_two_runs_same_submission["exam_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["submission_count"] == 1
    assert body["data"]["average_score"] == 5.0
    assert "平均分" in body["content_markdown"]


async def test_student_report(
    app_client,
    seeded_two_runs_same_submission,
):
    response = await app_client.get(
        f"/api/students/{seeded_two_runs_same_submission['student_id']}/report",
        params={"exam_id": seeded_two_runs_same_submission["exam_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope_type"] == "student"
    assert "学生报告" in body["content_markdown"]


async def test_student_report_regenerates_for_new_run(
    app_client,
    test_session_factory,
    seeded_two_runs_same_submission,
):
    async with test_session_factory() as session:
        session.add(
            Report(
                scope_type="student",
                scope_id=seeded_two_runs_same_submission["student_id"],
                exam_id=seeded_two_runs_same_submission["exam_id"],
                grading_run_id=seeded_two_runs_same_submission["old_run_id"],
                content_markdown="旧报告",
                data={"average_score": 3},
            )
        )
        await session.commit()

    response = await app_client.get(
        f"/api/students/{seeded_two_runs_same_submission['student_id']}/report",
        params={"exam_id": seeded_two_runs_same_submission["exam_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content_markdown"] != "旧报告"
    assert body["grading_run_id"] == seeded_two_runs_same_submission["new_run_id"]
