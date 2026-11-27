import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, text

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.config import Settings
from app.db.models import (
    ClassGroup,
    Exam,
    GradingResult,
    GradingRun,
    Passage,
    Question,
    Student,
    StudentAnswer,
    Submission,
    TeacherCorrection,
)
from app.db.seed import seed_error_categories
from app.db.session import create_engine_and_factory
from app.main import create_app
from app.schemas.grading import (
    ErrorAnalysisOutput,
    GradeOutput,
    PointResult,
    QuestionStructure,
    ReportNarrative,
    RubricOutput,
    RubricPoint,
)
from tests.fakes import FakeLLMClient

TEST_CONTAINER = os.environ.get("PG_CONTAINER", "agent_test-postgres")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or Settings().test_database_url

TABLES = [
    "reports",
    "teacher_corrections",
    "calibration_logs",
    "grading_results",
    "grading_runs",
    "rubrics",
    "student_answers",
    "submissions",
    "students",
    "classes",
    "error_categories",
    "import_runs",
    "questions",
    "passages",
    "exams",
]

@pytest.fixture(scope="session")
def test_database():
    subprocess.run(
        ["docker", "exec", TEST_CONTAINER, "createdb", "-U", "postgres", "Mark_test"],
        capture_output=True,
        check=False,
    )
    schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            TEST_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            "Mark_test",
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
        ],
        input=schema_path.read_bytes(),
        check=True,
    )
    yield


@pytest.fixture
def test_settings(test_database):
    return Settings(
        _env_file=None,
        mark_database_url=TEST_DATABASE_URL,
        langfuse_enabled=False,
        api_key="test",
    )


@pytest.fixture
def settings(test_settings):
    return test_settings


@pytest_asyncio.fixture
async def test_session_factory(test_database):
    engine, factory = create_engine_and_factory(TEST_DATABASE_URL)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(test_session_factory):
    async with test_session_factory() as session:
        await session.execute(
            text(f"TRUNCATE TABLE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        )
        await seed_error_categories(session)
        await session.commit()
    yield


@pytest_asyncio.fixture
async def session(test_session_factory, clean_tables):
    async with test_session_factory() as db_session:
        yield db_session
        await db_session.rollback()


@pytest_asyncio.fixture
async def sample_exam(session):
    class_group = ClassGroup(name="测试班", grade="高二")
    session.add(class_group)
    await session.flush()

    student = Student(class_id=class_group.id, name="测试学生", student_no="S001")
    session.add(student)
    await session.flush()

    exam = Exam(
        source_index=1,
        exam_code="TEST-EXAM",
        year=2024,
        paper_name="测试卷",
        compilation="测试汇编",
        source_file="test.docx",
        source_header="（2024年测试卷）",
    )
    session.add(exam)
    await session.flush()

    passage = Passage(
        exam_id=exam.id,
        order_index=1,
        title=None,
        author=None,
        content="测试材料",
        paragraphs=["测试材料"],
    )
    session.add(passage)
    await session.flush()

    mcq_options_q1 = [
        {"label": "A", "content": "选项A", "is_correct": False},
        {"label": "B", "content": "选项B", "is_correct": False},
        {"label": "C", "content": "选项C", "is_correct": True},
        {"label": "D", "content": "选项D", "is_correct": False},
    ]
    mcq_options_q2 = [
        {"label": "A", "content": "选项A", "is_correct": True},
        {"label": "B", "content": "选项B", "is_correct": False},
        {"label": "C", "content": "选项C", "is_correct": False},
        {"label": "D", "content": "选项D", "is_correct": False},
    ]
    questions = [
        Question(
            exam_id=exam.id,
            passage_id=passage.id,
            question_number=1,
            order_index=1,
            stem="第1题",
            question_type="single_choice",
            options=mcq_options_q1,
            correct_answer="C",
            answer_points=[],
            explanation="第1题解析",
            max_score=3,
        ),
        Question(
            exam_id=exam.id,
            passage_id=passage.id,
            question_number=2,
            order_index=2,
            stem="第2题",
            question_type="single_choice",
            options=mcq_options_q2,
            correct_answer="A",
            answer_points=[],
            explanation="第2题解析",
            max_score=3,
        ),
        Question(
            exam_id=exam.id,
            passage_id=passage.id,
            question_number=3,
            order_index=3,
            stem="第3题",
            question_type="subjective",
            options=[],
            correct_answer="参考答案：点1；点2；点3",
            answer_points=["点1", "点2", "点3"],
            explanation="第3题解析",
            max_score=6,
        ),
    ]
    session.add_all(questions)
    await session.commit()

    return {
        "exam_id": exam.id,
        "exam_code": exam.exam_code,
        "class_id": class_group.id,
        "student_id": student.id,
        "passage": {"content": passage.content, "paragraphs": passage.paragraphs},
        "questions": [
            {
                "id": question.id,
                "number": question.question_number,
                "type": question.question_type,
                "stem": question.stem,
                "options": question.options,
                "correct_answer": question.correct_answer,
                "answer_points": question.answer_points,
                "explanation": question.explanation,
                "max_score": float(question.max_score),
            }
            for question in questions
        ],
    }


@pytest_asyncio.fixture
async def sample_submission(session, sample_exam):
    submission = Submission(
        exam_id=sample_exam["exam_id"],
        student_id=sample_exam["student_id"],
        source="synthetic",
    )
    session.add(submission)
    await session.flush()

    session.add_all(
        [
            StudentAnswer(
                submission_id=submission.id,
                question_id=sample_exam["questions"][0]["id"],
                selected_options=["C"],
            ),
            StudentAnswer(
                submission_id=submission.id,
                question_id=sample_exam["questions"][1]["id"],
                selected_options=["A"],
            ),
            StudentAnswer(
                submission_id=submission.id,
                question_id=sample_exam["questions"][2]["id"],
                answer_text="只答出第一点",
            ),
        ]
    )
    await session.commit()

    return {
        "submission_id": submission.id,
        "exam_id": sample_exam["exam_id"],
        "student_id": sample_exam["student_id"],
        "questions": sample_exam["questions"],
    }


@pytest_asyncio.fixture
async def seeded_two_runs_same_submission(session, sample_exam, sample_submission):
    question_id = sample_submission["questions"][2]["id"]
    old_run = GradingRun(
        submission_id=sample_submission["submission_id"],
        graph_thread_id="old-run",
        status="completed",
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    new_run = GradingRun(
        submission_id=sample_submission["submission_id"],
        graph_thread_id="new-run",
        status="completed",
    )
    session.add_all([old_run, new_run])
    await session.flush()

    session.add_all(
        [
            GradingResult(
                run_id=old_run.id,
                question_id=question_id,
                ai_score=3,
                max_score=6,
                confidence=0.9,
                needs_review=False,
                rationale="old",
                point_results=[],
                knowledge_points=["筛选并整合信息"],
                error_type="incomplete_summary",
                final_score=3,
                reviewed=False,
            ),
            GradingResult(
                run_id=new_run.id,
                question_id=question_id,
                ai_score=5,
                max_score=6,
                confidence=0.9,
                needs_review=False,
                rationale="new",
                point_results=[],
                knowledge_points=["筛选并整合信息"],
                error_type="incomplete_summary",
                final_score=5,
                reviewed=False,
            ),
        ]
    )
    await session.commit()
    return {
        "class_id": sample_exam["class_id"],
        "exam_id": sample_exam["exam_id"],
        "student_id": sample_exam["student_id"],
        "submission_id": sample_submission["submission_id"],
        "old_run_id": old_run.id,
        "new_run_id": new_run.id,
    }


@pytest_asyncio.fixture
async def seeded_bad_cases(session, sample_exam, sample_submission):
    run = GradingRun(
        submission_id=sample_submission["submission_id"],
        graph_thread_id="bad-cases",
        status="completed",
    )
    session.add(run)
    await session.flush()

    q1_id = sample_exam["questions"][0]["id"]
    q3_id = sample_exam["questions"][2]["id"]
    q1_result = GradingResult(
        run_id=run.id,
        question_id=q1_id,
        ai_score=3,
        max_score=3,
        confidence=0.9,
        needs_review=False,
        rationale="选择正确",
        point_results=[],
        knowledge_points=[],
        error_type=None,
        final_score=1,
        reviewed=True,
    )
    q3_result = GradingResult(
        run_id=run.id,
        question_id=q3_id,
        ai_score=4,
        max_score=6,
        confidence=0.5,
        needs_review=False,
        rationale="低置信度",
        point_results=[],
        knowledge_points=["筛选并整合信息"],
        error_type="incomplete_summary",
        final_score=4,
        reviewed=False,
    )
    session.add_all([q1_result, q3_result])
    await session.flush()
    session.add(
        TeacherCorrection(
            result_id=q1_result.id,
            instruction="改判",
            old_score=3,
            new_score=1,
            old_rationale="选择正确",
            new_rationale="改判",
        )
    )
    await session.commit()
    return {"exam_id": sample_exam["exam_id"]}


@pytest_asyncio.fixture
async def app(test_settings, test_session_factory, fake_llm):
    return create_app(
        test_settings,
        session_factory=test_session_factory,
        llm=fake_llm,
        checkpointer=InMemorySaver(),
    )


@pytest_asyncio.fixture
async def app_client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def question_context(session, sample_exam):
    question = await session.get(Question, sample_exam["questions"][2]["id"])
    passage = (
        await session.execute(select(Passage).where(Passage.exam_id == sample_exam["exam_id"]))
    ).scalars().first()
    return {
        "question_id": question.id,
        "question_number": question.question_number,
        "exam_id": question.exam_id,
        "question_type": question.question_type,
        "stem": question.stem,
        "passage": passage.content,
        "options": question.options,
        "correct_answer": question.correct_answer,
        "answer_points": question.answer_points,
        "explanation": question.explanation,
        "max_score": float(question.max_score),
        "student_answer": "",
        "selected_options": [],
        "rubric": None,
        "rubric_id": None,
        "rubric_fallback": False,
    }


@pytest.fixture
def low_score_result():
    return {
        "question_id": 3,
        "question_number": 3,
        "question_type": "subjective",
        "ai_score": 2.0,
        "max_score": 6.0,
        "confidence": 0.8,
        "needs_review": False,
        "rationale": "只答出一点",
        "point_results": [],
        "knowledge_points": [],
        "error_type": None,
        "error_evidence": None,
        "final_score": None,
        "reviewed": False,
    }


@pytest.fixture
def fake_llm():
    return FakeLLMClient(
        {
            "structure": QuestionStructure(
                task_type="概括题",
                knowledge_points=["筛选并整合信息"],
                scoring_mode="rubric",
            ),
            "rubric": RubricOutput(
                max_score=6,
                points=[
                    RubricPoint(id="p1", description="点1", score=2),
                    RubricPoint(id="p2", description="点2", score=2),
                    RubricPoint(id="p3", description="点3", score=2),
                ],
            ),
            "grade": GradeOutput(
                score=4,
                confidence=0.9,
                point_results=[
                    PointResult(point_id="p1", hit=True, score=2),
                    PointResult(point_id="p2", hit=True, score=2),
                    PointResult(point_id="p3", hit=False, score=0),
                ],
                rationale="答出两点",
            ),
            "error_analysis": ErrorAnalysisOutput(
                primary_error_type="incomplete_summary",
                evidence="少一个采分点",
                suggestion="分点概括",
            ),
            "student_report": ReportNarrative(
                summary="学生报告",
                weaknesses=["概括不全"],
                suggestions=["分点作答"],
            ),
            "class_report": ReportNarrative(
                summary="班级报告",
                weaknesses=["概括不全"],
                suggestions=["分点作答"],
            ),
        }
    )
