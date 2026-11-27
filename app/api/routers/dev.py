from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.schemas.report import BadCaseRead
from app.services.bad_cases import list_bad_cases
from app.services.synthetic import seed_synthetic

router = APIRouter(prefix="/api/dev", tags=["dev"])


class SeedRequest(BaseModel):
    exam_code: str = "2023-新高考Ⅰ卷"
    students: int = 10
    class_name: str = "高二(1)班"
    seed: int = 42


@router.post("/seed-synthetic")
async def seed_synthetic_endpoint(
    payload: SeedRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    try:
        return await seed_synthetic(
            session,
            payload.exam_code,
            students=payload.students,
            class_name=payload.class_name,
            seed=payload.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/bad-cases", response_model=list[BadCaseRead])
async def bad_cases_endpoint(
    exam_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BadCaseRead]:
    return await list_bad_cases(session, exam_id)
