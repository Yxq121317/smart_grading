from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm, get_session
from app.db.models import (
    ClassGroup,
    Exam,
    GradingResult,
    GradingRun,
    Question,
    Report,
    Student,
    Submission,
)
from app.schemas.report import ReportRead
from app.services.llm import LLMProtocol
from app.services.reports import (
    build_class_aggregate,
    generate_class_report,
    generate_student_report,
)

router = APIRouter(prefix="/api", tags=["reports"])


def _report_read(report: Report) -> ReportRead:
    return ReportRead(
        scope_type=report.scope_type,
        scope_id=report.scope_id,
        exam_id=report.exam_id,
        grading_run_id=report.grading_run_id,
        content_markdown=report.content_markdown,
        data=report.data,
    )


@router.get("/classes/{class_id}/report", response_model=ReportRead)
async def get_class_report(
    class_id: int,
    exam_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMProtocol, Depends(get_llm)],
) -> ReportRead:
    class_group = await session.get(ClassGroup, class_id)
    if class_group is None:
        raise HTTPException(status_code=404, detail="class not found")
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")

    aggregate = await build_class_aggregate(session, class_id, exam_id)
    report_data = await generate_class_report(
        llm,
        class_group.name,
        exam.exam_code,
        aggregate,
    )
    report = Report(
        scope_type="class",
        scope_id=class_id,
        exam_id=exam_id,
        content_markdown=report_data["content_markdown"],
        data=report_data["data"],
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return _report_read(report)


@router.get("/students/{student_id}/report", response_model=ReportRead)
async def get_student_report(
    student_id: int,
    exam_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMProtocol, Depends(get_llm)],
) -> ReportRead:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")

    submission = (
        await session.execute(
            select(Submission).where(
                Submission.exam_id == exam_id,
                Submission.student_id == student_id,
            )
        )
    ).scalars().first()
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")
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
        raise HTTPException(status_code=404, detail="completed run not found")

    stored = (
        await session.execute(
            select(Report)
            .where(
                Report.scope_type == "student",
                Report.scope_id == student_id,
                Report.exam_id == exam_id,
                Report.grading_run_id == run.id,
            )
            .order_by(Report.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if stored is not None:
        return _report_read(stored)

    rows = (
        await session.execute(
            select(GradingResult, Question)
            .join(Question, Question.id == GradingResult.question_id)
            .where(GradingResult.run_id == run.id)
            .order_by(Question.order_index)
        )
    ).all()
    results = [
        {
            "question_number": question.question_number,
            "ai_score": float(result.ai_score),
            "max_score": float(result.max_score),
            "final_score": (
                float(result.final_score)
                if result.final_score is not None
                else float(result.ai_score)
            ),
            "confidence": float(result.confidence),
            "rationale": result.rationale,
            "error_type": result.error_type,
            "knowledge_points": result.knowledge_points,
        }
        for result, question in rows
    ]
    report_data = await generate_student_report(
        llm,
        student.name,
        exam.exam_code,
        results,
        [],
    )
    report = Report(
        scope_type="student",
        scope_id=student_id,
        exam_id=exam_id,
        grading_run_id=run.id,
        content_markdown=report_data["content_markdown"],
        data=report_data["data"],
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return _report_read(report)
