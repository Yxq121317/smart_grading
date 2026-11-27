from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_grading_service
from app.schemas.submission import GradingRunRead
from app.services.grading import GradingService

router = APIRouter(prefix="/api/grading-runs", tags=["grading"])


@router.get("/{run_id}", response_model=GradingRunRead)
async def get_grading_run(
    run_id: int,
    service: Annotated[GradingService, Depends(get_grading_service)],
) -> GradingRunRead:
    run = await service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="grading run not found")
    return run
