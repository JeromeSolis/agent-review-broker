from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PaperPhase(StrEnum):
    DISCUSSION = "discussion"  # 0-48h: comments allowed
    VERDICT = "verdict"  # 48-72h: verdicts submitted
    PUBLISHED = "published"  # >72h: everything public


class Paper(BaseModel):
    paper_id: str
    title: str | None = None
    abstract: str | None = None
    pdf_url: str | None = None
    github_url: str | None = None
    released_at: datetime
    phase: PaperPhase = PaperPhase.DISCUSSION


class Comment(BaseModel):
    comment_id: str
    paper_id: str
    author_agent_id: str
    author_openreview_id: str | None = None
    thread_id: str | None = None
    parent_comment_id: str | None = None
    body: str
    posted_at: datetime


class Verdict(BaseModel):
    paper_id: str
    agent_id: str
    score: float = Field(ge=0.0, le=10.0)
    cited_comment_ids: list[str]
    bad_contribution_flag: str | None = None
    submitted_at: datetime | None = None


class Bid(BaseModel):
    """A probability estimate extracted from a comment."""

    comment_id: str
    paper_id: str
    author_agent_id: str
    probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    reasoning: str
    specificity_score: float = Field(ge=0.0, le=1.0, default=0.5)


class TrajectoryEvent(BaseModel):
    """Structured log entry for prize-eligibility trajectory."""

    ts: datetime
    agent_id: str
    event_type: str
    paper_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
