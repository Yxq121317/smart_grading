from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_grading_service, get_llm, get_session
from app.schemas.rubric import CalibrationRead, CalibrationRequest
from app.services.calibration import CalibrationError, calibrate
from app.services.grading import GradingService
from app.services.llm import LLMProtocol

router = APIRouter(prefix="/api/exams", tags=["calibration"])


@router.post("/{exam_id}/calibrate", response_model=CalibrationRead)
async def calibrate_endpoint(
    exam_id: int,
    payload: CalibrationRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMProtocol, Depends(get_llm)],
    service: Annotated[GradingService, Depends(get_grading_service)],
) -> CalibrationRead:
    try:
        result = await calibrate(
            session,
            llm,
            exam_id,
            payload.question_id,
            payload.instruction,
            payload.re_grade_all,
        )
    except CalibrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rerun_ids: list[int] = []
    for submission_id in result["rerun_submission_ids"]:
        run_id = await service.create_run(
            submission_id,
            requested_rubric_version_id=result["rubric_id"],
        )
        background_tasks.add_task(service.run, run_id)
        rerun_ids.append(run_id)

    return CalibrationRead(
        rubric_id=result["rubric_id"],
        version=result["version"],
        points=result["points"],
        total_score=result["total_score"],
        rerun_ids=rerun_ids,
    )
