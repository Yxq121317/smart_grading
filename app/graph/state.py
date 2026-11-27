from typing import Annotated, Literal, TypedDict


class QuestionContext(TypedDict):
    question_id: int
    question_number: int
    exam_id: int
    question_type: Literal["single_choice", "subjective"]
    stem: str
    passage: str
    options: list[dict]
    correct_answer: str | None
    answer_points: list[str]
    explanation: str | None
    max_score: float
    student_answer: str | None
    selected_options: list[str]
    rubric: dict | None
    rubric_id: int | None
    rubric_fallback: bool


class QuestionResult(TypedDict):
    question_id: int
    question_number: int
    question_type: str
    ai_score: float
    max_score: float
    confidence: float
    needs_review: bool
    rationale: str
    student_answer: str | None
    point_results: list[dict]
    knowledge_points: list[str]
    rubric_id: int | None
    error_type: str | None
    error_evidence: str | None
    final_score: float | None
    reviewed: bool


class ReviewItem(TypedDict):
    result_id: int
    question_id: int
    question_number: int
    question_type: str
    student_answer: str | None
    ai_score: float
    max_score: float
    confidence: float
    rationale: str
    point_results: list[dict]


class TeacherCorrection(TypedDict):
    result_id: int
    final_score: float
    instruction: str
    new_rationale: str | None


def merge_results(
    left: list[QuestionResult] | None,
    right: list[QuestionResult] | None,
) -> list[QuestionResult]:
    merged: dict[int, QuestionResult] = {}
    for item in (left or []):
        merged[item["question_id"]] = item
    for item in (right or []):
        merged[item["question_id"]] = item
    return sorted(merged.values(), key=lambda item: item["question_number"])


class GradingState(TypedDict, total=False):
    exam_id: int
    exam_code: str
    student_id: int
    student_name: str
    submission_id: int
    grading_run_id: int
    requested_rubric_version_id: int | None
    question_contexts: list[QuestionContext]
    results: Annotated[list[QuestionResult], merge_results]
    corrected_results: list[QuestionResult] | None
    review_items: list[ReviewItem]
    corrections: list[TeacherCorrection]
    report: dict | None
    total_score: float
    max_score: float
    error: str | None


class QuestionState(TypedDict, total=False):
    context: QuestionContext
    structure: dict | None
    structure_fallback: bool
    rubric: dict | None
    rubric_fallback: bool
    result: QuestionResult | None
    error_type: str | None
    error_evidence: str | None
    suggestion: str | None
    error_fallback: bool
