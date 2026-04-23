from broker.models import Bid, Comment

REQUIRED_CITATIONS = 5


def select_citations(
    comments: list[Comment],
    *,
    own_openreview_id: str,
    bid_contributions: dict[str, float] | None = None,
    required: int = REQUIRED_CITATIONS,
) -> list[str]:
    """Pick at least `required` comment IDs to cite.

    Rules enforced:
    - No self-citations (same OR ID as us).
    - Prefer comments whose bids moved the posterior most (informativeness).
    - Fill remainder with any other eligible comments (MVP fallback).
    """
    eligible = [c for c in comments if c.author_openreview_id != own_openreview_id]

    if not eligible:
        return []

    if bid_contributions:
        # Sort eligible comments by |log-odds shift| descending; ties broken by recency.
        eligible.sort(
            key=lambda c: (
                abs(bid_contributions.get(c.comment_id, 0.0)),
                c.posted_at,
            ),
            reverse=True,
        )
    else:
        eligible.sort(key=lambda c: c.posted_at, reverse=True)

    return [c.comment_id for c in eligible[:required]]


def _bid_is_own(bid: Bid, own_openreview_id: str, own_agent_id: str) -> bool:
    return bid.author_agent_id == own_agent_id
