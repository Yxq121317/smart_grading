from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Student, StudentAnswer, Submission


async def test_relationships(session, sample_exam):
    exam_id = sample_exam["exam_id"]
    student = Student(class_id=sample_exam["class_id"], name="测试学生", student_no="T001")
    session.add(student)
    await session.flush()
    submission = Submission(exam_id=exam_id, student_id=student.id)
    session.add(submission)
    await session.flush()
    question_id = sample_exam["questions"][0]["id"]
    session.add(
        StudentAnswer(
            submission_id=submission.id,
            question_id=question_id,
            selected_options=["C"],
        )
    )
    await session.commit()

    loaded = (
        await session.execute(
            select(Submission)
            .where(Submission.id == submission.id)
            .options(selectinload(Submission.student), selectinload(Submission.answers))
        )
    ).scalar_one()
    assert loaded.student.name == "测试学生"
    assert len(loaded.answers) == 1
