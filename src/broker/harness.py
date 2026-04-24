"""Agent loop: Claude via Anthropic SDK, with Koala MCP tools and local tools.

Mirrors the reference repo's agent_definition/harness/harness.py pattern but
adds checkpointing, per-invocation session timeout, and trajectory logging.
"""

from __future__ import annotations

import asyncio
import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from broker.config import REPO_ROOT, load_api_key, settings
from broker.koala_client import KoalaClient
from broker.logging import log, record_trajectory, setup_logging
from broker.prompt import assemble_prompt, initial_user_message
from broker.tools import Dispatcher, all_tool_schemas


class AgentStopped(Exception):
    """Soft stop — used by signal handler and timeout guard."""


def _checkpoint_path(agent_name: str) -> Path:
    return REPO_ROOT / "data" / f"checkpoint-{agent_name}.json"


def _save_checkpoint(agent_name: str, messages: list[dict[str, Any]]) -> None:
    path = _checkpoint_path(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Anthropic SDK returns content blocks as pydantic models; coerce to dict.
    serializable = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = [c.model_dump() if hasattr(c, "model_dump") else c for c in content]
        serializable.append({"role": m["role"], "content": content})
    path.write_text(json.dumps(serializable))


def _load_checkpoint(agent_name: str) -> list[dict[str, Any]] | None:
    path = _checkpoint_path(agent_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        log.warning("checkpoint_corrupt", path=str(path))
        return None


def _trim_history(messages: list[dict[str, Any]], max_messages: int = 80) -> list[dict[str, Any]]:
    """Keep the conversation bounded. Drop oldest tool_result cycles but preserve
    enough recent context for the LLM to remain coherent. Simple heuristic —
    revisit if we hit real issues."""
    if len(messages) <= max_messages:
        return messages
    # Always keep the very first message (kickoff) if present, then a tail window.
    head = messages[:1]
    tail = messages[-(max_messages - 1):]
    return head + tail


async def run_once(*, session_timeout_s: int | None = None) -> int:
    """One agent-session invocation. Returns number of turns executed.

    The supervisor script re-invokes us indefinitely. Each session has its
    own timeout and shares the same persisted checkpoint.
    """
    setup_logging()

    agent_name = settings.agent_name
    api_key = load_api_key(agent_name)
    settings.koala_api_key = api_key  # so KoalaClient picks it up

    timeout_s = session_timeout_s or settings.session_timeout_s
    started_at = time.monotonic()
    stop_flag = {"stop": False}

    def _handle_sigterm(*_: Any) -> None:
        stop_flag["stop"] = True

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required")

    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    koala = KoalaClient(api_key=api_key)
    dispatcher = Dispatcher(koala=koala)

    system_prompt = assemble_prompt(agent_name)
    tools = all_tool_schemas()

    messages = _load_checkpoint(agent_name)
    resumed = messages is not None
    if not messages:
        messages = [{"role": "user", "content": initial_user_message(agent_name)}]

    await record_trajectory(
        "agent_boot",
        agent_id=agent_name,
        payload={
            "resumed": resumed,
            "timeout_s": timeout_s,
            "model": settings.frontier_model,
            "message_count": len(messages),
        },
    )

    turns = 0
    total_in_tokens = 0
    total_out_tokens = 0

    try:
        while turns < settings.max_turns:
            if stop_flag["stop"]:
                log.info("shutdown_signal")
                break
            if time.monotonic() - started_at > timeout_s:
                log.info("session_timeout_reached")
                break

            try:
                resp = await anthropic.messages.create(
                    model=settings.frontier_model,
                    system=system_prompt,
                    tools=tools,
                    messages=_trim_history(messages),
                    max_tokens=settings.max_tokens_per_turn,
                )
            except Exception as e:
                log.exception("messages_create_failed")
                await record_trajectory(
                    "llm_error", agent_id=agent_name, payload={"error": str(e)[:400]}
                )
                # Back off briefly and let the supervisor recycle if it recurs.
                await asyncio.sleep(10)
                raise

            turns += 1
            total_in_tokens += resp.usage.input_tokens
            total_out_tokens += resp.usage.output_tokens
            log.info(
                "turn",
                n=turns,
                stop_reason=resp.stop_reason,
                in_tok=resp.usage.input_tokens,
                out_tok=resp.usage.output_tokens,
                cum_in=total_in_tokens,
                cum_out=total_out_tokens,
            )

            assistant_content = list(resp.content)
            messages.append({"role": "assistant", "content": assistant_content})

            if resp.stop_reason == "tool_use":
                tool_results: list[dict[str, Any]] = []
                for block in assistant_content:
                    if getattr(block, "type", None) == "tool_use":
                        result = await dispatcher.dispatch(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                        await record_trajectory(
                            "tool_call",
                            agent_id=agent_name,
                            payload={
                                "tool": block.name,
                                "input_preview": json.dumps(block.input)[:500],
                                "result_preview": result[:500],
                            },
                        )
                messages.append({"role": "user", "content": tool_results})
            elif resp.stop_reason == "end_turn":
                # Agent produced text without a tool call — prompt it to continue.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue. Check notifications via get_unread_count, "
                            "then act on the next highest-value opportunity. "
                            "Remember: every comment requires github_file_url from "
                            "write_reasoning_and_commit."
                        ),
                    }
                )
            else:
                # max_tokens, stop_sequence, refusal, etc. — break and let supervisor recycle.
                log.warning("unexpected_stop", stop_reason=resp.stop_reason)
                break

            _save_checkpoint(agent_name, messages)
    finally:
        _save_checkpoint(agent_name, messages)
        await koala.close()
        await record_trajectory(
            "agent_exit",
            agent_id=agent_name,
            payload={
                "turns": turns,
                "in_tokens": total_in_tokens,
                "out_tokens": total_out_tokens,
                "elapsed_s": time.monotonic() - started_at,
            },
        )

    return turns
