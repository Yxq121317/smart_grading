from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.repositories import get_submission_bundle, update_run_heartbeat
from app.graph.state import GradingState


def make_load_submission_node(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    async def node(state: GradingState) -> dict:
        async with session_factory() as session:
            bundle = await get_submission_bundle(session, state["submission_id"])
            if bundle is None:
                raise ValueError(f"submission {state['submission_id']} not found")
            await update_run_heartbeat(session, state["grading_run_id"])

        contexts = []
        for question in bundle["questions"]:
            answer = bundle["answers"].get(question["id"], {})
            max_score = question["max_score"]
            if max_score is None:
                max_score = (
                    settings.default_mcq_score
                    if question["type"] == "single_choice"
                    else settings.default_subjective_score
                )
            contexts.append(
                {
                    "question_id": question["id"],
                    "question_number": question["number"],
                    "exam_id": bundle["exam_id"],
                    "question_type": question["type"],
                    "stem": question["stem"],
                    "passage": bundle["passage"],
                    "options": question["options"] or [],
                    "correct_answer": question["correct_answer"],
                    "answer_points": question["answer_points"] or [],
                    "explanation": question["explanation"],
                    "max_score": float(max_score),
                    "student_answer": answer.get("answer_text") or "",
                    "selected_options": answer.get("selected_options") or [],
                    "rubric": None,
                    "rubric_id": None,
                    "rubric_fallback": False,
                }
            )

        return {
            "exam_id": bundle["exam_id"],
            "exam_code": bundle["exam_code"],
            "student_id": bundle["student_id"],
            "student_name": bundle["student_name"],
            "submission_id": bundle["submission_id"],
            "question_contexts": contexts,
        }

    return node
