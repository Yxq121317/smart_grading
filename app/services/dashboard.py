from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClassGroup,
    Exam,
    GradingResult,
    GradingRun,
    Question,
    Student,
    StudentAnswer,
    Submission,
    TeacherCorrection,
)
from app.db.repositories import get_exam_detail
from app.db.seed import ERROR_CATEGORIES
from app.services.reports import build_class_aggregate

ERROR_NAMES = {item["code"]: item["name"] for item in ERROR_CATEGORIES}


def _zero_kpis() -> dict:
    return {
        "average_score": 0.0,
        "max_score": 0.0,
        "student_count": 0,
        "graded_count": 0,
        "pending_review": 0,
        "no_change_rate": 1.0,
        "completion_rate": 0.0,
    }


async def _latest_run(
    session: AsyncSession,
    submission_id: int,
) -> GradingRun | None:
    return (
        await session.execute(
            select(GradingRun)
            .where(GradingRun.submission_id == submission_id)
            .order_by(GradingRun.created_at.desc(), GradingRun.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def _review_count(session: AsyncSession, run_id: int) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(GradingResult)
            .where(
                GradingResult.run_id == run_id,
                GradingResult.needs_review.is_(True),
                GradingResult.reviewed.is_(False),
            )
        )
    ).scalar() or 0


async def _run_detail(
    session: AsyncSession,
    run: GradingRun,
    submission_id: int,
) -> dict:
    rows = (
        await session.execute(
            select(GradingResult, Question)
            .join(Question, Question.id == GradingResult.question_id)
            .where(GradingResult.run_id == run.id)
            .order_by(Question.order_index)
        )
    ).all()
    answers = (
        await session.execute(
            select(StudentAnswer).where(StudentAnswer.submission_id == submission_id)
        )
    ).scalars().all()
    answer_map = {answer.question_id: answer for answer in answers}

    results = []
    review_items = []
    for result, question in rows:
        answer = answer_map.get(question.id)
        student_answer = None
        if answer is not None:
            student_answer = answer.answer_text or ", ".join(
                answer.selected_options or []
            )
        item = {
            "id": result.id,
            "question_id": question.id,
            "question_number": question.question_number,
            "question_type": question.question_type,
            "ai_score": float(result.ai_score),
            "max_score": float(result.max_score),
            "confidence": float(result.confidence),
            "needs_review": result.needs_review,
            "rationale": result.rationale,
            "point_results": result.point_results,
            "knowledge_points": result.knowledge_points,
            "error_type": result.error_type,
            "error_evidence": result.error_evidence,
            "final_score": float(
                result.final_score
                if result.final_score is not None
                else result.ai_score
            ),
            "reviewed": result.reviewed,
        }
        results.append(item)
        if result.needs_review and not result.reviewed:
            review_items.append(
                {
                    "result_id": result.id,
                    "question_id": question.id,
                    "question_number": question.question_number,
                    "question_type": question.question_type,
                    "student_answer": student_answer,
                    "ai_score": float(result.ai_score),
                    "max_score": float(result.max_score),
                    "confidence": float(result.confidence),
                    "rationale": result.rationale or "",
                    "point_results": result.point_results or [],
                }
            )

    return {
        "id": run.id,
        "status": run.status,
        "results": results,
        "review_items": review_items,
    }


async def _submission_detail(
    session: AsyncSession,
    submission: Submission,
) -> dict:
    answers = (
        await session.execute(
            select(StudentAnswer).where(StudentAnswer.submission_id == submission.id)
        )
    ).scalars().all()
    return {
        "id": submission.id,
        "status": submission.status,
        "total_score": (
            float(submission.total_score)
            if submission.total_score is not None
            else None
        ),
        "max_score": (
            float(submission.max_score) if submission.max_score is not None else None
        ),
        "answers": [
            {
                "question_id": answer.question_id,
                "selected_options": answer.selected_options,
                "answer_text": answer.answer_text,
            }
            for answer in answers
        ],
    }


async def build_dashboard(
    session: AsyncSession,
    exam_code: str,
    class_id: int | None = None,
    student_id: int | None = None,
) -> dict:
    exam = (
        await session.execute(select(Exam).where(Exam.exam_code == exam_code))
    ).scalars().first()
    if exam is None:
        raise ValueError(f"exam {exam_code} not found")
    exam_detail = await get_exam_detail(session, exam.id)
    if exam_detail is None:
        raise ValueError(f"exam {exam_code} has no passage")

    if class_id is not None:
        class_group = await session.get(ClassGroup, class_id)
    else:
        class_group = (
            await session.execute(
                select(ClassGroup)
                .join(Student, Student.class_id == ClassGroup.id)
                .join(Submission, Submission.student_id == Student.id)
                .where(Submission.exam_id == exam.id)
                .order_by(ClassGroup.created_at.desc(), ClassGroup.id.desc())
                .limit(1)
            )
        ).scalars().first()

    exam_payload = exam_detail.model_dump()
    if class_group is None:
        return {
            "configured": False,
            "exam": exam_payload,
            "class": None,
            "students": [],
            "selected_student": None,
            "kpis": _zero_kpis(),
            "error_type_counts": {},
            "weak_points": [],
            "error_type_names": ERROR_NAMES,
        }

    students = (
        await session.execute(
            select(Student)
            .where(Student.class_id == class_group.id)
            .order_by(Student.id)
        )
    ).scalars().all()

    student_payloads = []
    runs_by_student: dict[int, GradingRun | None] = {}
    submissions_by_student: dict[int, Submission | None] = {}
    for student in students:
        submission = (
            await session.execute(
                select(Submission).where(
                    Submission.exam_id == exam.id,
                    Submission.student_id == student.id,
                )
            )
        ).scalars().first()
        run = await _latest_run(session, submission.id) if submission else None
        submissions_by_student[student.id] = submission
        runs_by_student[student.id] = run

        review_count = await _review_count(session, run.id) if run else 0
        total_score = None
        max_score = None
        if run is not None and run.status == "completed":
            totals = (
                await session.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                func.coalesce(
                                    GradingResult.final_score,
                                    GradingResult.ai_score,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(GradingResult.max_score), 0),
                    ).where(GradingResult.run_id == run.id)
                )
            ).one()
            total_score = float(totals[0])
            max_score = float(totals[1])

        student_payloads.append(
            {
                "id": student.id,
                "name": student.name,
                "student_no": student.student_no,
                "submission_id": submission.id if submission else None,
                "run_id": run.id if run else None,
                "run_status": run.status if run else None,
                "review_count": review_count,
                "total_score": total_score,
                "max_score": max_score,
            }
        )

    selected = next(
        (item for item in student_payloads if item["id"] == student_id),
        None,
    )
    if selected is None:
        selected = next(
            (item for item in student_payloads if item["run_id"] is None),
            student_payloads[0] if student_payloads else None,
        )
    selected_detail = None
    if selected is not None:
        submission = submissions_by_student[selected["id"]]
        run = runs_by_student[selected["id"]]
        selected_detail = {
            "id": selected["id"],
            "name": selected["name"],
            "student_no": selected["student_no"],
            "submission": (
                await _submission_detail(session, submission)
                if submission is not None
                else None
            ),
            "run": (
                await _run_detail(session, run, submission.id)
                if run is not None and submission is not None
                else None
            ),
        }

    aggregate = await build_class_aggregate(session, class_group.id, exam.id)
    pending_review = sum(item["review_count"] for item in student_payloads)
    graded_count = sum(
        1
        for run in runs_by_student.values()
        if run is not None and run.status == "completed"
    )
    completed_run_ids = [
        run.id
        for run in runs_by_student.values()
        if run is not None and run.status == "completed"
    ]
    total_results = 0
    overrides = 0
    if completed_run_ids:
        total_results = (
            await session.execute(
                select(func.count())
                .select_from(GradingResult)
                .where(GradingResult.run_id.in_(completed_run_ids))
            )
        ).scalar() or 0
        overrides = (
            await session.execute(
                select(func.count())
                .select_from(TeacherCorrection)
                .join(
                    GradingResult,
                    GradingResult.id == TeacherCorrection.result_id,
                )
                .where(
                    GradingResult.run_id.in_(completed_run_ids),
                    func.abs(
                        TeacherCorrection.new_score - TeacherCorrection.old_score
                    )
                    >= 0.01,
                )
            )
        ).scalar() or 0
    no_change_rate = (
        1 - overrides / total_results if total_results else 1.0
    )

    return {
        "configured": True,
        "exam": exam_payload,
        "class": {
            "id": class_group.id,
            "name": class_group.name,
            "student_count": len(students),
        },
        "students": student_payloads,
        "selected_student": selected_detail,
        "kpis": {
            "average_score": aggregate["average_score"],
            "max_score": aggregate["max_score"],
            "student_count": len(students),
            "graded_count": graded_count,
            "pending_review": pending_review,
            "no_change_rate": round(no_change_rate, 4),
            "completion_rate": (
                round(graded_count / len(students), 4) if students else 0.0
            ),
        },
        "error_type_counts": aggregate["error_type_counts"],
        "weak_points": aggregate["weak_points"],
        "error_type_names": ERROR_NAMES,
    }
