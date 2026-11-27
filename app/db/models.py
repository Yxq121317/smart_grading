from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_index: Mapped[int] = mapped_column(SmallInteger, unique=True)
    exam_code: Mapped[str] = mapped_column(Text, unique=True)
    year: Mapped[int] = mapped_column(SmallInteger)
    paper_name: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, default="语文")
    category: Mapped[str] = mapped_column(Text, default="论述类文本阅读")
    compilation: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(Text)
    source_header: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    passages: Mapped[list["Passage"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


class Passage(Base):
    __tablename__ = "passages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(SmallInteger, default=1)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    paragraphs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    exam: Mapped[Exam] = relationship(back_populates="passages")
    questions: Mapped[list["Question"]] = relationship(back_populates="passage")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"))
    passage_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("passages.id", ondelete="SET NULL")
    )
    question_number: Mapped[int] = mapped_column(SmallInteger)
    order_index: Mapped[int] = mapped_column(SmallInteger)
    stem: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    correct_answer: Mapped[str | None] = mapped_column(Text)
    answer_points: Mapped[list[str]] = mapped_column(JSONB, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    exam: Mapped[Exam] = relationship(back_populates="questions")
    passage: Mapped[Passage | None] = relationship(back_populates="questions")
    rubrics: Mapped[list["Rubric"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_file: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exam_count: Mapped[int] = mapped_column(Integer)
    question_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ClassGroup(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    grade: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, default="语文")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    students: Mapped[list["Student"]] = relationship(
        back_populates="class_group", cascade="all, delete-orphan"
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    class_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("classes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    student_no: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    class_group: Mapped[ClassGroup] = relationship(back_populates="students")
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"))
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(Text, default="api")
    status: Mapped[str] = mapped_column(Text, default="pending")
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exam: Mapped[Exam] = relationship()
    student: Mapped[Student] = relationship(back_populates="submissions")
    answers: Mapped[list["StudentAnswer"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )
    runs: Mapped[list["GradingRun"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("submissions.id", ondelete="CASCADE")
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="CASCADE")
    )
    selected_options: Mapped[list[str]] = mapped_column(JSONB, default=list)
    answer_text: Mapped[str | None] = mapped_column(Text)
    synthetic_profile: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    submission: Mapped[Submission] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


class Rubric(Base):
    __tablename__ = "rubrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    source: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    question: Mapped[Question] = relationship(back_populates="rubrics")
    grading_results: Mapped[list["GradingResult"]] = relationship(back_populates="rubric")


class GradingRun(Base):
    __tablename__ = "grading_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("submissions.id", ondelete="CASCADE")
    )
    rubric_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rubrics.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, default="pending")
    graph_thread_id: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    submission: Mapped[Submission] = relationship(back_populates="runs")
    rubric_version: Mapped[Rubric | None] = relationship()
    results: Mapped[list["GradingResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class GradingResult(Base):
    __tablename__ = "grading_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("grading_runs.id", ondelete="CASCADE")
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="CASCADE")
    )
    rubric_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rubrics.id", ondelete="SET NULL")
    )
    ai_score: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    max_score: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    point_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    knowledge_points: Mapped[list[str]] = mapped_column(JSONB, default=list)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_evidence: Mapped[str | None] = mapped_column(Text)
    final_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[GradingRun] = relationship(back_populates="results")
    question: Mapped[Question] = relationship()
    rubric: Mapped[Rubric | None] = relationship(back_populates="grading_results")
    corrections: Mapped[list["TeacherCorrection"]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )


class TeacherCorrection(Base):
    __tablename__ = "teacher_corrections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    result_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("grading_results.id", ondelete="CASCADE"),
        unique=True,
    )
    teacher_name: Mapped[str | None] = mapped_column(Text)
    instruction: Mapped[str | None] = mapped_column(Text)
    old_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    new_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    old_rationale: Mapped[str | None] = mapped_column(Text)
    new_rationale: Mapped[str | None] = mapped_column(Text)
    old_rubric: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_rubric: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    result: Mapped[GradingResult] = relationship(back_populates="corrections")


class CalibrationLog(Base):
    __tablename__ = "calibration_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exams.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="CASCADE")
    )
    instruction: Mapped[str] = mapped_column(Text)
    old_rubric_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("rubrics.id"))
    new_rubric_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("rubrics.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    exam: Mapped[Exam] = relationship()
    question: Mapped[Question] = relationship()


class ErrorCategory(Base):
    __tablename__ = "error_categories"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope_type: Mapped[str] = mapped_column(Text)
    scope_id: Mapped[int] = mapped_column(BigInteger)
    exam_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("exams.id", ondelete="CASCADE")
    )
    grading_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("grading_runs.id", ondelete="SET NULL")
    )
    content_markdown: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    exam: Mapped[Exam | None] = relationship()
