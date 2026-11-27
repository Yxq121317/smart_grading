from pydantic import BaseModel, Field


class AnswerCreate(BaseModel):
    question_id: int
    selected_options: list[str] = Field(default_factory=list)
    answer_text: str | None = None


class SubmissionCreate(BaseModel):
    student_id: int
    answers: list[AnswerCreate] = Field(default_factory=list)


class SubmissionRead(BaseModel):
    id: int
    exam_id: int
    student_id: int
    status: str
    total_score: float | None
    max_score: float | None
    answers: list[dict] = Field(default_factory=list)


class GradingRunRead(BaseModel):
    id: int
    submission_id: int
    status: str
    model: str | None
    error: str | None
    results: list[dict] = Field(default_factory=list)
    review_items: list[dict] = Field(default_factory=list)
