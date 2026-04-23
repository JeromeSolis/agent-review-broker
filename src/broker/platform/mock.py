import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from broker.models import Comment, Paper, Verdict
from broker.platform.base import AgentStatus, PlatformClient


class MockPlatformClient(PlatformClient):
    """In-memory mock for end-to-end testing before the real MCP schema is published."""

    def __init__(
        self,
        *,
        agent_id: str,
        seed_papers: list[Paper] | None = None,
        initial_karma: float = 100.0,
        paper_release_interval_s: float = 0.5,
    ):
        self.agent_id = agent_id
        self._papers: dict[str, Paper] = {p.paper_id: p for p in (seed_papers or [])}
        self._comments: dict[str, list[Comment]] = {}
        self._verdicts: list[Verdict] = []
        self._karma = initial_karma
        self._strikes = 0
        self._release_interval = paper_release_interval_s
        self._release_queue: list[Paper] = list(seed_papers or [])
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def stream_new_papers(self) -> AsyncIterator[Paper]:
        for paper in self._release_queue:
            await asyncio.sleep(self._release_interval)
            yield paper

    async def get_paper(self, paper_id: str) -> Paper:
        return self._papers[paper_id]

    async def download_pdf(self, paper_id: str, dest_path: str) -> None:
        # Mock writes an empty placeholder.
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dest_path).write_bytes(b"%PDF-1.4\n%mock\n")

    async def list_comments(self, paper_id: str) -> list[Comment]:
        return list(self._comments.get(paper_id, []))

    async def post_comment(
        self,
        paper_id: str,
        body: str,
        *,
        parent_comment_id: str | None = None,
        idempotency_key: str,
    ) -> Comment:
        cost = 1.0 if paper_id not in self._comments or not self._comments[paper_id] else 0.1
        if self._karma < cost:
            raise RuntimeError(f"insufficient karma: have {self._karma}, need {cost}")
        self._karma -= cost

        comment = Comment(
            comment_id=f"mock-{uuid.uuid4().hex[:8]}",
            paper_id=paper_id,
            author_agent_id=self.agent_id,
            thread_id=parent_comment_id or f"thread-{uuid.uuid4().hex[:8]}",
            parent_comment_id=parent_comment_id,
            body=body,
            posted_at=datetime.now(UTC),
        )
        self._comments.setdefault(paper_id, []).append(comment)
        return comment

    async def submit_verdict(
        self,
        verdict: Verdict,
        *,
        idempotency_key: str,
    ) -> None:
        if len(verdict.cited_comment_ids) < 5:
            raise RuntimeError("need >=5 citations")
        self._verdicts.append(
            verdict.model_copy(update={"submitted_at": datetime.now(UTC)})
        )

    async def get_agent_status(self) -> AgentStatus:
        return AgentStatus(karma=self._karma, strikes=self._strikes)

    # Test helpers
    def inject_comment(self, comment: Comment) -> None:
        self._comments.setdefault(comment.paper_id, []).append(comment)

    def submitted_verdicts(self) -> list[Verdict]:
        return list(self._verdicts)


def make_sample_papers(n: int = 5) -> list[Paper]:
    now = datetime.now(UTC)
    return [
        Paper(
            paper_id=f"icml2026-{i:04d}",
            title=f"Mock paper {i}",
            abstract=f"Abstract of mock paper {i}. " * 5,
            pdf_url=f"https://koala.science/papers/icml2026-{i:04d}.pdf",
            github_url=f"https://github.com/mock/paper-{i}" if i % 3 == 0 else None,
            released_at=now + timedelta(seconds=i),
        )
        for i in range(n)
    ]
