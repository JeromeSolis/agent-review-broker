from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from broker.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    pdf_url TEXT,
    github_url TEXT,
    released_at TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'discussion',
    verdict_deadline TEXT NOT NULL,
    pdf_local_path TEXT,
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_papers_phase ON papers(phase);
CREATE INDEX IF NOT EXISTS idx_papers_deadline ON papers(verdict_deadline);

CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    author_agent_id TEXT NOT NULL,
    author_openreview_id TEXT,
    thread_id TEXT,
    parent_comment_id TEXT,
    body TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
);

CREATE INDEX IF NOT EXISTS idx_comments_paper ON comments(paper_id);
CREATE INDEX IF NOT EXISTS idx_comments_thread ON comments(thread_id);

CREATE TABLE IF NOT EXISTS verdicts (
    paper_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    score REAL NOT NULL,
    cited_comment_ids TEXT NOT NULL,
    bad_contribution_flag TEXT,
    submitted_at TEXT,
    PRIMARY KEY (paper_id, agent_id)
);

CREATE TABLE IF NOT EXISTS bids (
    comment_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    author_agent_id TEXT NOT NULL,
    probability REAL NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    specificity_score REAL NOT NULL,
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bids_paper ON bids(paper_id);

CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    karma REAL NOT NULL DEFAULT 100.0,
    strikes INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Ecosystem intelligence populated by Scout.
CREATE TABLE IF NOT EXISTS ecosystem_agents (
    agent_id TEXT PRIMARY KEY,
    openreview_id TEXT,
    comment_count INTEGER NOT NULL DEFAULT 0,
    avg_specificity REAL,
    citation_yield REAL,  -- fraction of their comments that get cited
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS trajectory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    paper_id TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trajectory_agent ON trajectory(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_trajectory_paper ON trajectory(paper_id);

-- Idempotency ledger: prevents double-posting on crash recovery.
CREATE TABLE IF NOT EXISTS outbox (
    idempotency_key TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    paper_id TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
"""


async def init_db(path: Path | None = None) -> None:
    path = path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(SCHEMA)
        await db.commit()


@asynccontextmanager
async def connect(path: Path | None = None) -> AsyncIterator[aiosqlite.Connection]:
    path = path or settings.db_path
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = aiosqlite.Row
        yield db
