"""解析老师上传的答题卡文件（CSV / XLSX / JSON），并落库成可批改的答卷。

文件格式（三选一）：

1. CSV / XLSX，一行一个学生，一题一列：

       student_no,student_name,Q1,Q2,Q3,Q4,Q5
       2023001,张三,C,D,A,"主观题答案…","主观题答案…"

   表头也认 学号 / 姓名 / 第1题 / 1 / q1 这些写法；选择题填 A/B/C/D。

2. JSON：

       [{"student_no": "2023001", "student_name": "张三", "answers": {"1": "C", "4": "…"}}]
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClassGroup, Exam, Question, Student, StudentAnswer, Submission

NO_HEADERS = {"student_no", "studentno", "学号", "考号", "准考证号"}
NAME_HEADERS = {"student_name", "studentname", "姓名", "名字", "学生"}
CLASS_HEADERS = {"class", "class_name", "classname", "班级"}

_QUESTION_HEADER = re.compile(r"^(?:q|第)?(\d+)(?:题)?$", re.IGNORECASE)
_OPTION_LETTER = re.compile(r"[A-Ha-h]")


class AnswerSheetError(ValueError):
    """上传的文件无法解析成答题卡。"""


@dataclass(slots=True)
class SheetRow:
    student_name: str
    answers: dict[int, str] = field(default_factory=dict)
    student_no: str | None = None
    class_name: str | None = None


def question_number_from_header(header: Any) -> int | None:
    """把 ``Q1`` / ``第1题`` / ``1`` 这类表头解析成题号。"""
    text = "" if header is None else str(header).strip().lower().replace(" ", "")
    if not text:
        return None
    match = _QUESTION_HEADER.match(text)
    return int(match.group(1)) if match else None


def _header_kind(header: Any) -> str | None:
    text = "" if header is None else str(header).strip().lower().replace(" ", "")
    if text in NO_HEADERS:
        return "no"
    if text in NAME_HEADERS:
        return "name"
    if text in CLASS_HEADERS:
        return "class"
    return None


def _rows_from_records(records: list[dict[str, Any]]) -> list[SheetRow]:
    if not records:
        raise AnswerSheetError("文件里没有数据行。")

    headers = list(records[0].keys())
    mapping: dict[str, Any] = {}
    answer_columns: list[tuple[int, Any]] = []
    for header in headers:
        kind = _header_kind(header)
        if kind is not None:
            mapping[kind] = header
            continue
        number = question_number_from_header(header)
        if number is not None:
            answer_columns.append((number, header))

    if not answer_columns:
        raise AnswerSheetError(
            "没有找到题目列。表头至少要有 Q1、Q2…（或 第1题、第2题…）这样的列名。"
        )
    if "name" not in mapping and "no" not in mapping:
        raise AnswerSheetError("没有找到学生列。表头需要有 student_name（姓名）或 student_no（学号）。")

    rows: list[SheetRow] = []
    for index, record in enumerate(records, start=2):
        name = str(record.get(mapping.get("name"), "") or "").strip()
        student_no = str(record.get(mapping.get("no"), "") or "").strip() or None
        class_name = str(record.get(mapping.get("class"), "") or "").strip() or None
        if not name and not student_no:
            continue
        answers: dict[int, str] = {}
        for number, header in answer_columns:
            value = record.get(header)
            text = "" if value is None else str(value).strip()
            if text:
                answers[number] = text
        rows.append(
            SheetRow(
                student_name=name or (student_no or f"第 {index} 行"),
                answers=answers,
                student_no=student_no,
                class_name=class_name,
            )
        )
    if not rows:
        raise AnswerSheetError("文件里没有可导入的学生行。")
    return rows


def parse_csv(data: bytes) -> list[SheetRow]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return _rows_from_records(list(reader))


def parse_xlsx(data: bytes) -> list[SheetRow]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - 依赖已写进 pyproject
        raise AnswerSheetError("服务器缺少 openpyxl，无法解析 Excel。") from exc

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    values = list(sheet.iter_rows(values_only=True))
    workbook.close()
    if not values:
        raise AnswerSheetError("Excel 里没有数据。")
    headers = ["" if cell is None else str(cell).strip() for cell in values[0]]
    records = []
    for row in values[1:]:
        records.append(
            {headers[index]: row[index] for index in range(len(headers)) if index < len(row)}
        )
    return _rows_from_records(records)


def parse_json(data: bytes) -> list[SheetRow]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AnswerSheetError(f"JSON 解析失败：{exc.msg}") from exc

    if isinstance(payload, dict):
        payload = payload.get("students") or payload.get("rows") or payload.get("data")
    if not isinstance(payload, list) or not payload:
        raise AnswerSheetError("JSON 需要是学生数组，或带 students 字段的对象。")

    rows: list[SheetRow] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("student_name") or item.get("name") or "").strip()
        student_no = str(item.get("student_no") or item.get("no") or "").strip() or None
        class_name = str(item.get("class_name") or item.get("class") or "").strip() or None
        raw_answers = item.get("answers") or {}
        answers: dict[int, str] = {}
        if isinstance(raw_answers, dict):
            for key, value in raw_answers.items():
                number = question_number_from_header(key)
                text = "" if value is None else str(value).strip()
                if number is not None and text:
                    answers[number] = text
        elif isinstance(raw_answers, list):
            for index, value in enumerate(raw_answers, start=1):
                text = "" if value is None else str(value).strip()
                if text:
                    answers[index] = text
        if not name and not student_no:
            continue
        rows.append(
            SheetRow(
                student_name=name or (student_no or "未命名学生"),
                answers=answers,
                student_no=student_no,
                class_name=class_name,
            )
        )
    if not rows:
        raise AnswerSheetError("JSON 里没有可导入的学生。")
    return rows


def parse_answer_sheet(filename: str, data: bytes) -> list[SheetRow]:
    """按扩展名选择解析器。"""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"xlsx", "xlsm"}:
        return parse_xlsx(data)
    if suffix == "json":
        return parse_json(data)
    if suffix in {"csv", "txt", ""}:
        return parse_csv(data)
    raise AnswerSheetError(f"不支持的文件类型 .{suffix}，请上传 CSV、XLSX 或 JSON。")


def _normalize_choice(raw: str, labels: list[str]) -> str | None:
    text = raw.strip()
    if not text:
        return None
    upper = text.upper()
    if upper in labels:
        return upper
    for letter in _OPTION_LETTER.findall(text):
        candidate = letter.upper()
        if candidate in labels:
            return candidate
    return None


async def import_answer_sheet(
    session: AsyncSession,
    exam_id: int,
    rows: list[SheetRow],
    *,
    default_class_name: str = "导入班级",
) -> dict[str, Any]:
    """把解析好的答题卡写进库，返回导入统计。"""
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise AnswerSheetError("试卷不存在。")

    questions = (
        await session.execute(select(Question).where(Question.exam_id == exam_id))
    ).scalars().all()
    if not questions:
        raise AnswerSheetError("这份试卷还没有题目，无法导入答卷。")
    by_number = {question.question_number: question for question in questions}

    class_cache: dict[str, ClassGroup] = {}
    created = 0
    skipped = 0
    errors: list[str] = []

    for row in rows:
        class_name = (row.class_name or default_class_name).strip() or default_class_name
        class_group = class_cache.get(class_name)
        if class_group is None:
            class_group = (
                await session.execute(
                    select(ClassGroup).where(ClassGroup.name == class_name)
                )
            ).scalars().first()
            if class_group is None:
                class_group = ClassGroup(name=class_name)
                session.add(class_group)
                await session.flush()
            class_cache[class_name] = class_group

        student = None
        if row.student_no:
            student = (
                await session.execute(
                    select(Student).where(Student.student_no == row.student_no)
                )
            ).scalars().first()
        if student is None:
            student = Student(
                class_id=class_group.id,
                name=row.student_name,
                student_no=row.student_no,
            )
            session.add(student)
            await session.flush()

        existing = (
            await session.execute(
                select(Submission).where(
                    Submission.exam_id == exam_id,
                    Submission.student_id == student.id,
                )
            )
        ).scalars().first()
        if existing is not None:
            skipped += 1
            errors.append(f"{row.student_name}：这份试卷已经有答卷，跳过。")
            continue

        pending: list[StudentAnswer] = []
        row_error = False
        for number, raw in row.answers.items():
            question = by_number.get(number)
            if question is None:
                errors.append(f"{row.student_name}：试卷里没有第 {number} 题，已忽略。")
                continue
            if question.question_type == "single_choice":
                labels = [
                    str(option.get("label", "")).strip().upper()
                    for option in (question.options or [])
                    if option.get("label")
                ]
                letter = _normalize_choice(raw, labels)
                if letter is None:
                    errors.append(
                        f"{row.student_name}：第 {number} 题答案 {raw!r} 不是合法选项，已忽略该题。"
                    )
                    row_error = True
                    continue
                pending.append(StudentAnswer(question_id=question.id, selected_options=[letter]))
            else:
                pending.append(StudentAnswer(question_id=question.id, answer_text=raw))

        if not pending:
            skipped += 1
            errors.append(f"{row.student_name}：没有任何有效答案，跳过。")
            continue

        submission = Submission(exam_id=exam_id, student_id=student.id, source="import")
        session.add(submission)
        await session.flush()
        for answer in pending:
            answer.submission_id = submission.id
            session.add(answer)
        created += 1
        if row_error:
            errors.append(f"{row.student_name}：已导入，但有题目被跳过。")

    await session.commit()
    return {
        "exam_id": exam_id,
        "exam_code": exam.exam_code,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }
