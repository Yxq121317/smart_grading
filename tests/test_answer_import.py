import json

import pytest
from sqlalchemy import select

from app.db.models import Student, StudentAnswer, Submission
from app.services.answer_import import (
    AnswerSheetError,
    parse_answer_sheet,
    parse_csv,
    parse_json,
)


def test_parse_csv_with_chinese_headers() -> None:
    data = (
        "学号,姓名,Q1,第2题,3\n"
        '2023001,张三,C,A,"西方媒体用了竞争性真相的三种手法"\n'
        '2023002,李四,D,B,\n'
    ).encode("utf-8-sig")

    rows = parse_csv(data)

    assert [row.student_name for row in rows] == ["张三", "李四"]
    assert rows[0].student_no == "2023001"
    assert rows[0].answers == {1: "C", 2: "A", 3: "西方媒体用了竞争性真相的三种手法"}
    assert rows[1].answers == {1: "D", 2: "B"}


def test_parse_json_payload() -> None:
    payload = [
        {"student_no": "2023003", "student_name": "王五", "answers": {"1": "A", "4": "答案"}},
        {"name": "赵六", "answers": ["B", "C"]},
    ]
    rows = parse_json(json.dumps(payload).encode("utf-8"))

    assert rows[0].student_no == "2023003"
    assert rows[0].answers == {1: "A", 4: "答案"}
    assert rows[1].student_name == "赵六"
    assert rows[1].answers == {1: "B", 2: "C"}


def test_parse_answer_sheet_rejects_unknown_suffix() -> None:
    with pytest.raises(AnswerSheetError):
        parse_answer_sheet("sheet.pdf", b"%PDF-1.4")


def test_missing_question_columns_is_rejected() -> None:
    with pytest.raises(AnswerSheetError):
        parse_csv("学号,姓名\n2023001,张三\n".encode())


async def test_import_endpoint_creates_submissions(app_client, sample_exam) -> None:
    csv_bytes = (
        "student_no,student_name,Q1,Q2,Q3\n"
        'U001,导入学生一,C,A,"答出第一点"\n'
        "U002,导入学生二,D,B,答出第二点\n"
    ).encode("utf-8-sig")

    response = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/submissions/import",
        files={"file": ("sheet.csv", csv_bytes, "text/csv")},
        data={"class_name": "测试班"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] == 2
    assert body["skipped"] == 0

    session = app_client._transport.app.state.session_factory
    async with session() as db:
        students = (
            await db.execute(select(Student).where(Student.student_no.in_(["U001", "U002"])))
        ).scalars().all()
        assert {student.name for student in students} == {"导入学生一", "导入学生二"}
        assert all(student.class_id == sample_exam["class_id"] for student in students)

        submissions = (
            await db.execute(
                select(Submission).where(Submission.exam_id == sample_exam["exam_id"])
            )
        ).scalars().all()
        assert len(submissions) == 2
        assert {submission.source for submission in submissions} == {"import"}

        first = submissions[0]
        answers = (
            await db.execute(
                select(StudentAnswer).where(StudentAnswer.submission_id == first.id)
            )
        ).scalars().all()
        assert len(answers) == 3
        choice_answers = [answer for answer in answers if answer.selected_options]
        assert len(choice_answers) == 2
        assert all(len(answer.selected_options) == 1 for answer in choice_answers)


async def test_import_twice_skips_existing(app_client, sample_exam) -> None:
    csv_bytes = "student_no,student_name,Q1\nU010,重复学生,A\n".encode()

    first = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/submissions/import",
        files={"file": ("sheet.csv", csv_bytes, "text/csv")},
    )
    second = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/submissions/import",
        files={"file": ("sheet.csv", csv_bytes, "text/csv")},
    )

    assert first.json()["created"] == 1
    assert second.status_code == 201
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == 1


async def test_import_rejects_bad_option(app_client, sample_exam) -> None:
    csv_bytes = "student_no,student_name,Q1\nU020,错选项学生,Z\n".encode()

    response = await app_client.post(
        f"/api/exams/{sample_exam['exam_id']}/submissions/import",
        files={"file": ("sheet.csv", csv_bytes, "text/csv")},
    )

    body = response.json()
    assert body["created"] == 0
    assert body["skipped"] == 1
    assert any("不是合法选项" in message for message in body["errors"])
