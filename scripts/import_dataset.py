#!/usr/bin/env python3
"""把 data/ 下的高考真题 docx 导入 PostgreSQL 的题库表。

只使用标准库。生成 SQL 后，通过本机 Docker 里的 Postgres 容器执行，
默认容器名 agent_test-postgres，数据库 Mark，用户 postgres。

用法：
    python -X utf8 scripts/import_dataset.py
    python -X utf8 scripts/import_dataset.py --apply
    python -X utf8 scripts/import_dataset.py --reset --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

EXAM_RE = re.compile(r"^（(\d{4})年(.+?卷)）(.*)$")
QUESTION_RE = re.compile(r"^(\d+)[．.](.*)$")
OPTION_RE = re.compile(r"^([A-D])[．.](.*)$")
YEAR_HEADING_RE = re.compile(r"^〖(\d{4})年高考真题〗$")
EXPLAIN_PREFIXES = ("【解析】", "【分析】")
CIRCLED_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

SUBJECT = "语文"
CATEGORY = "论述类文本阅读"
COMPILATION = "五年（2019-2023）高考真题分项汇编 专题03 论述类文本阅读"


def normalize_newlines(text: str) -> str:
    """把 docx 里的回车统一成换行，并处理不换行空格。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


def normalize_inline(text: str) -> str:
    """题干和选项统一压成一行。"""
    return re.sub(r"\s+", " ", normalize_newlines(text)).strip()


def read_docx(path: Path):
    """读取 docx 的正文段落、媒体文件和年份标题。"""
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
        media = [
            {"path": name, "bytes": zf.getinfo(name).file_size}
            for name in zf.namelist()
            if name.startswith("word/media/")
        ]

    paragraphs = []
    for para in root.find(W + "body").findall(W + "p"):
        text = "".join(node.text or "" for node in para.iter(W + "t"))
        text = normalize_newlines(text).strip()
        if text:
            paragraphs.append(text)

    year_headings = []
    for index, text in enumerate(paragraphs):
        match = YEAR_HEADING_RE.match(text)
        if match:
            year_headings.append({"paragraph": index, "year": int(match.group(1)), "text": text})
    return paragraphs, media, year_headings


def split_by_question_numbers(text: str, numbers: list[int]) -> dict[int, str]:
    """按题号把答案/解析整段切开；保留题号，后续再剥离。"""
    positions = []
    for number in numbers:
        match = re.search(rf"(?<!\d){number}[．.]", text)
        if match:
            positions.append((number, match.start()))
    positions.sort(key=lambda item: item[1])

    chunks: dict[int, str] = {}
    for index, (number, start) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(text)
        chunks[number] = text[start:end].strip()
    return chunks


def strip_question_number(text: str, number: int) -> str:
    return re.sub(rf"^\s*{number}[．.]\s*", "", text)


def extract_title_author(paragraphs: list[str]):
    """对“标题 / 作者 / 正文”开头的文章做轻量识别，识别不了就全部当正文。"""
    title = None
    author = None
    body = list(paragraphs)

    if body:
        first = body[0]
        if len(first) <= 30 and not re.search(r"[。！？；]$", first) and not first.startswith("（"):
            title = body.pop(0)
            if body and re.fullmatch(r"[一-鿿·]{2,6}", body[0]):
                author = body.pop(0)

    return title, author, body


def split_answer_points(text: str) -> list[str]:
    """把主观题参考答案切成采分点，作为后续生成评分细则的初稿。"""
    text = text.strip()
    if not text:
        return []
    if text.startswith("示例"):
        return [text]

    marks = [m for m in re.finditer(f"[{CIRCLED_MARKS}]", text)]
    if marks:
        return _slice_at_marks(text, marks)

    marks = [m for m in re.finditer(r"[（(]\s*\d+\s*[）)]", text)]
    if len(marks) >= 2:
        return _slice_at_marks(text, marks)

    if "优点" in text and "缺点" in text:
        parts = [part.strip() for part in re.split(r"(?=优点[:：]|缺点[:：])", text) if part.strip()]
        if len(parts) >= 2:
            return parts

    if "；" in text:
        parts = [part.strip() for part in text.split("；") if part.strip()]
        if len(parts) >= 2:
            return parts

    return [text]


def _slice_at_marks(text: str, marks) -> list[str]:
    points = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        points.append(text[mark.start():end].strip())
    return points


def parse_docx(path: Path):
    """解析一份汇编 docx，返回按试卷组组织的结构化数据。"""
    paragraphs, media, year_headings = read_docx(path)
    exam_starts = [(index, EXAM_RE.match(text)) for index, text in enumerate(paragraphs) if EXAM_RE.match(text)]

    exams = []
    issues = {
        "year_heading_mismatches": [],
        "unexpected_question_paragraphs": [],
        "missing_answers": [],
        "missing_explanations": [],
    }

    for exam_index, (start, header_match) in enumerate(exam_starts):
        end = exam_starts[exam_index + 1][0] if exam_index + 1 < len(exam_starts) else len(paragraphs)
        items = paragraphs[start:end]

        year = int(header_match.group(1))
        paper_name = header_match.group(2)

        section_year = None
        for heading in year_headings:
            if heading["paragraph"] < start:
                section_year = heading["year"]
            else:
                break
        if section_year is not None and section_year != year:
            issues["year_heading_mismatches"].append(
                {
                    "section_year": section_year,
                    "exam_year": year,
                    "paper_name": paper_name,
                    "source_header": items[0],
                }
            )

        answer_index = next((i for i, text in enumerate(items) if text.startswith("【答案】")), None)
        explanation_index = next(
            (i for i, text in enumerate(items) if text.startswith(EXPLAIN_PREFIXES)), None
        )

        body_end = answer_index if answer_index is not None else len(items)
        body = items[1:body_end]
        first_question = next((i for i, text in enumerate(body) if QUESTION_RE.match(text)), len(body))
        passage_paragraphs = body[:first_question]
        question_region = body[first_question:]

        questions = []
        current = 0
        while current < len(question_region):
            question_match = QUESTION_RE.match(question_region[current])
            if not question_match:
                issues["unexpected_question_paragraphs"].append(
                    {"paper_name": paper_name, "year": year, "text": question_region[current]}
                )
                current += 1
                continue

            number = int(question_match.group(1))
            stem = normalize_inline(question_match.group(2))
            options = []
            cursor = current + 1
            while cursor < len(question_region):
                option_match = OPTION_RE.match(question_region[cursor])
                if not option_match:
                    break
                options.append(
                    {"label": option_match.group(1), "content": normalize_inline(option_match.group(2))}
                )
                cursor += 1

            questions.append(
                {
                    "number": number,
                    "order_index": len(questions) + 1,
                    "stem": stem,
                    "options": options,
                }
            )
            current = cursor

        answer_text = ""
        if answer_index is not None:
            answer_end = explanation_index if explanation_index is not None else len(items)
            answer_text = "\n".join(items[answer_index:answer_end])
            answer_text = re.sub(r"^【答案】\s*", "", answer_text)

        explanation_text = ""
        if explanation_index is not None:
            explanation_text = "\n".join(items[explanation_index:])
            explanation_text = re.sub(r"^【(?:解析|分析)】\s*", "", explanation_text)

        numbers = [question["number"] for question in questions]
        answer_map = split_by_question_numbers(answer_text, numbers) if answer_text else {}
        explanation_map = split_by_question_numbers(explanation_text, numbers) if explanation_text else {}

        for question in questions:
            number = question["number"]
            answer = strip_question_number(answer_map.get(number, ""), number).strip()
            explanation = strip_question_number(explanation_map.get(number, ""), number).strip()

            if not answer:
                issues["missing_answers"].append({"year": year, "paper_name": paper_name, "number": number})
            if not explanation:
                issues["missing_explanations"].append(
                    {"year": year, "paper_name": paper_name, "number": number}
                )

            question["answer"] = answer
            question["explanation"] = explanation
            question["question_type"] = "single_choice" if question["options"] else "subjective"

            if question["options"]:
                match = re.match(r"^\s*([A-D]+)", answer)
                correct = match.group(1) if match else None
                if correct is None:
                    issues["missing_answers"].append(
                        {"year": year, "paper_name": paper_name, "number": number, "reason": "选项答案无法识别"}
                    )
                question["correct_answer"] = correct
                correct_letters = set(correct or "")
                for option in question["options"]:
                    option["is_correct"] = option["label"] in correct_letters
                question["answer_points"] = []
            else:
                question["correct_answer"] = answer
                question["answer_points"] = split_answer_points(answer)

        title, author, passage_body = extract_title_author(passage_paragraphs)
        question_count = len(questions)
        exams.append(
            {
                "source_index": exam_index + 1,
                "year": year,
                "paper_name": paper_name,
                "source_header": items[0],
                "passage": {
                    "order_index": 1,
                    "title": title,
                    "author": author,
                    "paragraphs": passage_body,
                    "content": "\n\n".join(passage_body),
                },
                "questions": questions,
                "question_count": question_count,
            }
        )

    return exams, {"media": media, "year_headings": year_headings, "issues": issues}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def cross_check(left, right) -> list[dict]:
    """比对解析版和原卷版的题干、选项、正文，确保两份文件一致。"""
    mismatches = []
    if len(left) != len(right):
        mismatches.append({"field": "exam_count", "left": len(left), "right": len(right)})

    for exam_index, (a, b) in enumerate(zip(left, right), start=1):
        if a["year"] != b["year"] or a["paper_name"] != b["paper_name"]:
            mismatches.append(
                {
                    "exam": exam_index,
                    "field": "exam_header",
                    "left": f"{a['year']} {a['paper_name']}",
                    "right": f"{b['year']} {b['paper_name']}",
                }
            )

        a_paragraphs = a["passage"]["paragraphs"]
        b_paragraphs = b["passage"]["paragraphs"]
        if len(a_paragraphs) != len(b_paragraphs):
            mismatches.append(
                {
                    "exam": exam_index,
                    "field": "passage_paragraph_count",
                    "left": len(a_paragraphs),
                    "right": len(b_paragraphs),
                }
            )
        else:
            for paragraph_index, (left_text, right_text) in enumerate(
                zip(a_paragraphs, b_paragraphs), start=1
            ):
                if normalize_text(left_text) != normalize_text(right_text):
                    mismatches.append(
                        {
                            "exam": exam_index,
                            "field": f"passage_paragraph_{paragraph_index}",
                            "left": normalize_text(left_text)[:80],
                            "right": normalize_text(right_text)[:80],
                        }
                    )

        if len(a["questions"]) != len(b["questions"]):
            mismatches.append(
                {
                    "exam": exam_index,
                    "field": "question_count",
                    "left": len(a["questions"]),
                    "right": len(b["questions"]),
                }
            )
            continue

        for qa, qb in zip(a["questions"], b["questions"]):
            if qa["number"] != qb["number"]:
                mismatches.append(
                    {
                        "exam": exam_index,
                        "field": "question_number",
                        "left": qa["number"],
                        "right": qb["number"],
                    }
                )
            if normalize_text(qa["stem"]) != normalize_text(qb["stem"]):
                mismatches.append(
                    {
                        "exam": exam_index,
                        "field": f"question_{qa['number']}_stem",
                        "left": normalize_text(qa["stem"])[:80],
                        "right": normalize_text(qb["stem"])[:80],
                    }
                )
            if len(qa["options"]) != len(qb["options"]):
                mismatches.append(
                    {
                        "exam": exam_index,
                        "field": f"question_{qa['number']}_option_count",
                        "left": len(qa["options"]),
                        "right": len(qb["options"]),
                    }
                )
                continue
            for oa, ob in zip(qa["options"], qb["options"]):
                if oa["label"] != ob["label"] or normalize_text(oa["content"]) != normalize_text(ob["content"]):
                    mismatches.append(
                        {
                            "exam": exam_index,
                            "field": f"question_{qa['number']}_option_{oa['label']}",
                            "left": normalize_text(oa["content"])[:80],
                            "right": normalize_text(ob["content"])[:80],
                        }
                    )

    return mismatches


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_json(value) -> str:
    return sql_literal(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def build_exam_codes(exams) -> None:
    bases = [f"{exam['year']}-{exam['paper_name']}" for exam in exams]
    counts = Counter(bases)
    seen = Counter()
    for exam, base in zip(exams, bases):
        seen[base] += 1
        exam["exam_code"] = base if counts[base] == 1 else f"{base}-{seen[base]}"


def generate_sql(exams, details: dict, source_file: str, reset: bool) -> str:
    lines = [
        "-- 由 scripts/import_dataset.py 生成，请勿手工修改。",
        f"-- 生成时间：{datetime.now(UTC).isoformat()}",
        "BEGIN;",
        "SET client_encoding = 'UTF8';",
        "SET standard_conforming_strings = on;",
    ]

    if reset:
        lines.append("TRUNCATE TABLE import_runs, questions, passages, exams RESTART IDENTITY CASCADE;")

    for exam in exams:
        exam_code = exam["exam_code"]
        lines.append(f"\n-- {exam_code}")
        lines.append(
            "INSERT INTO exams "
            "(source_index, exam_code, year, paper_name, subject, category, compilation, source_file, source_header)\n"
            f"VALUES ({exam['source_index']}, {sql_literal(exam_code)}, {exam['year']}, "
            f"{sql_literal(exam['paper_name'])}, {sql_literal(SUBJECT)}, {sql_literal(CATEGORY)}, "
            f"{sql_literal(COMPILATION)}, {sql_literal(source_file)}, {sql_literal(exam['source_header'])})\n"
            "ON CONFLICT (source_index) DO UPDATE SET\n"
            "    exam_code = EXCLUDED.exam_code,\n"
            "    year = EXCLUDED.year,\n"
            "    paper_name = EXCLUDED.paper_name,\n"
            "    subject = EXCLUDED.subject,\n"
            "    category = EXCLUDED.category,\n"
            "    compilation = EXCLUDED.compilation,\n"
            "    source_file = EXCLUDED.source_file,\n"
            "    source_header = EXCLUDED.source_header,\n"
            "    updated_at = now();"
        )

        passage = exam["passage"]
        lines.append(
            "INSERT INTO passages (exam_id, order_index, title, author, content, paragraphs)\n"
            f"SELECT e.id, {passage['order_index']}, {sql_literal(passage['title'])}, "
            f"{sql_literal(passage['author'])}, {sql_literal(passage['content'])}, "
            f"{sql_json(passage['paragraphs'])}\n"
            f"FROM exams e WHERE e.source_index = {exam['source_index']}\n"
            "ON CONFLICT (exam_id, order_index) DO UPDATE SET\n"
            "    title = EXCLUDED.title,\n"
            "    author = EXCLUDED.author,\n"
            "    content = EXCLUDED.content,\n"
            "    paragraphs = EXCLUDED.paragraphs,\n"
            "    updated_at = now();"
        )

        value_rows = []
        for question in exam["questions"]:
            explanation = (
                sql_literal(question["explanation"])
                if question["explanation"]
                else "NULL::text"
            )
            value_rows.append(
                "("
                f"{question['number']}, {question['order_index']}, {sql_literal(question['stem'])}, "
                f"{sql_literal(question['question_type'])}, {sql_json(question['options'])}, "
                f"{sql_literal(question['correct_answer'])}, {sql_json(question['answer_points'])}, "
                f"{explanation}, NULL::numeric(4,1)"
                ")"
            )

        lines.append(
            "INSERT INTO questions "
            "(exam_id, passage_id, question_number, order_index, stem, question_type, options, "
            "correct_answer, answer_points, explanation, max_score)\n"
            "SELECT e.id, p.id, v.question_number, v.order_index, v.stem, v.question_type, v.options, "
            "v.correct_answer, v.answer_points, v.explanation, v.max_score\n"
            "FROM exams e\n"
            "JOIN passages p ON p.exam_id = e.id AND p.order_index = 1\n"
            "CROSS JOIN (VALUES\n    "
            + ",\n    ".join(value_rows)
            + "\n) AS v(question_number, order_index, stem, question_type, options, correct_answer, "
            "answer_points, explanation, max_score)\n"
            f"WHERE e.source_index = {exam['source_index']}\n"
            "ON CONFLICT (exam_id, question_number) DO UPDATE SET\n"
            "    passage_id = EXCLUDED.passage_id,\n"
            "    order_index = EXCLUDED.order_index,\n"
            "    stem = EXCLUDED.stem,\n"
            "    question_type = EXCLUDED.question_type,\n"
            "    options = EXCLUDED.options,\n"
            "    correct_answer = EXCLUDED.correct_answer,\n"
            "    answer_points = EXCLUDED.answer_points,\n"
            "    explanation = EXCLUDED.explanation,\n"
            "    max_score = EXCLUDED.max_score,\n"
            "    updated_at = now();"
        )

    question_count = sum(len(exam["questions"]) for exam in exams)
    status = "ok"
    if (
        details["cross_check_mismatch_count"] > 0
        or details["missing_answers"]
        or details["missing_explanations"]
    ):
        status = "warning"

    lines.append(
        "\nINSERT INTO import_runs (source_file, exam_count, question_count, status, details)\n"
        f"VALUES ({sql_literal(source_file)}, {len(exams)}, {question_count}, {sql_literal(status)}, "
        f"{sql_json(details)});"
    )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def apply_sql(path: Path, container: str, database: str, user: str) -> None:
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
    ]
    result = subprocess.run(
        command,
        check=False,
        input=path.read_bytes(),
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(f"导入失败：{path}")
    output = result.stdout.decode("utf-8", errors="replace").strip()
    if output:
        print(output)


def verify(container: str, database: str, user: str) -> None:
    query = """
    SELECT json_build_object(
        'exams', (SELECT count(*) FROM exams),
        'passages', (SELECT count(*) FROM passages),
        'questions', (SELECT count(*) FROM questions),
        'single_choice', (SELECT count(*) FROM questions WHERE question_type = 'single_choice'),
        'subjective', (SELECT count(*) FROM questions WHERE question_type = 'subjective'),
        'without_correct_answer', (
            SELECT count(*) FROM questions
            WHERE correct_answer IS NULL OR btrim(correct_answer) = ''
        ),
        'without_explanation', (
            SELECT count(*) FROM questions
            WHERE explanation IS NULL OR btrim(explanation) = ''
        ),
        'with_answer_points', (
            SELECT count(*) FROM questions WHERE jsonb_array_length(answer_points) > 0
        )
    );
    """
    command = ["docker", "exec", container, "psql", "-U", user, "-d", database, "-At", "-c", query]
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        raise SystemExit("核对查询失败")
    print(result.stdout.decode("utf-8", errors="replace").strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="把高考真题 docx 导入 PostgreSQL 题库")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "db" / "import_dataset.sql")
    parser.add_argument("--apply", action="store_true", help="生成后通过 Docker 执行 schema 和导入 SQL")
    parser.add_argument("--reset", action="store_true", help="导入前清空题库表")
    parser.add_argument("--container", default=os.environ.get("PG_CONTAINER", "agent_test-postgres"))
    parser.add_argument("--database", default=os.environ.get("PG_DATABASE", "Mark"))
    parser.add_argument("--user", default=os.environ.get("PG_USER", "postgres"))
    args = parser.parse_args()

    docx_files = sorted(args.data_dir.glob("*.docx"))
    parse_path = next((path for path in docx_files if "解析版" in path.name), None)
    original_path = next((path for path in docx_files if "原卷版" in path.name), None)
    if parse_path is None:
        raise SystemExit(f"没有在 {args.data_dir} 找到解析版 docx")
    if original_path is None:
        raise SystemExit(f"没有在 {args.data_dir} 找到原卷版 docx")

    exams, meta = parse_docx(parse_path)
    original_exams, _ = parse_docx(original_path)
    cross_mismatches = cross_check(exams, original_exams)
    build_exam_codes(exams)

    source_file = parse_path.relative_to(ROOT).as_posix()
    original_file = original_path.relative_to(ROOT).as_posix()

    duplicate_papers = [
        {"year": year, "paper_name": paper_name, "count": count}
        for (year, paper_name), count in Counter(
            (exam["year"], exam["paper_name"]) for exam in exams
        ).items()
        if count > 1
    ]

    all_questions = [question for exam in exams for question in exam["questions"]]
    type_counts = Counter(question["question_type"] for question in all_questions)
    subjective_with_points = sum(
        1
        for question in all_questions
        if question["question_type"] == "subjective" and len(question["answer_points"]) > 1
    )

    details = {
        "compilation": COMPILATION,
        "parsed_from": source_file,
        "cross_checked_with": original_file,
        "cross_check_mismatch_count": len(cross_mismatches),
        "cross_check_mismatches": cross_mismatches[:20],
        "year_headings": meta["year_headings"],
        "year_heading_mismatches": meta["issues"]["year_heading_mismatches"],
        "duplicate_papers": duplicate_papers,
        "question_type_counts": dict(type_counts),
        "missing_answers": meta["issues"]["missing_answers"],
        "missing_explanations": meta["issues"]["missing_explanations"],
        "unexpected_question_paragraphs": meta["issues"]["unexpected_question_paragraphs"],
        "subjective_with_multiple_points": subjective_with_points,
        "media_files": meta["media"],
        "notes": [
            "max_score 留空：原始数据没有逐题分值。",
            "answer_points 是按圈号、(1)、优点/缺点、分号切出的初稿，不是官方评分细则。",
            "2019 北京卷第 50 题的示例答案按单条保留，没有继续切分。",
            "2019 江苏卷包含两篇不同文本，按两个试卷组保存。",
            "文末的 2023 年标题标记与实际试卷年份不一致，年份以试卷组标题为准。",
        ],
    }

    sql = generate_sql(exams, details, source_file, args.reset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql, encoding="utf-8", newline="\n")

    print(f"解析版：{source_file}")
    print(f"原卷版：{original_file}")
    print(f"试卷组：{len(exams)}")
    print(f"题目：{len(all_questions)}（单选 {type_counts.get('single_choice', 0)}，主观 {type_counts.get('subjective', 0)}）")
    print(f"答案缺失：{len(details['missing_answers'])}")
    print(f"解析缺失：{len(details['missing_explanations'])}")
    print(f"两版交叉校验差异：{len(cross_mismatches)}")
    print(f"生成 SQL：{args.output}")

    if args.apply:
        apply_sql(ROOT / "db" / "schema.sql", args.container, args.database, args.user)
        apply_sql(args.output, args.container, args.database, args.user)
        print("入库完成，核对结果：")
        verify(args.container, args.database, args.user)


if __name__ == "__main__":
    main()
