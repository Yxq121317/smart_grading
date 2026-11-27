from typing import Literal

from pydantic import BaseModel, Field

ErrorType = Literal[
    "info_filter",
    "concept_misread",
    "incomplete_summary",
    "argument_analysis",
    "evidence_misuse",
    "expression",
    "off_topic",
    "blank",
    "mcq_wrong",
]

ERROR_TYPES = {
    "info_filter",
    "concept_misread",
    "incomplete_summary",
    "argument_analysis",
    "evidence_misuse",
    "expression",
    "off_topic",
    "blank",
    "mcq_wrong",
}


class QuestionStructure(BaseModel):
    task_type: str
    answer_requirements: list[str] = Field(default_factory=list)
    knowledge_points: list[str] = Field(default_factory=list)
    scoring_mode: Literal["exact_match", "rubric"]
    notes: str = ""


class RubricPoint(BaseModel):
    id: str
    description: str
    score: float = Field(gt=0)
    evidence_hint: str = ""


class RubricOutput(BaseModel):
    max_score: float = Field(gt=0)
    points: list[RubricPoint]
    scoring_rules: str = ""


class PointResult(BaseModel):
    point_id: str
    hit: bool
    score: float = Field(ge=0)
    evidence: str = ""
    comment: str = ""


class GradeOutput(BaseModel):
    score: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    point_results: list[PointResult]
    rationale: str
    needs_review: bool = False


class ErrorAnalysisOutput(BaseModel):
    primary_error_type: ErrorType
    secondary_error_types: list[ErrorType] = Field(default_factory=list)
    evidence: str
    suggestion: str


class ReportNarrative(BaseModel):
    summary: str
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ReviewCorrection(BaseModel):
    result_id: int
    final_score: float
    instruction: str = ""
    new_rationale: str | None = None


class ReviewRequest(BaseModel):
    corrections: list[ReviewCorrection] = Field(default_factory=list)
