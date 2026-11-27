from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalibrationLog, Exam, Passage, Question
from app.db.repositories import (
    get_active_rubric,
    list_submission_ids_for_exam,
    save_rubric,
)
from app.graph.subgraphs.rubric import build_rubric_subgraph
from app.schemas.grading import RubricOutput
from app.services.llm import LLMProtocol


class CalibrationError(Exception):
    pass


async def calibrate(
    session: AsyncSession,
    llm: LLMProtocol,
    exam_id: int,
    question_id: int,
    instruction: str,
    re_grade_all: bool = False,
) -> dict:
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise ValueError("exam not found")
    question = await session.get(Question, question_id)
    if question is None or question.exam_id != exam_id:
        raise ValueError("question not found in exam")

    passage = (
        await session.execute(
            select(Passage)
            .where(Passage.exam_id == exam_id)
            .order_by(Passage.order_index)
        )
    ).scalars().first()
    old_rubric = await get_active_rubric(session, question_id)
    max_score = (
        float(question.max_score) if question.max_score is not None else 6.0
    )
    context = {
        "question_id": question.id,
        "question_number": question.question_number,
        "exam_id": exam.id,
        "question_type": question.question_type,
        "stem": question.stem,
        "passage": passage.content if passage is not None else "",
        "options": question.options or [],
        "correct_answer": question.correct_answer,
        "answer_points": question.answer_points or [],
        "explanation": question.explanation,
        "max_score": max_score,
        "student_answer": "",
        "selected_options": [],
        "rubric": None,
        "rubric_id": old_rubric.id if old_rubric is not None else None,
        "rubric_fallback": False,
    }

    graph = build_rubric_subgraph(llm, allow_fallback=False)
    result = await graph.ainvoke(
        {"context": context, "instruction": instruction}
    )
    rubric_data = result.get("rubric")
    if result.get("rubric_fallback") or not rubric_data:
        raise CalibrationError("rubric calibration failed")
    output = RubricOutput.model_validate(rubric_data)

    new_rubric = await save_rubric(
        session,
        question_id,
        [point.model_dump() for point in output.points],
        output.max_score,
        source="teacher",
        instruction=instruction,
    )
    session.add(
        CalibrationLog(
            exam_id=exam_id,
            question_id=question_id,
            instruction=instruction,
            old_rubric_id=old_rubric.id if old_rubric is not None else None,
            new_rubric_id=new_rubric.id,
        )
    )
    await session.commit()

    submission_ids = (
        await list_submission_ids_for_exam(session, exam_id)
        if re_grade_all
        else []
    )
    return {
        "rubric_id": new_rubric.id,
        "version": new_rubric.version,
        "points": new_rubric.points,
        "total_score": float(new_rubric.total_score),
        "rerun_submission_ids": submission_ids,
    }
