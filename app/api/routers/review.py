from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_grading_service, get_session
from app.db.models import GradingResult, GradingRun
from app.schemas.grading import ReviewRequest
from app.services.grading import GradingService

router = APIRouter(prefix="/api/grading-runs", tags=["review"])


@router.post("/{run_id}/review", status_code=status.HTTP_202_ACCEPTED)
async def review_grading_run(
    run_id: int,
    payload: ReviewRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[GradingService, Depends(get_grading_service)],
) -> dict:
    run = await session.get(GradingRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="grading run not found")
    if run.status != "awaiting_review":
        raise HTTPException(status_code=409, detail="grading run is not awaiting review")

    result_ids = set(
        (
            await session.execute(
                select(GradingResult.id).where(GradingResult.run_id == run_id)
            )
        ).scalars()
    )
    if any(
        correction.result_id not in result_ids
        for correction in payload.corrections
    ):
        raise HTTPException(
            status_code=400,
            detail="correction result does not belong to run",
        )

    background_tasks.add_task(
        service.resume,
        run_id,
        [correction.model_dump() for correction in payload.corrections],
    )
    return {"status": "resuming"}
