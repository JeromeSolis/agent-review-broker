"""Thin JSON-RPC client for the Koala Science MCP endpoint.

Mirrors the reference implementation in koala-science/peer-review-agents
(agent_definition/harness/koala.py). Every platform action — fetching papers,
posting comments, submitting verdicts — goes through `call_tool`.
"""

from typing import Any

import httpx

from broker.config import settings
from broker.logging import log


class KoalaError(RuntimeError):
    """Wraps a JSON-RPC error returned by the Koala MCP server."""


class KoalaClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.koala_api_key
        if not self.api_key:
            raise RuntimeError(
                "Koala API key missing. Drop it at agent_configs/<name>/.api_key "
                "or set COALESCENCE_API_KEY in .env"
            )
        self.mcp_url = (base_url or settings.koala_mcp_url).rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._id = 0
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool and return the flattened text content.

        Raises KoalaError on JSON-RPC error responses so the caller (the
        harness tool-dispatcher) can surface the error back to the LLM.
        """
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        log.debug("koala_call", tool=name, id=self._id)
        resp = await self._client.post(self.mcp_url, json=payload, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise KoalaError(str(data["error"]))
        content = data.get("result", {}).get("content", [])
        return "\n".join(
            block.get("text", "") for block in content if block.get("type") == "text"
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        """Fetch the live tool catalog from the server — used at startup to
        confirm schemas match what we hard-code below."""
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": "tools/list"}
        resp = await self._client.post(self.mcp_url, json=payload, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise KoalaError(str(data["error"]))
        return data.get("result", {}).get("tools", [])
