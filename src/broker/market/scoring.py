import json
import math

from broker.ingestion.pdf import ParsedPaper
from broker.llm import TaskClass, complete
from broker.logging import log
from broker.models import Paper

# ICML historical acceptance rate — anchor for calibration.
ICML_BASE_RATE = 0.27

SYSTEM_PROMPT = """You are an expert ML peer reviewer assessing ICML 2026 submissions.
Your job is to estimate the probability this paper would be accepted at ICML 2026.

Ground truth: ICML's historical acceptance rate is ~27%. Anchor your estimate on this base rate
and update it based on evidence in the paper. Be calibrated, not aspirational.

Consider: technical novelty, experimental rigor, baselines, clarity of writing, scope of
contribution, theoretical or empirical soundness. Do NOT reward ambition or breadth of scope;
reward *executed* quality.

Respond with JSON: {"probability": <float 0-1>, "confidence": <float 0-1>, "reasoning": "<1-2 sentences>"}
"""


def _build_prompt(paper: Paper, parsed: ParsedPaper | None) -> str:
    parts = [f"PAPER ID: {paper.paper_id}"]
    if paper.title:
        parts.append(f"TITLE: {paper.title}")
    if paper.abstract:
        parts.append(f"ABSTRACT:\n{paper.abstract}")

    if parsed:
        for section in ("introduction", "method", "experiments", "conclusion"):
            text = parsed.sections.get(section)
            if text:
                # Cap per-section content to keep tokens bounded.
                parts.append(f"{section.upper()}:\n{text[:3000]}")

    if paper.github_url:
        parts.append(f"GITHUB: {paper.github_url}")

    return "\n\n".join(parts)


def _entropy(p: float) -> float:
    """Binary entropy in bits. 0 at p=0/1, 1 at p=0.5."""
    if p <= 0 or p >= 1:
        return 0.0
    return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


async def score_paper(paper: Paper, parsed: ParsedPaper | None = None) -> tuple[float, float, str]:
    """Produce a calibrated accept-probability for a paper.

    Returns (probability, confidence, reasoning).
    """
    user_prompt = _build_prompt(paper, parsed)
    raw = await complete(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        task=TaskClass.CRITICAL,
        # Local reasoning-trained models (Ollama Qwen/Gemma/Nemotron) emit
        # hidden reasoning tokens that count against max_tokens; we need
        # generous headroom so the final JSON content actually emerges.
        max_tokens=1500,
        temperature=0.2,
        json_mode=True,
    )

    try:
        data = json.loads(raw)
        prob = float(data["probability"])
        conf = float(data.get("confidence", 0.5))
        reasoning = str(data.get("reasoning", ""))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning("score_parse_failed", paper_id=paper.paper_id, error=str(e), raw=raw[:200])
        return ICML_BASE_RATE, 0.1, "parse failure, returning base rate"

    prob = max(0.0, min(1.0, prob))
    conf = max(0.0, min(1.0, conf))
    return prob, conf, reasoning


def to_verdict_score(probability: float) -> float:
    """Map an accept-probability [0,1] to the platform's 0-10 verdict scale."""
    return round(probability * 10.0, 2)
