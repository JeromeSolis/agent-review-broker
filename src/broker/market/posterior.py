import math
from dataclasses import dataclass

from broker.models import Bid


@dataclass
class PosteriorResult:
    probability: float
    confidence: float
    bids_used: list[Bid]
    contributions: dict[str, float]  # comment_id -> log-odds shift attributed to this bid


def _logit(p: float, eps: float = 1e-6) -> float:
    p = max(eps, min(1.0 - eps, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def update_posterior(
    prior: float,
    prior_confidence: float,
    bids: list[Bid],
    *,
    max_shift_per_bid: float = 1.5,  # cap in log-odds space to prevent single-bid dominance
) -> PosteriorResult:
    """Weighted Bayesian update in log-odds space.

    Each bid contributes a log-odds shift toward its own probability, weighted by
    specificity and confidence. The shift is capped per-bid to prevent any single
    bid from dominating the posterior. Bids from agents we flag as low-quality
    can be filtered upstream.

    Not a naive mean: the log-odds space preserves Bayesian semantics
    (contributions add, not average), and specificity weights filter noise.
    """
    if not bids:
        return PosteriorResult(
            probability=prior, confidence=prior_confidence, bids_used=[], contributions={}
        )

    prior_logit = _logit(prior)
    posterior_logit = prior_logit

    total_weight = prior_confidence * 2.0  # prior counts as two unit-weight bids
    contributions: dict[str, float] = {}

    for bid in bids:
        bid_logit = _logit(bid.probability)
        weight = bid.specificity_score * bid.confidence
        if weight <= 0:
            continue

        raw_shift = (bid_logit - posterior_logit) * weight
        clipped = max(-max_shift_per_bid, min(max_shift_per_bid, raw_shift))

        posterior_logit += clipped / (total_weight + weight) * weight * 2.0
        total_weight += weight
        contributions[bid.comment_id] = clipped

    probability = _sigmoid(posterior_logit)
    # Confidence grows with total weight but saturates.
    confidence = min(1.0, total_weight / (total_weight + 4.0))

    return PosteriorResult(
        probability=probability,
        confidence=confidence,
        bids_used=bids,
        contributions=contributions,
    )
