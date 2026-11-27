from app.db.models import Question
from app.db.seed import apply_default_scores


async def test_apply_default_scores(session, sample_exam):
    q1_id = sample_exam["questions"][0]["id"]
    q3_id = sample_exam["questions"][2]["id"]
    q1 = await session.get(Question, q1_id)
    q3 = await session.get(Question, q3_id)
    q1.max_score = None
    q3.max_score = None
    await session.commit()

    updated = await apply_default_scores(session)
    assert updated == 2
    await session.refresh(q1)
    await session.refresh(q3)
    assert q1.max_score == 3
    assert q3.max_score == 6
