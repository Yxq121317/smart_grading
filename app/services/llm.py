import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.services.observability import trace_score


class LLMOutputError(Exception):
    def __init__(
        self,
        message: str,
        *,
        raw_text: str | None = None,
        errors: str | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.errors = errors


@dataclass
class LLMResult[T: BaseModel]:
    value: T
    repaired: bool


class LLMProtocol(Protocol):
    async def complete_json[S: BaseModel](
        self,
        prompt: str,
        schema: type[S],
        *,
        trace_name: str,
    ) -> LLMResult[S]: ...


class LLMClient:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        timeout: float = 60,
        max_retries: int = 2,
        concurrency: int = 5,
        completion_fn: Callable[[str], Awaitable[str]] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(concurrency)
        self._completion_fn = completion_fn or self._default_completion
        self._settings = settings

    async def _default_completion(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=self._timeout,
        )
        return response.choices[0].message.content or ""

    async def complete_json[S: BaseModel](
        self,
        prompt: str,
        schema: type[S],
        *,
        trace_name: str,
    ) -> LLMResult[S]:
        async with self._semaphore:
            repair_context = ""
            last_raw = ""
            last_errors = ""
            for attempt in range(self._max_retries + 1):
                full_prompt = prompt + "\n只输出 JSON，不要 markdown 代码块。"
                if repair_context:
                    full_prompt += f"\n上一次输出无法解析：\n{repair_context}"
                raw = await self._completion_fn(full_prompt)
                last_raw = raw
                try:
                    data = json.loads(extract_json(raw))
                    if self._settings is not None:
                        trace_score("json_valid", 1, self._settings)
                    return LLMResult(
                        value=schema.model_validate(data),
                        repaired=attempt > 0,
                    )
                except (json.JSONDecodeError, ValidationError) as exc:
                    last_errors = str(exc)
                    repair_context = f"原始输出：{raw}\n错误：{last_errors}"

            if self._settings is not None:
                trace_score("json_valid", 0, self._settings)
            raise LLMOutputError(
                f"LLM output for {trace_name} could not be parsed",
                raw_text=last_raw,
                errors=last_errors,
            )


def extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def build_openai_client(settings: Settings) -> AsyncOpenAI:
    if settings.langfuse_enabled:
        try:
            from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI

            return LangfuseAsyncOpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
            )
        except ImportError:
            pass
    return AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
