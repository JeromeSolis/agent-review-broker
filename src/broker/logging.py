import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import structlog

from broker.config import settings
from broker.db import connect


def setup_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()


async def record_trajectory(
    event_type: str,
    *,
    agent_id: str | None = None,
    paper_id: str | None = None,
    payload: dict[str, Any] | None = None,
    db: aiosqlite.Connection | None = None,
) -> None:
    """Append a structured event to the trajectory log.

    Prize eligibility requires the full trajectory; every platform action funnels through here.
    """
    agent_id = agent_id or settings.agent_id or "unknown"
    payload = payload or {}
    ts = datetime.now(UTC).isoformat()

    log.info(event_type, agent_id=agent_id, paper_id=paper_id, **payload)

    async def _write(conn: aiosqlite.Connection) -> None:
        await conn.execute(
            "INSERT INTO trajectory (ts, agent_id, event_type, paper_id, payload_json) VALUES (?, ?, ?, ?, ?)",
            (ts, agent_id, event_type, paper_id, json.dumps(payload, default=str)),
        )
        await conn.commit()

    if db is not None:
        await _write(db)
    else:
        async with connect() as conn:
            await _write(conn)
