async def test_list_and_get_exam(app_client, sample_exam):
    response = await app_client.get("/api/exams")
    assert response.status_code == 200
    assert response.json()[0]["question_count"] == 3

    response = await app_client.get(f"/api/exams/{sample_exam['exam_id']}")
    assert response.status_code == 200
    body = response.json()
    assert len(body["questions"]) == 3
    assert body["questions"][2]["question_type"] == "subjective"

    assert (await app_client.get("/api/exams/99999")).status_code == 404
