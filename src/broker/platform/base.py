from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from broker.models import Comment, Paper, Verdict


class PlatformError(Exception):
    """Base for platform errors."""


class RateLimited(PlatformError):
    """Platform throttled us. Respect retry_after."""

    def __init__(self, retry_after_s: float):
        self.retry_after_s = retry_after_s
        super().__init__(f"rate limited, retry after {retry_after_s}s")


class ModerationRejected(PlatformError):
    """Comment was rejected by the automated moderator."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"moderation: {reason}")


@dataclass
class AgentStatus:
    karma: float
    strikes: int


class PlatformClient(ABC):
    """Abstract interface over the Koala platform.

    Real implementation wraps the MCP endpoint; mock implementation is used
    pre-launch and in tests. Every method is idempotent or explicitly tracked
    via the outbox table so crash-recovery does not double-post.
    """

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def stream_new_papers(self) -> AsyncIterator[Paper]:
        """Yield newly released papers as they appear."""
        yield  # pragma: no cover

    @abstractmethod
    async def get_paper(self, paper_id: str) -> Paper: ...

    @abstractmethod
    async def download_pdf(self, paper_id: str, dest_path: str) -> None: ...

    @abstractmethod
    async def list_comments(self, paper_id: str) -> list[Comment]: ...

    @abstractmethod
    async def post_comment(
        self,
        paper_id: str,
        body: str,
        *,
        parent_comment_id: str | None = None,
        idempotency_key: str,
    ) -> Comment: ...

    @abstractmethod
    async def submit_verdict(
        self,
        verdict: Verdict,
        *,
        idempotency_key: str,
    ) -> None: ...

    @abstractmethod
    async def get_agent_status(self) -> AgentStatus: ...
