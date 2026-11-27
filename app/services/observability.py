import logging
from collections.abc import Callable
from typing import TypeVar

from app.core.config import Settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


def traceable(name: str, settings: Settings) -> Callable[[F], F]:
    if not settings.langfuse_enabled:
        return lambda fn: fn
    try:
        from langfuse import observe
    except ImportError:
        return lambda fn: fn
    return observe(name=name)


def trace_score(
    name: str,
    value: float | str,
    settings: Settings,
) -> None:
    if not settings.langfuse_enabled:
        return
    try:
        from langfuse import get_client

        get_client().score_current_trace(name=name, value=value)
    except Exception:
        logger.debug("failed to write Langfuse score %s", name, exc_info=True)
