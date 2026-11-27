from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_grading_service, get_session
from app.db.models import Exam, Question, Student, StudentAnswer, Submission
from app.schemas.submission import SubmissionCreate, SubmissionRead
from app.services.answer_import import (
    AnswerSheetError,
    import_answer_sheet,
    parse_answer_sheet,
)
from app.services.grading import GradingService

router = APIRouter(prefix="/api", tags=["submissions"])


def _submission_read(submission: Submission, answers: list[StudentAnswer]) -> SubmissionRead:
    return SubmissionRead(
        id=submission.id,
        exam_id=submission.exam_id,
        student_id=submission.student_id,
        status=submission.status,
        total_score=(
            float(submission.total_score) if submission.total_score is not None else None
        ),
        max_score=(
            float(submission.max_score) if submission.max_score is not None else None
        ),
        answers=[
            {
                "question_id": answer.question_id,
                "selected_options": answer.selected_options,
                "answer_text": answer.answer_text,
            }
            for answer in answers
        ],
    )


@router.post(
    "/exams/{exam_id}/submissions",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    exam_id: int,
    payload: SubmissionCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubmissionRead:
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    student = await session.get(Student, payload.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")

    question_ids = set(
        (
            await session.execute(
                select(Question.id).where(Question.exam_id == exam_id)
            )
        ).scalars()
    )
    answered_ids = [answer.question_id for answer in payload.answers]
    if len(answered_ids) != len(set(answered_ids)):
        raise HTTPException(status_code=400, detail="duplicate question answers")
    if any(question_id not in question_ids for question_id in answered_ids):
        raise HTTPException(status_code=400, detail="question does not belong to exam")

    existing = (
        await session.execute(
            select(Submission).where(
                Submission.exam_id == exam_id,
                Submission.student_id == payload.student_id,
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="submission already exists")

    submission = Submission(
        exam_id=exam_id,
        student_id=payload.student_id,
        source="api",
    )
    session.add(submission)
    await session.flush()

    answers = [
        StudentAnswer(
            submission_id=submission.id,
            question_id=answer.question_id,
            selected_options=answer.selected_options,
            answer_text=answer.answer_text,
        )
        for answer in payload.answers
    ]
    session.add_all(answers)
    await session.commit()
    await session.refresh(submission)

    return _submission_read(submission, answers)


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
async def get_submission(
    submission_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubmissionRead:
    submission = await session.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")
    answers = (
        await session.execute(
            select(StudentAnswer).where(
                StudentAnswer.submission_id == submission.id
            )
        )
    ).scalars().all()
    return _submission_read(submission, list(answers))


@router.post(
    "/exams/{exam_id}/submissions/import",
    status_code=status.HTTP_201_CREATED,
)
async def import_submissions(
    exam_id: int,
    file: Annotated[UploadFile, File(description="CSV / XLSX / JSON 答题卡")],
    session: Annotated[AsyncSession, Depends(get_session)],
    class_name: Annotated[str, Form()] = "导入班级",
) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件是空的")
    try:
        rows = parse_answer_sheet(file.filename or "", data)
        return await import_answer_sheet(
            session,
            exam_id,
            rows,
            default_class_name=class_name or "导入班级",
        )
    except AnswerSheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/submissions/{submission_id}/grade",
    status_code=status.HTTP_202_ACCEPTED,
)
async def grade_submission(
    submission_id: int,
    background_tasks: BackgroundTasks,
    service: Annotated[GradingService, Depends(get_grading_service)],
) -> dict:
    try:
        run_id = await service.create_run(submission_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(service.run, run_id)
    return {"grading_run_id": run_id, "status": "pending"}
