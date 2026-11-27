from app.services.llm import LLMResult


def make_question_context(
    sample_exam,
    index,
    *,
    student_answer="",
    selected_options=None,
):
    question = sample_exam["questions"][index]
    return {
        "question_id": question["id"],
        "question_number": question["number"],
        "exam_id": sample_exam["exam_id"],
        "question_type": question["type"],
        "stem": question["stem"],
        "passage": sample_exam["passage"]["content"],
        "options": question["options"],
        "correct_answer": question["correct_answer"],
        "answer_points": question["answer_points"],
        "explanation": question["explanation"],
        "max_score": question["max_score"],
        "student_answer": student_answer,
        "selected_options": selected_options or [],
        "rubric": None,
        "rubric_id": None,
        "rubric_fallback": False,
    }


class FakeLLMClient:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    async def complete_json(self, prompt, schema, *, trace_name):
        self.calls.append(trace_name)
        value = self.responses[trace_name]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        parsed = value if isinstance(value, schema) else schema.model_validate(value)
        return LLMResult(value=parsed, repaired=False)
