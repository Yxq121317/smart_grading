from app.core.config import Settings
from app.services.llm import build_openai_client
from app.services.observability import trace_score, traceable


def test_traceable_is_noop_when_disabled():
    settings = Settings(_env_file=None, langfuse_enabled=False)

    def fn():
        return 1

    assert traceable("x", settings)(fn) is fn


def test_trace_score_is_noop_when_disabled():
    settings = Settings(_env_file=None, langfuse_enabled=False)
    assert trace_score("task_completed", 1, settings) is None


def test_build_openai_client_without_langfuse():
    settings = Settings(_env_file=None, langfuse_enabled=False, api_key="test")
    client = build_openai_client(settings)
    assert client.__class__.__module__.startswith("openai")
