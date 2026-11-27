import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GradingResult, GradingRun, Question, Student, Submission
from app.schemas.grading import ReportNarrative
from app.services.llm import LLMProtocol

STUDENT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "student_report.md"
CLASS_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "class_report.md"


def _bullets(items: list[str]) -> str:
    if not items:
        return "- 暂无"
    return "\n".join(f"- {item}" for item in items)


def _narrative_markdown(narrative: ReportNarrative) -> str:
    return (
        f"## 总体\n{narrative.summary}\n\n"
        f"## 薄弱点\n{_bullets(narrative.weaknesses)}\n\n"
        f"## 建议\n{_bullets(narrative.suggestions)}"
    )


async def build_class_aggregate(
    session: AsyncSession,
    class_id: int,
    exam_id: int,
) -> dict:
    submissions = (
        await session.execute(
            select(Submission)
            .join(Student, Student.id == Submission.student_id)
            .where(
                Submission.exam_id == exam_id,
                Student.class_id == class_id,
            )
        )
    ).scalars().all()

    submission_count = 0
    score_sum = 0.0
    max_score = 0.0
    score_distribution = {
        "0-59": 0,
        "60-69": 0,
        "70-79": 0,
        "80-89": 0,
        "90-100": 0,
    }
    per_question: dict[int, dict] = {}
    error_type_counts: Counter[str] = Counter()
    knowledge_point_counts: Counter[str] = Counter()

    for submission in submissions:
        run = (
            await session.execute(
                select(GradingRun)
                .where(
                    GradingRun.submission_id == submission.id,
                    GradingRun.status == "completed",
                )
                .order_by(GradingRun.created_at.desc(), GradingRun.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if run is None:
            continue

        rows = (
            await session.execute(
                select(GradingResult, Question)
                .join(Question, Question.id == GradingResult.question_id)
                .where(GradingResult.run_id == run.id)
            )
        ).all()
        total = 0.0
        total_max = 0.0
        for result, question in rows:
            final_score = float(
                result.final_score
                if result.final_score is not None
                else result.ai_score
            )
            max_score_value = float(result.max_score)
            total += final_score
            total_max += max_score_value

            entry = per_question.setdefault(
                question.question_number,
                {"question_number": question.question_number, "score": 0.0, "max": 0.0},
            )
            entry["score"] += final_score
            entry["max"] += max_score_value

            if result.error_type:
                error_type_counts[result.error_type] += 1
            for point in result.knowledge_points or []:
                knowledge_point_counts[point] += 1

        submission_count += 1
        score_sum += total
        max_score = max(max_score, total_max)
        percentage = (total / total_max * 100) if total_max else 0
        for band, (low, high) in {
            "0-59": (0, 60),
            "60-69": (60, 70),
            "70-79": (70, 80),
            "80-89": (80, 90),
            "90-100": (90, 101),
        }.items():
            if low <= percentage < high:
                score_distribution[band] += 1
                break

    weak_points = [name for name, _ in knowledge_point_counts.most_common(5)]
    return {
        "class_id": class_id,
        "exam_id": exam_id,
        "submission_count": submission_count,
        "average_score": round(score_sum / submission_count, 2) if submission_count else 0.0,
        "max_score": max_score,
        "score_distribution": score_distribution,
        "per_question": [
            {
                "question_number": item["question_number"],
                "average_score_rate": round(item["score"] / item["max"], 3)
                if item["max"]
                else 0.0,
            }
            for item in sorted(
                per_question.values(),
                key=lambda item: item["question_number"],
            )
        ],
        "error_type_counts": dict(error_type_counts),
        "knowledge_point_counts": dict(knowledge_point_counts),
        "weak_points": weak_points,
    }


async def generate_student_report(
    llm: LLMProtocol,
    student_name: str,
    exam_code: str,
    results: list[dict],
    contexts: list[dict],
) -> dict:
    del contexts
    template = STUDENT_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        student_name=student_name,
        exam_code=exam_code,
        results=json.dumps(results, ensure_ascii=False),
    )
    response = await llm.complete_json(
        prompt,
        ReportNarrative,
        trace_name="student_report",
    )
    return {
        "content_markdown": _narrative_markdown(response.value),
        "data": {
            "student_name": student_name,
            "exam_code": exam_code,
            "results": results,
        },
    }


async def generate_class_report(
    llm: LLMProtocol,
    class_name: str,
    exam_code: str,
    aggregate: dict,
) -> dict:
    template = CLASS_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        class_name=class_name,
        exam_code=exam_code,
        aggregate=json.dumps(aggregate, ensure_ascii=False),
    )
    response = await llm.complete_json(
        prompt,
        ReportNarrative,
        trace_name="class_report",
    )
    markdown = (
        f"## 概况\n"
        f"- 提交人数：{aggregate['submission_count']}\n"
        f"- 平均分：{aggregate['average_score']:.1f} / {aggregate['max_score']:.1f}\n"
        f"- 薄弱知识点：{'、'.join(aggregate['weak_points']) or '暂无'}\n\n"
        + _narrative_markdown(response.value)
    )
    return {
        "content_markdown": markdown,
        "data": aggregate,
    }
