import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.services.llm import LLMClient, LLMOutputError


class Answer(BaseModel):
    number: int


class StubCompletion:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    async def __call__(self, prompt):
        self.calls += 1
        return self.outputs.pop(0)


async def test_complete_json_first_try():
    stub = StubCompletion(['{"number": 1}'])
    client = LLMClient(AsyncOpenAI(api_key="test"), "test", completion_fn=stub)
    result = await client.complete_json("x", Answer, trace_name="test")
    assert result.value.number == 1
    assert result.repaired is False
    assert stub.calls == 1


async def test_complete_json_retries():
    stub = StubCompletion(["not json", '{"number": 1}'])
    client = LLMClient(AsyncOpenAI(api_key="test"), "test", completion_fn=stub)
    result = await client.complete_json("x", Answer, trace_name="test")
    assert result.value.number == 1
    assert result.repaired is True
    assert stub.calls == 2


async def test_complete_json_raises():
    stub = StubCompletion(["not json", "still not json", "bad"])
    client = LLMClient(
        AsyncOpenAI(api_key="test"),
        "test",
        max_retries=2,
        completion_fn=stub,
    )
    with pytest.raises(LLMOutputError):
        await client.complete_json("x", Answer, trace_name="test")
