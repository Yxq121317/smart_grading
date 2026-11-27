from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import GradingResult, Rubric, Submission, TeacherCorrection
from app.graph.state import GradingState


def make_apply_corrections_node(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def node(state: GradingState) -> dict:
        corrections = state.get("corrections", [])
        results = [dict(result) for result in state.get("results", [])]
        results_by_question = {result["question_id"]: result for result in results}

        async with session_factory() as session:
            stored_results = (
                await session.execute(
                    select(GradingResult)
                    .where(GradingResult.run_id == state["grading_run_id"])
                    .with_for_update()
                )
            ).scalars().all()
            stored_by_id = {result.id: result for result in stored_results}

            for correction in corrections:
                stored = stored_by_id.get(correction["result_id"])
                if stored is None:
                    raise ValueError(
                        f"result {correction['result_id']} does not belong to run"
                    )
                if stored.reviewed:
                    continue

                old_rubric = None
                if stored.rubric_id is not None:
                    rubric = await session.get(Rubric, stored.rubric_id)
                    if rubric is not None:
                        old_rubric = {
                            "max_score": float(rubric.total_score),
                            "points": rubric.points,
                            "scoring_rules": "",
                        }

                new_rationale = correction.get("new_rationale")
                session.add(
                    TeacherCorrection(
                        result_id=stored.id,
                        instruction=correction.get("instruction") or "",
                        old_score=stored.ai_score,
                        new_score=correction["final_score"],
                        old_rationale=stored.rationale,
                        new_rationale=new_rationale,
                        old_rubric=old_rubric,
                        new_rubric=old_rubric,
                    )
                )
                stored.final_score = correction["final_score"]
                stored.reviewed = True
                if new_rationale:
                    stored.rationale = new_rationale

                result = results_by_question.get(stored.question_id)
                if result is not None:
                    result["final_score"] = correction["final_score"]
                    result["reviewed"] = True
                    if new_rationale:
                        result["rationale"] = new_rationale

            submission = await session.get(Submission, state["submission_id"])
            if submission is not None:
                submission.total_score = sum(
                    float(
                        result.final_score
                        if result.final_score is not None
                        else result.ai_score
                    )
                    for result in stored_results
                )
                submission.max_score = sum(
                    float(result.max_score) for result in stored_results
                )
            await session.commit()

        return {"review_items": [], "corrected_results": results}

    return node
