from pydantic import BaseModel, ConfigDict


class ExamSummary(BaseModel):
    id: int
    exam_code: str
    year: int
    paper_name: str
    question_count: int


class PassageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    author: str | None
    content: str
    paragraphs: list[str]


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_number: int
    order_index: int
    stem: str
    question_type: str
    options: list[dict]
    correct_answer: str | None
    answer_points: list[str]
    explanation: str | None
    max_score: float | None
    active_rubric: dict | None = None


class ExamDetail(BaseModel):
    id: int
    exam_code: str
    year: int
    paper_name: str
    passage: PassageRead
    questions: list[QuestionRead]
