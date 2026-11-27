from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.models import Question, Rubric
from app.schemas.rubric import RubricRead

router = APIRouter(prefix="/api/questions", tags=["rubrics"])


@router.get("/{question_id}/rubrics", response_model=list[RubricRead])
async def list_question_rubrics(
    question_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RubricRead]:
    question = await session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="question not found")
    rubrics = (
        await session.execute(
            select(Rubric)
            .where(Rubric.question_id == question_id)
            .order_by(Rubric.version.desc())
        )
    ).scalars().all()
    return [
        RubricRead(
            id=rubric.id,
            question_id=rubric.question_id,
            version=rubric.version,
            points=rubric.points,
            total_score=float(rubric.total_score),
            source=rubric.source,
            active=rubric.active,
            created_at=rubric.created_at,
        )
        for rubric in rubrics
    ]
