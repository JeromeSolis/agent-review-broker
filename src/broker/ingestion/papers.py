from datetime import timedelta

from broker.db import connect
from broker.logging import log, record_trajectory
from broker.models import Paper
from broker.platform.base import PlatformClient

# Each paper's 72h clock closes verdicts at released_at + PAPER_LIFECYCLE_H.
PAPER_LIFECYCLE_H = 72


def verdict_deadline(paper: Paper):
    return paper.released_at + timedelta(hours=PAPER_LIFECYCLE_H)


async def upsert_paper(paper: Paper) -> bool:
    """Persist a paper. Returns True if it was newly inserted."""
    deadline = verdict_deadline(paper).isoformat()
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT INTO papers (paper_id, title, abstract, pdf_url, github_url, released_at, phase, verdict_deadline)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                title=excluded.title,
                abstract=excluded.abstract,
                pdf_url=excluded.pdf_url,
                github_url=excluded.github_url
            """,
            (
                paper.paper_id,
                paper.title,
                paper.abstract,
                paper.pdf_url,
                paper.github_url,
                paper.released_at.isoformat(),
                paper.phase.value,
                deadline,
            ),
        )
        await db.commit()
        return cur.rowcount > 0


async def ingest_papers(platform: PlatformClient) -> None:
    """Long-running task: consume the platform's paper stream, persist each new paper."""
    log.info("ingestion_start")
    async for paper in platform.stream_new_papers():
        try:
            is_new = await upsert_paper(paper)
            if is_new:
                await record_trajectory(
                    "paper_ingested",
                    paper_id=paper.paper_id,
                    payload={"title": paper.title, "has_repo": bool(paper.github_url)},
                )
        except Exception as e:
            log.error("paper_ingest_failed", paper_id=paper.paper_id, error=str(e))
