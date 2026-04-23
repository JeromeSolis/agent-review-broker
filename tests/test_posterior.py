from datetime import UTC, datetime

from broker.market.posterior import update_posterior
from broker.models import Bid


def _bid(comment_id: str, p: float, specificity: float = 0.7, confidence: float = 0.7) -> Bid:
    return Bid(
        comment_id=comment_id,
        paper_id="test-paper",
        author_agent_id=f"agent-{comment_id}",
        probability=p,
        confidence=confidence,
        reasoning="x",
        specificity_score=specificity,
    )


def test_no_bids_returns_prior():
    result = update_posterior(prior=0.3, prior_confidence=0.5, bids=[])
    assert result.probability == 0.3
    assert result.bids_used == []


def test_bids_pull_posterior_toward_consensus():
    # Prior at 0.3, three informed bids clustered at 0.7 should pull the posterior up.
    result = update_posterior(
        prior=0.3,
        prior_confidence=0.3,
        bids=[_bid("a", 0.7), _bid("b", 0.75), _bid("c", 0.72)],
    )
    assert result.probability > 0.4


def test_low_specificity_bids_get_downweighted():
    high_spec = update_posterior(
        prior=0.3, prior_confidence=0.3, bids=[_bid("a", 0.9, specificity=0.9)]
    )
    low_spec = update_posterior(
        prior=0.3, prior_confidence=0.3, bids=[_bid("a", 0.9, specificity=0.1)]
    )
    assert high_spec.probability > low_spec.probability


def test_contributions_recorded_for_each_bid():
    result = update_posterior(
        prior=0.3,
        prior_confidence=0.3,
        bids=[_bid("a", 0.8), _bid("b", 0.6)],
    )
    assert "a" in result.contributions
    assert "b" in result.contributions


def test_single_bid_cannot_dominate():
    # A single extreme bid at p=0.99 should not flip a prior of 0.1 to >0.9.
    result = update_posterior(
        prior=0.1, prior_confidence=0.7, bids=[_bid("a", 0.99, specificity=1.0, confidence=1.0)]
    )
    assert result.probability < 0.9
