"""Real Koala platform client over MCP.

STATUS: Stub. Tool names and payload schemas are unknown until the competition
launches Fri 2026-04-24 12:00 ET. At launch, replace the TODOs below with the
real tool names and argument shapes from Koala's published MCP spec.

Design: thin mapping from PlatformClient domain methods → MCP tool calls.
"""

from collections.abc import AsyncIterator

from broker.config import settings
from broker.models import Comment, Paper, Verdict
from broker.platform.base import AgentStatus, PlatformClient


class KoalaPlatformClient(PlatformClient):
    def __init__(self, *, agent_id: str, mcp_url: str | None = None, api_key: str | None = None):
        self.agent_id = agent_id
        self.mcp_url = mcp_url or settings.koala_mcp_url
        self.api_key = api_key or settings.koala_api_key
        self._session = None  # TODO: MCP ClientSession at launch

    async def connect(self) -> None:
        # TODO(launch): open MCP ClientSession against self.mcp_url with auth.
        raise NotImplementedError("wire at competition launch")

    async def close(self) -> None:
        if self._session is not None:
            # TODO(launch): close session
            pass

    async def stream_new_papers(self) -> AsyncIterator[Paper]:
        # TODO(launch): poll or subscribe to paper stream via MCP tool.
        # Likely tool: "papers.list_new" with a since cursor.
        raise NotImplementedError
        yield  # pragma: no cover

    async def get_paper(self, paper_id: str) -> Paper:
        # TODO(launch): tool "papers.get"
        raise NotImplementedError

    async def download_pdf(self, paper_id: str, dest_path: str) -> None:
        # TODO(launch): tool "papers.download_pdf" or follow pdf_url with httpx.
        raise NotImplementedError

    async def list_comments(self, paper_id: str) -> list[Comment]:
        # TODO(launch): tool "comments.list"
        raise NotImplementedError

    async def post_comment(
        self,
        paper_id: str,
        body: str,
        *,
        parent_comment_id: str | None = None,
        idempotency_key: str,
    ) -> Comment:
        # TODO(launch): tool "comments.post"
        raise NotImplementedError

    async def submit_verdict(
        self,
        verdict: Verdict,
        *,
        idempotency_key: str,
    ) -> None:
        # TODO(launch): tool "verdicts.submit"
        raise NotImplementedError

    async def get_agent_status(self) -> AgentStatus:
        # TODO(launch): tool "agent.status" — karma + strikes
        raise NotImplementedError
