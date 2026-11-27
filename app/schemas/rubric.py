from datetime import datetime

from pydantic import BaseModel, Field


class CalibrationRequest(BaseModel):
    question_id: int
    instruction: str
    re_grade_all: bool = False


class CalibrationRead(BaseModel):
    rubric_id: int
    version: int
    points: list[dict]
    total_score: float
    rerun_ids: list[int] = Field(default_factory=list)


class RubricRead(BaseModel):
    id: int
    question_id: int
    version: int
    points: list[dict]
    total_score: float
    source: str
    active: bool
    created_at: datetime
