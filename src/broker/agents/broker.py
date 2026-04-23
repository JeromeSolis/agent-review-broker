import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from broker.agents.base import Agent
from broker.config import settings
from broker.db import connect
from broker.ingestion.pdf import ParsedPaper, parse_pdf
from broker.llm import TaskClass, complete
from broker.logging import log, record_trajectory
from broker.market import score_paper, select_citations, update_posterior
from broker.market.scoring import _entropy, to_verdict_score
from broker.models import Bid, Comment, Verdict
from broker.platform.base import ModerationRejected, PlatformClient
from broker.scheduler.state_machine import PaperTask

# Triage threshold: only open a market thread if the prior is sufficiently uncertain.
# Binary entropy at p=0.27 is ~0.85; at p=0.5 is 1.0. Gate above ~0.9 => broker
# operates roughly in the p in [0.3, 0.7] band.
ENTROPY_TRIAGE_THRESHOLD = 0.9

OPENING_COMMENT_TEMPLATE = """I'm estimating this paper at P(accept) = {probability:.2f} ({reasoning}).

Open question for other reviewers: what's your estimate, and what's the single strongest
piece of evidence driving it? Specific references (section, figure, equation, benchmark) preferred.
"""

BID_EXTRACTION_SYSTEM = """Extract the probability-of-acceptance signal from a reviewer comment.

Respond with JSON: {
  "probability": <float 0-1, or null if no clear signal>,
  "confidence": <float 0-1>,
  "specificity": <float 0-1, how concrete and verifiable the reasoning is>,
  "reasoning_summary": "<one-sentence summary of their argument>"
}

Return null probability if the comment is off-topic, vague, or contains no actionable signal.
"""


class BrokerAgent(Agent):
    """Agent 1 — the bet.

    Lifecycle per paper:
    - Discussion phase: score the paper (prior). If entropy is high enough, open a
      structured thread inviting bids. Otherwise skip (no karma spent).
    - Verdict phase: gather comments, extract bids from other agents' replies, run a
      weighted Bayesian posterior, submit verdict with 5 most informative citations.
    """

    def __init__(self, *, agent_id: str, openreview_id: str):
        self.agent_id = agent_id
        self.openreview_id = openreview_id
        self._pdf_cache_dir = Path("./papers")
        self._pdf_cache_dir.mkdir(parents=True, exist_ok=True)

    async def on_discussion_tick(self, task: PaperTask, platform: PlatformClient) -> None:
        if await self._has_opened_thread(task.paper.paper_id):
            return

        status = await platform.get_agent_status()
        if status.karma < 2.0:
            log.info(
                "broker_karma_low_skip", paper_id=task.paper.paper_id, karma=status.karma
            )
            return

        parsed = await self._ensure_pdf(task.paper.paper_id, task.paper.pdf_url, platform)
        probability, confidence, reasoning = await score_paper(task.paper, parsed)

        await self._store_prior(task.paper.paper_id, probability, confidence, reasoning)

        entropy = _entropy(probability)
        await record_trajectory(
            "broker_prior",
            agent_id=self.agent_id,
            paper_id=task.paper.paper_id,
            payload={
                "probability": probability,
                "confidence": confidence,
                "entropy": entropy,
                "reasoning": reasoning,
            },
        )

        if entropy < ENTROPY_TRIAGE_THRESHOLD:
            log.info(
                "broker_triage_skip",
                paper_id=task.paper.paper_id,
                entropy=entropy,
                probability=probability,
            )
            return

        # Open the market thread.
        body = OPENING_COMMENT_TEMPLATE.format(probability=probability, reasoning=reasoning)
        idem_key = f"open-thread:{self.agent_id}:{task.paper.paper_id}"
        try:
            comment = await platform.post_comment(
                task.paper.paper_id, body, idempotency_key=idem_key
            )
            await self._mark_thread_opened(task.paper.paper_id, comment.comment_id)
            await record_trajectory(
                "broker_thread_opened",
                agent_id=self.agent_id,
                paper_id=task.paper.paper_id,
                payload={"comment_id": comment.comment_id, "probability": probability},
            )
        except ModerationRejected as e:
            log.warning("broker_thread_moderated", paper_id=task.paper.paper_id, reason=e.reason)

    async def on_verdict_tick(
        self, task: PaperTask, platform: PlatformClient, *, urgent: bool = False
    ) -> None:
        paper_id = task.paper.paper_id
        prior = await self._load_prior(paper_id)
        if prior is None:
            # Didn't score during discussion phase (e.g., ingested late). Score now.
            parsed = await self._ensure_pdf(paper_id, task.paper.pdf_url, platform)
            probability, confidence, reasoning = await score_paper(task.paper, parsed)
            await self._store_prior(paper_id, probability, confidence, reasoning)
            prior = (probability, confidence)

        prob, conf = prior

        comments = await platform.list_comments(paper_id)
        other_comments = [c for c in comments if c.author_openreview_id != self.openreview_id]
        bids = await self._extract_bids(paper_id, other_comments)

        posterior = update_posterior(prob, conf, bids)

        citations = select_citations(
            other_comments,
            own_openreview_id=self.openreview_id,
            bid_contributions=posterior.contributions,
        )

        if len(citations) < 5:
            log.warning(
                "broker_insufficient_citations",
                paper_id=paper_id,
                available=len(citations),
                urgent=urgent,
            )
            if not urgent:
                # Wait for more comments unless deadline is close.
                return
            # Urgent + insufficient comments: submit with whatever we have (platform may reject).

        verdict = Verdict(
            paper_id=paper_id,
            agent_id=self.agent_id,
            score=to_verdict_score(posterior.probability),
            cited_comment_ids=citations,
        )

        idem_key = f"verdict:{self.agent_id}:{paper_id}"
        try:
            await platform.submit_verdict(verdict, idempotency_key=idem_key)
            await self._record_verdict(verdict)
            await record_trajectory(
                "broker_verdict_submitted",
                agent_id=self.agent_id,
                paper_id=paper_id,
                payload={
                    "score": verdict.score,
                    "prior": prob,
                    "posterior": posterior.probability,
                    "bids_used": len(posterior.bids_used),
                    "citations": citations,
                },
            )
        except Exception as e:
            log.error("broker_verdict_failed", paper_id=paper_id, error=str(e))

    # ---- helpers ----

    async def _has_opened_thread(self, paper_id: str) -> bool:
        async with connect() as db:
            cur = await db.execute(
                "SELECT 1 FROM comments WHERE paper_id=? AND author_agent_id=? AND parent_comment_id IS NULL",
                (paper_id, self.agent_id),
            )
            return await cur.fetchone() is not None

    async def _mark_thread_opened(self, paper_id: str, comment_id: str) -> None:
        async with connect() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO comments
                (comment_id, paper_id, author_agent_id, author_openreview_id, thread_id, parent_comment_id, body, posted_at)
                VALUES (?, ?, ?, ?, ?, NULL, '', ?)
                """,
                (
                    comment_id,
                    paper_id,
                    self.agent_id,
                    self.openreview_id,
                    comment_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def _store_prior(
        self, paper_id: str, probability: float, confidence: float, reasoning: str
    ) -> None:
        async with connect() as db:
            await db.execute(
                """
                INSERT INTO trajectory (ts, agent_id, event_type, paper_id, payload_json)
                VALUES (?, ?, 'prior_stored', ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    self.agent_id,
                    paper_id,
                    json.dumps(
                        {
                            "probability": probability,
                            "confidence": confidence,
                            "reasoning": reasoning,
                        }
                    ),
                ),
            )
            await db.commit()

    async def _load_prior(self, paper_id: str) -> tuple[float, float] | None:
        async with connect() as db:
            cur = await db.execute(
                """
                SELECT payload_json FROM trajectory
                WHERE agent_id=? AND paper_id=? AND event_type='prior_stored'
                ORDER BY id DESC LIMIT 1
                """,
                (self.agent_id, paper_id),
            )
            row = await cur.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return float(data["probability"]), float(data["confidence"])

    async def _ensure_pdf(
        self, paper_id: str, pdf_url: str | None, platform: PlatformClient
    ) -> ParsedPaper | None:
        if not pdf_url:
            return None
        path = self._pdf_cache_dir / f"{paper_id}.pdf"
        if not path.exists():
            try:
                await platform.download_pdf(paper_id, str(path))
            except Exception as e:
                log.warning("pdf_download_failed", paper_id=paper_id, error=str(e))
                return None
        try:
            return parse_pdf(path)
        except Exception as e:
            log.warning("pdf_parse_skipped", paper_id=paper_id, error=str(e))
            return None

    async def _extract_bids(self, paper_id: str, comments: list[Comment]) -> list[Bid]:
        """Use the LLM to parse each other-agent comment into a structured bid.

        Cached in the bids table by comment_id.
        """
        if not comments:
            return []

        # Load cached bids first.
        cached: dict[str, Bid] = {}
        async with connect() as db:
            cur = await db.execute(
                "SELECT comment_id, paper_id, author_agent_id, probability, confidence, reasoning, specificity_score FROM bids WHERE paper_id=?",
                (paper_id,),
            )
            for row in await cur.fetchall():
                cached[row["comment_id"]] = Bid(
                    comment_id=row["comment_id"],
                    paper_id=row["paper_id"],
                    author_agent_id=row["author_agent_id"],
                    probability=row["probability"],
                    confidence=row["confidence"],
                    reasoning=row["reasoning"],
                    specificity_score=row["specificity_score"],
                )

        results: list[Bid] = []
        for comment in comments:
            if comment.comment_id in cached:
                results.append(cached[comment.comment_id])
                continue

            try:
                raw = await complete(
                    [
                        {"role": "system", "content": BID_EXTRACTION_SYSTEM},
                        {"role": "user", "content": comment.body},
                    ],
                    task=TaskClass.BULK_ANALYSIS,
                    max_tokens=256,
                    temperature=0.1,
                    json_mode=True,
                )
                data = json.loads(raw)
                prob = data.get("probability")
                if prob is None:
                    continue
                bid = Bid(
                    comment_id=comment.comment_id,
                    paper_id=paper_id,
                    author_agent_id=comment.author_agent_id,
                    probability=max(0.0, min(1.0, float(prob))),
                    confidence=float(data.get("confidence", 0.5)),
                    reasoning=data.get("reasoning_summary", ""),
                    specificity_score=float(data.get("specificity", 0.5)),
                )
                await self._cache_bid(bid)
                results.append(bid)
            except Exception as e:
                log.debug("bid_extract_failed", comment_id=comment.comment_id, error=str(e))
                continue

        return results

    async def _cache_bid(self, bid: Bid) -> None:
        async with connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO bids
                (comment_id, paper_id, author_agent_id, probability, confidence, reasoning, specificity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bid.comment_id,
                    bid.paper_id,
                    bid.author_agent_id,
                    bid.probability,
                    bid.confidence,
                    bid.reasoning,
                    bid.specificity_score,
                ),
            )
            await db.commit()

    async def _record_verdict(self, verdict: Verdict) -> None:
        async with connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO verdicts
                (paper_id, agent_id, score, cited_comment_ids, bad_contribution_flag, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    verdict.paper_id,
                    verdict.agent_id,
                    verdict.score,
                    json.dumps(verdict.cited_comment_ids),
                    verdict.bad_contribution_flag,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()


def make_broker_from_env() -> BrokerAgent:
    return BrokerAgent(
        agent_id=settings.agent_id or f"broker-{uuid.uuid4().hex[:6]}",
        openreview_id=settings.openreview_id or "unknown",
    )
