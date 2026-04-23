"""End-to-end smoke test: Broker processes a paper against the mock platform.

LLM calls are stubbed so the test runs offline with no API keys.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

os.environ.setdefault("PLATFORM_MODE", "mock")
os.environ.setdefault("AGENT_ID", "test-broker")
os.environ.setdefault("OPENREVIEW_ID", "~Test_User1")

from broker.agents.broker import BrokerAgent
from broker.db import init_db
from broker.ingestion.papers import upsert_paper
from broker.models import Comment, Paper
from broker.platform.mock import MockPlatformClient
from broker.scheduler.state_machine import PaperTask, current_phase


async def _fake_score_prompt(*args, **kwargs):
    # Return an uncertain prior to trigger the triage threshold.
    return json.dumps({"probability": 0.5, "confidence": 0.4, "reasoning": "ambiguous case"})


async def _fake_bid_extract(*args, **kwargs):
    return json.dumps(
        {"probability": 0.7, "confidence": 0.8, "specificity": 0.8, "reasoning_summary": "strong novelty"}
    )


@pytest.fixture
async def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("broker.config.settings.db_path", db_path)
    monkeypatch.setattr("broker.config.settings.agent_id", "test-broker")
    monkeypatch.setattr("broker.config.settings.openreview_id", "~Test_User1")
    await init_db(db_path)
    yield db_path


async def test_broker_opens_thread_on_ambiguous_paper(tmp_db, tmp_path, monkeypatch):
    paper = Paper(
        paper_id="test-001",
        title="An Ambiguous Paper",
        abstract="We do a thing. Results mixed.",
        pdf_url=None,
        released_at=datetime.now(UTC),
    )
    await upsert_paper(paper)

    platform = MockPlatformClient(agent_id="test-broker", seed_papers=[paper])
    await platform.connect()

    broker = BrokerAgent(agent_id="test-broker", openreview_id="~Test_User1")
    broker._pdf_cache_dir = tmp_path / "pdfs"
    broker._pdf_cache_dir.mkdir()

    async def stub_complete(messages, *, task, max_tokens, temperature, json_mode):
        if any("ML peer reviewer" in m["content"] for m in messages):
            return await _fake_score_prompt()
        return await _fake_bid_extract()

    with patch("broker.market.scoring.complete", side_effect=stub_complete):
        task = PaperTask(
            paper=paper,
            phase=current_phase(paper.released_at),
            hours_elapsed=0.0,
            hours_remaining=72.0,
        )
        await broker.on_discussion_tick(task, platform)

    comments = await platform.list_comments("test-001")
    assert len(comments) == 1, "broker should open a thread on an ambiguous paper"
    assert "P(accept) = 0.50" in comments[0].body


async def test_broker_submits_verdict_in_verdict_phase(tmp_db, tmp_path, monkeypatch):
    released = datetime.now(UTC) - timedelta(hours=50)
    paper = Paper(
        paper_id="test-002",
        title="Verdict Phase Paper",
        abstract="test",
        pdf_url=None,
        released_at=released,
    )
    await upsert_paper(paper)

    platform = MockPlatformClient(agent_id="test-broker", seed_papers=[paper])
    await platform.connect()

    # Inject 6 comments from other agents so we have enough to cite.
    for i in range(6):
        platform.inject_comment(
            Comment(
                comment_id=f"other-{i}",
                paper_id="test-002",
                author_agent_id=f"other-agent-{i}",
                author_openreview_id=f"~Other_{i}",
                thread_id=f"thread-{i}",
                body=f"I estimate probability 0.6 because reason {i}",
                posted_at=datetime.now(UTC),
            )
        )

    broker = BrokerAgent(agent_id="test-broker", openreview_id="~Test_User1")
    broker._pdf_cache_dir = tmp_path / "pdfs"
    broker._pdf_cache_dir.mkdir()

    async def stub_complete(messages, *, task, max_tokens, temperature, json_mode):
        if any("ML peer reviewer" in m["content"] for m in messages):
            return await _fake_score_prompt()
        return await _fake_bid_extract()

    with patch("broker.market.scoring.complete", side_effect=stub_complete), \
         patch("broker.agents.broker.complete", side_effect=stub_complete):
        task = PaperTask(
            paper=paper,
            phase=current_phase(released),
            hours_elapsed=50.0,
            hours_remaining=22.0,
        )
        await broker.on_verdict_tick(task, platform)

    verdicts = platform.submitted_verdicts()
    assert len(verdicts) == 1
    assert 0 <= verdicts[0].score <= 10
    assert len(verdicts[0].cited_comment_ids) == 5
