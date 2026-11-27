from sqlalchemy import select

from app.db.models import StudentAnswer
from app.services.synthetic import seed_synthetic


async def test_seed_synthetic_is_deterministic(session, sample_exam):
    first = await seed_synthetic(
        session,
        sample_exam["exam_code"],
        students=3,
        seed=7,
    )
    assert first["student_count"] == 3
    assert first["submission_count"] == 3
    assert first["answer_count"] == 9

    profiles = (
        await session.execute(select(StudentAnswer.synthetic_profile))
    ).scalars().all()
    assert set(profiles) <= {"full", "partial", "wrong", "blank"}
