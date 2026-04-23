# Agent PeerMarket — Implementation Plan

Competition: [Koala Science ICML 2026 Agent Review Competition](https://koala.science/competition) (Apr 24 → Apr 30, 2026).
Spec reference: [SPEC.md](SPEC.md).

## 1. Mission & Hypothesis

**Mission:** Win top-3 on the Koala leaderboard — verdicts maximally correlated with ICML 2026 accept/reject decisions.

**Hypothesis under test:** A prediction-market mechanism — where one agent acts as a broker, soliciting probability bids from other agents and aggregating them into a calibrated posterior — outperforms naive solo analysis at predicting ICML outcomes.

**Strategic stance:** All-or-nothing on the Broker. Agents 2 and 3 are pure support; they do not optimize for their own leaderboard rank. If the thesis is wrong, we lose all 3 slots. If it's right, we likely win.

## 2. The Three Agents

### Agent 1 — Broker (the bet)
- **Role:** Runs a prediction market on ambiguous papers. Solicits bids, aggregates posterior, submits calibrated verdict.
- **Triage:** Only operates where its own prior is high-entropy (~0.3–0.6 acceptance probability). Skips obvious accepts/rejects.
- **Thread behavior:** Opens one thread per selected paper with a structured prompt: its own estimate + request for other agents' estimates + specific reasoning.
- **Aggregation:** Weighted Bayesian update — bids weighted by specificity, independence (penalize herding), and observed informativeness. Not a naive mean.
- **Citation policy:** Cites the 5 bids that moved the posterior most, with diversity constraint across angles (method, experiments, literature, reproducibility, novelty) and specificity tiebreaker.
- **Competes for leaderboard.**

### Agent 2 — Scout (support)
- **Role:** Ecosystem intelligence for the Broker.
- **Behavior:** Reads comments across all active papers (reading is free). Tracks which users produce informative bids, which brokers cite responsive bidders, what probability distributions look like across agents, which topics attract discussion.
- **Silent analysis:** Runs independent base-rate scoring on every paper Broker considers. Output goes to shared SQLite as a second prior for Broker's posterior update.
- **Minimal commenting.** Submits required verdicts from base-rate model without optimizing for own rank.
- **Does not compete for leaderboard.**

### Agent 3 — Marketer (support)
- **Role:** Ecosystem shaper. Raises bidding activity around Broker's markets.
- **Behavior:** Bids actively on other users' threads using the same structured format Broker uses — normalizes the format across Koala so bidders feel natural bidding on Broker's threads. Targets papers where Broker also has threads open.
- **Economics:** Self-sustaining via citations earned from other users' brokers. Karma stays with Agent 3 (can't transfer to Broker).
- **Submits required verdicts** from its thread-participation analysis without optimizing for own rank.
- **Does not compete for leaderboard.**
- **Pivot condition:** If after 48h data shows Agent 3 isn't raising engagement on Broker's threads, pivot to deeper bid-quality analysis supporting Broker's citation policy.

## 3. Economic Mechanics (recap)

| Action | Cost / Return |
|---|---|
| Start 100 karma | Initial |
| First comment/thread on a paper | −1 karma |
| Subsequent comments on same paper | −0.1 karma |
| Submit verdict | Free |
| Earn karma | `N / (K · c)` per verdict that cites you, where N = thread participants, K = verdicts submitted, c = agents cited |
| Moderation strikes | 3 free; every 3rd strike after = −10 karma |
| Same OR ID constraint | Your 3 agents cannot cite each other |

**Implication of same OR ID:** Agents 2 and 3 cannot directly funnel karma or citations to Broker. All support flows via shared internal state (SQLite) and ecosystem-shaping behavior, not via Koala's citation mechanism.

## 4. Architecture

```
┌────────────────────────────────────────────────────┐
│  Orchestrator — runs 3 agent processes             │
├─────────────────────┬──────────────────────────────┤
│  Market Layer       │  Analysis Layer              │
│  (Broker only)      │  (scoring models per agent)  │
│  bids → posterior   │  paper → prior               │
│  citation selector  │                              │
├─────────────────────┴──────────────────────────────┤
│  Discussion Layer                                  │
│  comment gen + moderation lint + format enforcer   │
├────────────────────────────────────────────────────┤
│  Scheduler — per-paper 72h state machine           │
│  concurrency, retries, idempotent posting          │
├────────────────────────────────────────────────────┤
│  Ingestion — paper stream, PDF parse               │
├────────────────────────────────────────────────────┤
│  Platform — MCP client, auth, karma/strikes probes │
├────────────────────────────────────────────────────┤
│  LLM Router — local (DGX) ↔ frontier (API)         │
│  kill switch for emergency failover                │
├────────────────────────────────────────────────────┤
│  Storage — SQLite: papers, comments, verdicts,     │
│  ecosystem intelligence, trajectory logs           │
└────────────────────────────────────────────────────┘
```

## 5. Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Concurrency | asyncio |
| Storage | SQLite (single file, WAL mode) |
| LLM (bulk) | Local on DGX — Llama 3.3 70B or Qwen2.5-72B via vLLM |
| LLM (frontier) | Claude Sonnet / Opus via Anthropic API |
| LLM router | Thin abstraction; `LLM_MODE=local\|frontier\|auto` env flag; kill switch |
| MCP client | Official MCP SDK; coded against a thin abstraction so real schema can be slotted in at launch |
| PDF parsing | pypdf / pdfplumber for text + layout |
| Deployment | Single DGX node, systemd-managed processes per agent |

## 6. Timeline

> Competition opens **Fri 2026-04-24, 12:00 ET** — <24h from now.

### T-24h → T-0 (today + Fri morning): MVP
- Repo scaffold: `pyproject.toml`, package layout, SQLite schema, logging.
- Platform layer: MCP client abstraction, auth, karma/strikes probes.
- Ingestion: paper stream + PDF parse + local storage.
- Broker v0: naive scoring, naive citation selection (any 5 comments), verdict submission.
- Scheduler v0: 72h per-paper state machine with idempotency + crash recovery.
- LLM router with kill switch.
- **Goal:** From minute one at launch, Broker submits valid verdicts on a small triaged subset.

### Day 1–2 (Fri–Sat): V1
- Scout (Agent 2) online: passive reading, ecosystem intelligence table, silent base-rate prior.
- Marketer (Agent 3) online: active bidding on others' threads, structured format.
- Broker: structured opening-comment generator, weighted Bayesian posterior, entropy-based triage, informativeness+diversity citation selection.
- Trajectory logging verified (required for prizes).

### Day 3–5 (Sat–Mon): V2 — tune the thesis
- Refine Broker's bid-weighting and citation policy based on observed data.
- Watch kill-switch metrics (see §7).
- Tune triage thresholds based on live karma trajectory.

### Day 6–7 (Tue–Wed): Finalize
- Monitor: all verdicts submitted before per-paper 72h clocks close.
- No new code unless kill-switch triggered.
- Export trajectory logs for prize eligibility.

## 7. Falsification Criteria / Kill Switches

Commit automated tripwires upfront — no judgment calls in the moment.

| Condition | Action |
|---|---|
| After 24h: <30% of Broker's opening threads get ≥2 bids | Pivot Broker to pure Social-Reader mode (read others' comments, stop opening own threads) |
| After 48h: Broker verdict distribution indistinguishable from Scout's base-rate | Pivot: elicitation isn't adding signal — same as above |
| Broker karma drops below 20 | Entropy cutoff rises automatically (broker only opens threads on very high-entropy papers) |
| Marketer (Agent 3) after 48h: no correlation between its participation and Broker's thread engagement | Pivot Agent 3 to bid-quality analysis supporting Broker's citation policy |
| Any agent: 2 strikes accumulated | Tighten moderation lint (stricter pre-send filter) |
| Frontier LLM rate limit / cost spike | Flip LLM router kill switch → all-local |

## 8. Open Decisions & Unknowns

**Resolved:**
- Python ✓ / asyncio
- LLM: mix with kill switch (local + frontier) ✓
- SQLite ✓
- Skip repo inspection for MVP ✓
- Single OR ID for all 3 agents ✓

**To resolve at launch (Fri noon):**
- Exact MCP tool schema — platform layer is coded against abstraction; slot in real API on launch.
- Final correlation metric (Pearson / Spearman / AUC) — design scoring to be robust across all three.
- Whether other agents' comments are readable in real-time during 0–48h — **Broker depends on this**. If comments hidden until verdict phase, Broker pivots to Social-Reader-only at launch.
- Paper volume per agent — is there a per-agent cap on verdicts? Affects triage aggressiveness.

**User action required:**
- Register OpenReview ID (user to complete before Friday noon).

## 9. Next Steps

1. Scaffold the Python package (pyproject, layout, SQLite schema, logging, LLM router skeleton, MCP client abstraction).
2. Implement platform layer against abstraction (can test against mock until Friday).
3. Implement ingestion + PDF parse.
4. Implement Broker v0 (MVP path: triage → open thread → verdict with naive citations).
5. Implement scheduler + 72h state machine.
6. Wire trajectory logging.
7. Dry-run end-to-end against mocked MCP.
8. Friday noon: slot in real MCP schema, go live.

Scout + Marketer land during Day 1–2 once Broker is proven live.
