from pydantic import BaseModel, Field


class ReportRead(BaseModel):
    scope_type: str
    scope_id: int
    exam_id: int | None
    grading_run_id: int | None = None
    content_markdown: str
    data: dict = Field(default_factory=dict)


class BadCaseRead(BaseModel):
    question_id: int
    question_number: int
    student_name: str
    student_answer: str | None
    ai_score: float
    final_score: float
    confidence: float
    rationale: str | None
    error_type: str | None
    reason: str
