from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GradingResult,
    GradingRun,
    Question,
    Student,
    StudentAnswer,
    Submission,
    TeacherCorrection,
)
from app.schemas.report import BadCaseRead


async def list_bad_cases(
    session: AsyncSession,
    exam_id: int,
) -> list[BadCaseRead]:
    submissions = (
        await session.execute(
            select(Submission).where(Submission.exam_id == exam_id)
        )
    ).scalars().all()

    cases: list[BadCaseRead] = []
    for submission in submissions:
        run = (
            await session.execute(
                select(GradingRun)
                .where(
                    GradingRun.submission_id == submission.id,
                    GradingRun.status == "completed",
                )
                .order_by(GradingRun.created_at.desc(), GradingRun.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if run is None:
            continue

        student = await session.get(Student, submission.student_id)
        answers = (
            await session.execute(
                select(StudentAnswer).where(
                    StudentAnswer.submission_id == submission.id
                )
            )
        ).scalars().all()
        answer_map = {answer.question_id: answer for answer in answers}

        rows = (
            await session.execute(
                select(GradingResult, Question)
                .join(Question, Question.id == GradingResult.question_id)
                .where(GradingResult.run_id == run.id)
                .order_by(Question.order_index)
            )
        ).all()
        for result, question in rows:
            answer = answer_map.get(question.id)
            student_answer = None
            if answer is not None:
                student_answer = answer.answer_text or ", ".join(
                    answer.selected_options or []
                )
            base = {
                "question_id": question.id,
                "question_number": question.question_number,
                "student_name": student.name if student is not None else "",
                "student_answer": student_answer,
                "ai_score": float(result.ai_score),
                "final_score": float(
                    result.final_score
                    if result.final_score is not None
                    else result.ai_score
                ),
                "confidence": float(result.confidence),
                "rationale": result.rationale,
                "error_type": result.error_type,
            }
            if float(result.confidence) < 0.6:
                cases.append(BadCaseRead(reason="low_confidence", **base))
            if result.error_type == "grading_failed" or (
                float(result.confidence) == 0 and result.error_type is None
            ):
                cases.append(BadCaseRead(reason="grading_failed", **base))

            corrections = (
                await session.execute(
                    select(TeacherCorrection).where(
                        TeacherCorrection.result_id == result.id
                    )
                )
            ).scalars().all()
            if any(
                abs(float(correction.new_score) - float(correction.old_score)) >= 2
                for correction in corrections
                if correction.new_score is not None
                and correction.old_score is not None
            ):
                cases.append(BadCaseRead(reason="teacher_override", **base))

    return cases
