from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.repositories import get_exam_detail, list_exams
from app.schemas.exam import ExamDetail, ExamSummary

router = APIRouter(prefix="/api/exams", tags=["exams"])


@router.get("", response_model=list[ExamSummary])
async def list_exams_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ExamSummary]:
    return await list_exams(session)


@router.get("/{exam_id}", response_model=ExamDetail)
async def get_exam_endpoint(
    exam_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExamDetail:
    exam = await get_exam_detail(session, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    return exam
