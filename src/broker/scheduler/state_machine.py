import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from broker.db import connect
from broker.ingestion.papers import PAPER_LIFECYCLE_H
from broker.logging import log
from broker.models import Paper, PaperPhase
from broker.platform.base import PlatformClient

if TYPE_CHECKING:
    from broker.agents.base import Agent

DISCUSSION_PHASE_H = 48
SCHEDULER_TICK_S = 30
VERDICT_SAFETY_MARGIN_MIN = 15  # submit verdict at least this long before deadline


@dataclass
class PaperTask:
    paper: Paper
    phase: PaperPhase
    hours_elapsed: float
    hours_remaining: float


def time_into_lifecycle(released_at: datetime, now: datetime | None = None) -> timedelta:
    now = now or datetime.now(UTC)
    if released_at.tzinfo is None:
        released_at = released_at.replace(tzinfo=UTC)
    return now - released_at


def current_phase(released_at: datetime, now: datetime | None = None) -> PaperPhase:
    elapsed = time_into_lifecycle(released_at, now).total_seconds() / 3600
    if elapsed < DISCUSSION_PHASE_H:
        return PaperPhase.DISCUSSION
    if elapsed < PAPER_LIFECYCLE_H:
        return PaperPhase.VERDICT
    return PaperPhase.PUBLISHED


async def _fetch_active_papers() -> list[Paper]:
    """All papers whose 72h clock hasn't closed yet."""
    async with connect() as db:
        cur = await db.execute(
            """
            SELECT paper_id, title, abstract, pdf_url, github_url, released_at, phase
            FROM papers
            WHERE phase != 'published'
            """
        )
        rows = await cur.fetchall()

    papers: list[Paper] = []
    for row in rows:
        papers.append(
            Paper(
                paper_id=row["paper_id"],
                title=row["title"],
                abstract=row["abstract"],
                pdf_url=row["pdf_url"],
                github_url=row["github_url"],
                released_at=datetime.fromisoformat(row["released_at"]),
                phase=PaperPhase(row["phase"]),
            )
        )
    return papers


async def _sync_phase_transitions(papers: list[Paper]) -> None:
    """Keep the stored phase aligned with wall clock."""
    async with connect() as db:
        for p in papers:
            live_phase = current_phase(p.released_at)
            if live_phase != p.phase:
                await db.execute(
                    "UPDATE papers SET phase=? WHERE paper_id=?",
                    (live_phase.value, p.paper_id),
                )
                log.info(
                    "phase_transition",
                    paper_id=p.paper_id,
                    from_phase=p.phase.value,
                    to_phase=live_phase.value,
                )
                p.phase = live_phase
        await db.commit()


async def _has_own_verdict(paper_id: str, agent_id: str) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM verdicts WHERE paper_id=? AND agent_id=? AND submitted_at IS NOT NULL",
            (paper_id, agent_id),
        )
        return await cur.fetchone() is not None


async def _tick(platform: PlatformClient, agent: "Agent") -> None:
    papers = await _fetch_active_papers()
    if not papers:
        return
    await _sync_phase_transitions(papers)

    for paper in papers:
        elapsed = time_into_lifecycle(paper.released_at)
        hours_elapsed = elapsed.total_seconds() / 3600
        hours_remaining = PAPER_LIFECYCLE_H - hours_elapsed

        task = PaperTask(
            paper=paper,
            phase=paper.phase,
            hours_elapsed=hours_elapsed,
            hours_remaining=hours_remaining,
        )

        try:
            if paper.phase == PaperPhase.DISCUSSION:
                await agent.on_discussion_tick(task, platform)
            elif paper.phase == PaperPhase.VERDICT:
                if await _has_own_verdict(paper.paper_id, agent.agent_id):
                    continue
                # Deadline guard: submit verdict now if we're close to the 72h wall.
                minutes_to_deadline = hours_remaining * 60
                urgent = minutes_to_deadline < VERDICT_SAFETY_MARGIN_MIN * 2
                await agent.on_verdict_tick(task, platform, urgent=urgent)
        except Exception as e:
            log.error(
                "agent_tick_failed",
                agent=agent.agent_id,
                paper_id=paper.paper_id,
                phase=paper.phase.value,
                error=str(e),
            )


async def run_scheduler(platform: PlatformClient, agent: "Agent", *, tick_s: float = SCHEDULER_TICK_S) -> None:
    log.info("scheduler_start", agent=agent.agent_id, tick_s=tick_s)
    while True:
        try:
            await _tick(platform, agent)
        except Exception as e:
            log.error("scheduler_tick_error", error=str(e))
        await asyncio.sleep(tick_s)
