async def test_dashboard_without_submissions(app_client, sample_exam):
    response = await app_client.get(
        "/api/demo/dashboard",
        params={"exam_code": sample_exam["exam_code"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["exam"]["id"] == sample_exam["exam_id"]
    assert body["students"] == []


async def test_dashboard_uses_latest_run(
    app_client,
    sample_exam,
    seeded_two_runs_same_submission,
):
    response = await app_client.get(
        "/api/demo/dashboard",
        params={"exam_code": sample_exam["exam_code"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert len(body["exam"]["questions"]) == 3
    assert body["class"]["student_count"] == 1
    assert body["students"][0]["run_status"] == "completed"
    assert body["kpis"]["average_score"] == 5.0
    assert body["kpis"]["graded_count"] == 1
    assert body["selected_student"]["run"]["results"][0]["final_score"] == 5.0
    assert body["error_type_counts"]["incomplete_summary"] == 1
