from app.db.models import Rubric
from app.db.repositories import save_rubric


async def test_calibration_creates_new_active_rubric(
    app_client,
    sample_exam,
    session,
):
    question_id = sample_exam["questions"][2]["id"]
    old = await save_rubric(
        session,
        question_id,
        [
            {"id": "p1", "description": "点1", "score": 2},
            {"id": "p2", "description": "点2", "score": 2},
            {"id": "p3", "description": "点3", "score": 2},
        ],
        6.0,
    )
    old_id = old.id

    response = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/calibrate",
        json={
            "question_id": question_id,
            "instruction": "第三点只要提到倾向性标题就给分",
            "re_grade_all": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    new_id = body["rubric_id"]
    assert new_id != old_id
    assert body["version"] == 2

    session.expire_all()
    assert (await session.get(Rubric, old_id)).active is False
    assert (await session.get(Rubric, new_id)).active is True

    response = await app_client.get(f"/api/questions/{question_id}/rubrics")
    assert response.status_code == 200
    assert [item["version"] for item in response.json()] == [2, 1]


async def test_calibration_can_rerun_all_submissions(
    app_client,
    sample_exam,
    sample_submission,
):
    response = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/calibrate",
        json={
            "question_id": sample_exam["questions"][2]["id"],
            "instruction": "按采分点给分",
            "re_grade_all": True,
        },
    )
    assert response.status_code == 200
    assert len(response.json()["rerun_ids"]) == 1
