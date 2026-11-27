from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/dashboard")
async def dashboard(
    session: Annotated[AsyncSession, Depends(get_session)],
    exam_code: str = "2023-新高考Ⅰ卷",
    class_id: int | None = None,
    student_id: int | None = None,
) -> dict:
    try:
        return await build_dashboard(
            session,
            exam_code,
            class_id=class_id,
            student_id=student_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
