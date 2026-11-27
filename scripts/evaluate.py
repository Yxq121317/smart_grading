import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.db.models import Passage, Question
from app.db.session import create_engine_and_factory
from app.graph.subgraphs.grade_question import build_question_subgraph
from app.services.llm import LLMClient, build_openai_client

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "golden_grading.jsonl"


def compute_metrics(cases: list[dict], predictions: list[dict]) -> dict:
    if not cases:
        return {
            "mae": 0.0,
            "exact_match_rate": 0.0,
            "json_valid_rate": 0.0,
            "error_accuracy": 0.0,
            "avg_confidence": 0.0,
            "review_rate": 0.0,
        }
    count = min(len(cases), len(predictions))
    pairs = list(zip(cases[:count], predictions[:count]))
    mae = sum(
        abs(float(prediction["score"]) - float(case["expected_score"]))
        for case, prediction in pairs
    ) / count
    exact = sum(
        1
        for case, prediction in pairs
        if float(prediction["score"]) == float(case["expected_score"])
    ) / count
    json_valid = sum(
        1 for prediction in predictions[:count] if prediction.get("json_valid")
    ) / count
    error_accuracy = sum(
        1
        for case, prediction in pairs
        if prediction.get("error_type") == case.get("expected_error_type")
    ) / count
    avg_confidence = sum(
        float(prediction.get("confidence", 0)) for prediction in predictions[:count]
    ) / count
    review_rate = sum(
        1 for prediction in predictions[:count] if prediction.get("needs_review")
    ) / count
    return {
        "mae": mae,
        "exact_match_rate": exact,
        "json_valid_rate": json_valid,
        "error_accuracy": error_accuracy,
        "avg_confidence": avg_confidence,
        "review_rate": review_rate,
    }


def _load_cases(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fake_predictions(cases: list[dict]) -> list[dict]:
    return [
        {
            "score": case["expected_score"],
            "error_type": case.get("expected_error_type"),
            "json_valid": True,
            "confidence": 0.9,
            "needs_review": False,
        }
        for case in cases
    ]


async def _live_predictions(cases: list[dict], settings: Settings) -> list[dict]:
    engine, factory = create_engine_and_factory(settings.mark_database_url)
    llm = LLMClient(
        build_openai_client(settings),
        settings.model_name,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        concurrency=settings.grading_concurrency,
        settings=settings,
    )
    graph = build_question_subgraph(llm, settings)
    predictions: list[dict] = []
    try:
        async with factory() as session:
            for case in cases:
                question = await session.get(Question, case["question_id"])
                if question is None:
                    raise ValueError(f"question {case['question_id']} not found")
                passage = (
                    await session.execute(
                        select(Passage)
                        .where(Passage.exam_id == question.exam_id)
                        .order_by(Passage.order_index)
                    )
                ).scalars().first()
                max_score = (
                    float(question.max_score)
                    if question.max_score is not None
                    else (
                        settings.default_mcq_score
                        if question.question_type == "single_choice"
                        else settings.default_subjective_score
                    )
                )
                context = {
                    "question_id": question.id,
                    "question_number": question.question_number,
                    "exam_id": question.exam_id,
                    "question_type": question.question_type,
                    "stem": question.stem,
                    "passage": passage.content if passage is not None else "",
                    "options": question.options or [],
                    "correct_answer": question.correct_answer,
                    "answer_points": question.answer_points or [],
                    "explanation": question.explanation,
                    "max_score": max_score,
                    "student_answer": case.get("student_answer", ""),
                    "selected_options": case.get("selected_options", []),
                    "rubric": None,
                    "rubric_id": None,
                    "rubric_fallback": False,
                }
                result = (await graph.ainvoke({"context": context}))["result"]
                predictions.append(
                    {
                        "score": result["final_score"]
                        if result["final_score"] is not None
                        else result["ai_score"],
                        "error_type": result["error_type"],
                        "json_valid": result["rationale"]
                        != "评分输出无法解析",
                        "confidence": result["confidence"],
                        "needs_review": result["needs_review"],
                    }
                )
    finally:
        await engine.dispose()
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate grading quality")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--fake", action="store_true", help="Use expected scores")
    args = parser.parse_args()

    cases = _load_cases(args.fixture)
    if args.fake:
        predictions = _fake_predictions(cases)
    else:
        predictions = asyncio.run(_live_predictions(cases, Settings()))
    print(json.dumps(compute_metrics(cases, predictions), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
