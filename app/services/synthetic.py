import random
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClassGroup,
    Exam,
    Question,
    Student,
    StudentAnswer,
    Submission,
)


async def seed_synthetic(
    session: AsyncSession,
    exam_code: str,
    students: int = 10,
    class_name: str = "高二(1)班",
    seed: int = 42,
) -> dict:
    exam = (
        await session.execute(select(Exam).where(Exam.exam_code == exam_code))
    ).scalars().first()
    if exam is None:
        raise ValueError(f"exam {exam_code} not found")
    questions = (
        await session.execute(
            select(Question)
            .where(Question.exam_id == exam.id)
            .order_by(Question.order_index)
        )
    ).scalars().all()

    rng = random.Random(seed)
    class_group = ClassGroup(name=class_name, grade="高二")
    session.add(class_group)
    await session.flush()

    submissions: list[Submission] = []
    answer_count = 0
    for index in range(students):
        student = Student(
            class_id=class_group.id,
            name=f"模拟学生{index + 1:02d}",
            student_no=f"SYN-{uuid4().hex[:8]}-{index + 1:02d}",
        )
        session.add(student)
        await session.flush()

        submission = Submission(
            exam_id=exam.id,
            student_id=student.id,
            source="synthetic",
        )
        session.add(submission)
        await session.flush()
        submissions.append(submission)

        for question in questions:
            if question.question_type == "single_choice":
                labels = [option["label"] for option in (question.options or [])]
                correct = question.correct_answer
                if labels and rng.random() < 0.7:
                    chosen = correct if correct in labels else labels[0]
                    profile = "full"
                elif labels:
                    wrong_options = [label for label in labels if label != correct]
                    chosen = rng.choice(wrong_options) if wrong_options else correct
                    profile = "wrong"
                else:
                    chosen = correct or ""
                    profile = "wrong"
                selected_options = [chosen] if chosen else []
                answer_text = None
            else:
                profile = rng.choices(
                    ["full", "partial", "wrong", "blank"],
                    weights=[0.3, 0.4, 0.2, 0.1],
                )[0]
                selected_options = []
                if profile == "full":
                    answer_text = question.correct_answer or ""
                elif profile == "partial":
                    points = question.answer_points or []
                    answer_text = "；".join(points[: max(1, len(points) // 2)])
                elif profile == "wrong":
                    answer_text = "我认为这道题主要考查的是文章的中心思想。"
                else:
                    answer_text = ""

            session.add(
                StudentAnswer(
                    submission_id=submission.id,
                    question_id=question.id,
                    selected_options=selected_options,
                    answer_text=answer_text,
                    synthetic_profile=profile,
                )
            )
            answer_count += 1

    await session.commit()
    return {
        "class_id": class_group.id,
        "student_count": students,
        "submission_count": len(submissions),
        "answer_count": answer_count,
    }
