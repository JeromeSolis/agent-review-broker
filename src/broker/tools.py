"""Tool definitions exposed to the LLM harness.

Two families:
- Koala MCP tools — fetched live from the server via `fetch_koala_schemas`
  and passed through the dispatcher to `KoalaClient.call_tool`. We do NOT
  hard-code Koala schemas — the live skill.md is authoritative per
  GLOBAL_RULES and the platform evolves.
- Local Python tools — expose our market math (Bayesian posterior, citation
  selection, paper scoring) and the github_file_url writer. Hard-coded here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from broker.git_helper import write_reasoning_and_commit
from broker.ingestion.pdf import parse_pdf
from broker.koala_client import KoalaClient, KoalaError
from broker.logging import log, record_trajectory
from broker.market import score_paper as score_paper_impl
from broker.market import select_citations as select_citations_impl
from broker.market import update_posterior as update_posterior_impl
from broker.models import Bid, Comment, Paper

# Koala MCP tool schemas are fetched live. See fetch_koala_schemas() below.
_KOALA_TOOL_NAMES: set[str] = set()


async def fetch_koala_schemas(koala: KoalaClient) -> list[dict[str, Any]]:
    """Pull the current tool catalog from Koala and translate to Anthropic format.

    MCP tool schema uses `inputSchema` (camelCase) while Anthropic expects
    `input_schema` (snake_case). We also record names into _KOALA_TOOL_NAMES
    so the dispatcher knows which calls to forward vs handle locally.
    """
    raw = await koala.list_tools()
    out: list[dict[str, Any]] = []
    _KOALA_TOOL_NAMES.clear()
    for t in raw:
        name = t.get("name")
        if not name:
            continue
        _KOALA_TOOL_NAMES.add(name)
        out.append(
            {
                "name": name,
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema") or t.get("input_schema") or {"type": "object", "properties": {}},
            }
        )
    log.info("koala_schemas_loaded", count=len(out), names=sorted(_KOALA_TOOL_NAMES))
    return out

# ---------------------------------------------------------------------------
# Local tool schemas
# ---------------------------------------------------------------------------

LOCAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "score_paper",
        "description": (
            "Compute a calibrated P(accept) prior for a paper using a local LLM (DGX Ollama). "
            "Returns {probability, confidence, reasoning, entropy}. Entropy > 0.9 means the "
            "prior is uncertain — good triage signal for deciding whether to open a thread."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "title": {"type": "string"},
                "abstract": {"type": "string"},
                "github_url": {"type": "string"},
                "pdf_sections": {
                    "type": "object",
                    "description": "Optional pre-parsed sections: {introduction, method, experiments, conclusion}",
                },
            },
            "required": ["paper_id", "title", "abstract"],
        },
    },
    {
        "name": "update_posterior",
        "description": (
            "Run a weighted Bayesian posterior update in log-odds space given a prior and bids. "
            "Each bid has {comment_id, probability, confidence, specificity_score}. Returns "
            "{probability, confidence, contributions} where contributions[comment_id] is the "
            "log-odds shift that bid produced — use it to rank comments for citation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prior": {"type": "number"},
                "prior_confidence": {"type": "number"},
                "bids": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "comment_id": {"type": "string"},
                            "paper_id": {"type": "string"},
                            "author_agent_id": {"type": "string"},
                            "probability": {"type": "number"},
                            "confidence": {"type": "number"},
                            "specificity_score": {"type": "number"},
                            "reasoning": {"type": "string"},
                        },
                        "required": [
                            "comment_id",
                            "paper_id",
                            "author_agent_id",
                            "probability",
                        ],
                    },
                },
            },
            "required": ["prior", "prior_confidence", "bids"],
        },
    },
    {
        "name": "select_citations",
        "description": (
            "Pick at least 5 informative comment IDs to cite in a verdict. Filters out "
            "same-OpenReview-ID agents. Prefers comments whose bids moved the posterior most."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "comment_id": {"type": "string"},
                            "author_openreview_id": {"type": "string"},
                            "posted_at": {"type": "string"},
                        },
                        "required": ["comment_id"],
                    },
                },
                "own_openreview_id": {"type": "string"},
                "bid_contributions": {
                    "type": "object",
                    "description": "From update_posterior — comment_id -> log-odds shift",
                },
                "required": {"type": "integer", "description": "Default 5"},
            },
            "required": ["comments", "own_openreview_id"],
        },
    },
    {
        "name": "write_reasoning_and_commit",
        "description": (
            "Write a markdown reasoning file to agent_configs/<agent_name>/reasoning/, git "
            "commit+push it, and return the github blob URL. Call this BEFORE post_comment "
            "or post_verdict and pass the returned URL as github_file_url."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title — used for filename and commit msg."},
                "body": {"type": "string", "description": "Markdown body documenting reasoning and evidence."},
                "paper_id": {"type": "string", "description": "Optional — included in filename for traceability."},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "parse_pdf_sections",
        "description": (
            "Download a paper PDF by URL and extract its sections. Useful before score_paper "
            "when the abstract alone is too thin. Returns {abstract, introduction, method, "
            "experiments, conclusion, page_count}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_url": {"type": "string"},
            },
            "required": ["pdf_url"],
        },
    },
    {
        "name": "record_trajectory",
        "description": (
            "Log a structured event to the agent's trajectory database. Required for prize "
            "eligibility. Use at key decision points (triage choices, bid aggregation results, "
            "verdict submissions) to create an audit trail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string"},
                "paper_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["event_type"],
        },
    },
]


async def all_tool_schemas(koala: KoalaClient) -> list[dict[str, Any]]:
    """Assemble the full tool catalog: live Koala schemas + hard-coded local tools."""
    koala_schemas = await fetch_koala_schemas(koala)
    return koala_schemas + LOCAL_TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# Local tool handlers
# ---------------------------------------------------------------------------


async def _handle_score_paper(args: dict[str, Any]) -> str:
    import math

    paper = Paper(
        paper_id=args["paper_id"],
        title=args.get("title"),
        abstract=args.get("abstract"),
        github_url=args.get("github_url"),
        released_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    probability, confidence, reasoning = await score_paper_impl(paper, None)
    # Binary entropy in bits.
    entropy = 0.0
    if 0 < probability < 1:
        entropy = -(
            probability * math.log2(probability)
            + (1 - probability) * math.log2(1 - probability)
        )
    return json.dumps(
        {
            "probability": probability,
            "confidence": confidence,
            "reasoning": reasoning,
            "entropy": entropy,
            "verdict_score": round(probability * 10.0, 2),
        }
    )


async def _handle_update_posterior(args: dict[str, Any]) -> str:
    bids = [Bid(**b) for b in args["bids"]]
    result = update_posterior_impl(
        prior=args["prior"],
        prior_confidence=args.get("prior_confidence", 0.5),
        bids=bids,
    )
    return json.dumps(
        {
            "probability": result.probability,
            "confidence": result.confidence,
            "contributions": result.contributions,
            "bids_used": len(result.bids_used),
            "verdict_score": round(result.probability * 10.0, 2),
        }
    )


async def _handle_select_citations(args: dict[str, Any]) -> str:
    from datetime import datetime

    comments = []
    for c in args["comments"]:
        posted_at = c.get("posted_at")
        if isinstance(posted_at, str):
            posted_at = datetime.fromisoformat(posted_at)
        else:
            posted_at = datetime.now()
        comments.append(
            Comment(
                comment_id=c["comment_id"],
                paper_id=c.get("paper_id", ""),
                author_agent_id=c.get("author_agent_id", ""),
                author_openreview_id=c.get("author_openreview_id"),
                body=c.get("body", ""),
                posted_at=posted_at,
            )
        )
    ids = select_citations_impl(
        comments,
        own_openreview_id=args["own_openreview_id"],
        bid_contributions=args.get("bid_contributions"),
        required=args.get("required", 5),
    )
    return json.dumps({"cited_comment_ids": ids})


async def _handle_write_reasoning(args: dict[str, Any]) -> str:
    url = await write_reasoning_and_commit(
        title=args["title"],
        body=args["body"],
        paper_id=args.get("paper_id"),
    )
    return json.dumps({"github_file_url": url})


async def _handle_parse_pdf(args: dict[str, Any]) -> str:
    import tempfile

    import httpx

    pdf_url = args["pdf_url"]
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(pdf_url, follow_redirects=True)
        resp.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name
    parsed = parse_pdf(tmp_path)
    return json.dumps(
        {
            "abstract": parsed.sections.get("abstract", "")[:4000],
            "introduction": parsed.sections.get("introduction", "")[:4000],
            "method": parsed.sections.get("method", "")[:4000],
            "experiments": parsed.sections.get("experiments", "")[:4000],
            "conclusion": parsed.sections.get("conclusion", "")[:2000],
            "page_count": parsed.page_count,
        }
    )


async def _handle_record_trajectory(args: dict[str, Any]) -> str:
    await record_trajectory(
        event_type=args["event_type"],
        paper_id=args.get("paper_id"),
        payload=args.get("payload") or {},
    )
    return json.dumps({"ok": True})


LOCAL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "score_paper": _handle_score_paper,
    "update_posterior": _handle_update_posterior,
    "select_citations": _handle_select_citations,
    "write_reasoning_and_commit": _handle_write_reasoning,
    "parse_pdf_sections": _handle_parse_pdf,
    "record_trajectory": _handle_record_trajectory,
}

@dataclass
class Dispatcher:
    koala: KoalaClient

    async def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Route a tool call. Koala names are resolved against the live schema
        set populated by fetch_koala_schemas(). Errors are stringified so the
        LLM can react rather than crashing the loop."""
        log.debug("tool_dispatch", tool=tool_name)
        try:
            if tool_name in _KOALA_TOOL_NAMES:
                result = await self.koala.call_tool(tool_name, tool_input)
                return result if result else "(empty response)"
            if tool_name in LOCAL_HANDLERS:
                return await LOCAL_HANDLERS[tool_name](tool_input)
            return json.dumps({"error": f"unknown tool {tool_name}"})
        except KoalaError as e:
            log.warning("koala_error", tool=tool_name, error=str(e))
            return json.dumps({"error": f"koala: {e}"})
        except Exception as e:
            log.exception("tool_error", tool=tool_name)
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
