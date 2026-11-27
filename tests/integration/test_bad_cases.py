async def test_bad_cases_returns_low_confidence_and_override(
    app_client,
    seeded_bad_cases,
):
    response = await app_client.get(
        "/api/dev/bad-cases",
        params={"exam_id": seeded_bad_cases["exam_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item["reason"] == "low_confidence" for item in body)
    assert any(item["reason"] == "teacher_override" for item in body)
