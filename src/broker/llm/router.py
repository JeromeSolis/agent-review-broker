from enum import StrEnum
from typing import TypedDict

from broker.config import LLMMode, settings
from broker.llm import frontier, local
from broker.logging import log


class TaskClass(StrEnum):
    BULK_ANALYSIS = "bulk_analysis"  # paper triage, bulk reading — local preferred
    COMMENT_GEN = "comment_gen"  # thread opens, bids — either
    CRITICAL = "critical"  # broker posterior, citation selection — frontier preferred


class Message(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


def _route(task: TaskClass) -> str:
    """Decide local vs frontier for a given task.

    Kill switch always wins. In auto mode, critical tasks go frontier, rest goes local.
    """
    if settings.llm_kill_switch_to_local:
        return "local"
    if settings.llm_mode == LLMMode.LOCAL:
        return "local"
    if settings.llm_mode == LLMMode.FRONTIER:
        return "frontier"
    # AUTO
    if task == TaskClass.CRITICAL:
        return "frontier"
    return "local"


async def complete(
    messages: list[Message],
    *,
    task: TaskClass,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    backend = _route(task)
    log.debug("llm_route", task=task, backend=backend, kill_switch=settings.llm_kill_switch_to_local)

    try:
        if backend == "frontier":
            return await frontier.complete(
                messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode
            )
        return await local.complete(
            messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode
        )
    except Exception as e:
        # Frontier failures fall back to local — never the other way (local is the safety net).
        if backend == "frontier" and not settings.llm_kill_switch_to_local:
            log.warning("frontier_failed_fallback_local", error=str(e))
            return await local.complete(
                messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode
            )
        raise
