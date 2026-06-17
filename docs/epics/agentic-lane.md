# Epic — Agentic / discretionary strategy lane (DESIGN-FIRST)

> Status: **DESIGN — operator-validated direction (2026-06-17).** No code that touches real
> money lands until this doc is approved. Gate A (the statistical FDR gate) is **LOCKED and
> untouched** by everything here.

## 0. Why
The deterministic FDR Gate (Gate A) is the right judge for **systematic** strategies (typed
`StrategySpec`, ML, backtest) — it rejects luck-that-looks-like-skill before real money moves.
But it is too rigid for **LLM-intuition / agentic / natural-language** strategies that reason over
multi-format data (tweets, news, on-chain, filings). The answer is **not to loosen Gate A** — it is
to add **lanes** where the required proof scales with the capital at risk.

## 1. Principles (operator-validated)
1. **Proof ∝ capital.** The strictness of the gate scales with money at risk. Zero-capital lanes need
   no gate.
2. **The Gate decides FUNDING / ELIGIBILITY, not EXISTENCE.** A strategy that fails the gate is not
   deleted — it runs in a `$0` lane, measured forward on real data. The gate kills *funding*, not the *idea*.
3. **Live = manual human approval for ALL strategies (for now).** Gate A and Gate B both produce only
   **eligibility + signals**; the operator clicks "launch". This matches the existing invariant
   (`gate = eligibility, human clicks launch`).
4. **LLM proposes, deterministic disposes.** The LLM/agent reasons and proposes a decision; a
   deterministic path (admission check → risk gauntlet → sizing → order path) decides, sizes, and fires.
   The LLM is **never** on the trigger and **never** defines its own success metric.

## 2. Two eligibility gates (not "gate yes/no")
| | **Gate A — statistical (existing, LOCKED)** | **Gate B — admission / credibility (new)** |
|---|---|---|
| For | systematic `StrategySpec` / ML / backtest | agentic / NL / discretionary strategies |
| Bar | DSR≥0.95, PBO≤0.50, BH-FDR q=0.10, holdout, net of fees | **pre-registered** event-study/SCAR (`research/event_study.py`) **or** voice Brier-skill (`voices_pass`) **AND** a forward **paper track record** (net-positive, ≥N days / ≥M fills) |
| Produces | eligibility for the funded systematic lane | eligibility for **manual** live launch |
| Volume-proof | BH-FDR across the cohort | pre-registration of the credibility check |

Both gates feed **one** eligibility view. Neither auto-arms real money — the **human launches**.

## 3. Lane ladder (proof ∝ capital)
| Lane | Money | Gate | For |
|---|---|---|---|
| Explore / Research | `$0` | none — runs + forward-measured | LLM intuition, NL ideas, risky hypotheses, multi-format data |
| Rejects-watch | `$0` | gate-failed-but-OOS-strong → watched | measuring Gate A Type-II |
| Paper | SIM | Gate A | the proven systematic edge |
| Live systematic | REAL | Gate A + 5 interlocks + **manual launch** | the autonomous money machine |
| **Live discretionary (NEW)** | REAL, hard-capped | Gate B + interlocks + **manual launch** | the agentic / NL "agent trader" |

## 4. Unified per-strategy caps (operator-validated)
**ONE** caps system across **ALL** strategies (agentic *and* Quant/Gate-A), managed in Settings and
shown on the front:
- **Global total** live cap (across all strategies).
- **Per-strategy default** cap.
- **Per-strategy editable** cap — visible and simply editable on the front.

Enforced in the order gauntlet for every strategy. Builds on the operator live caps already shipped
(#260: `global_live_max_notional`, `per_strategy_live_max_notional` in `master/risk.py` /
`master/execution.py`). The new work is: make the per-strategy cap first-class + editable in the web
Settings, unified for agentic and systematic alike.

## 5. The agent-strategy artifact + visible process
- New `origin='agent'`: a **reasoning loop** (the Mind panel — Technical · Macro · Sentiment · Social ·
  Positioning · OSINT) → typed `Decision{symbol, side, confidence, SL, TP, size_request, rationale, trace}`.
- A **paper twin** always runs alongside a live agent strategy (SIM↔live variance attribution).
- Authored / run as a **small cohort via Claude Code compute** (flat sub, local) — **not** a paid LLM API
  (see memory `llm_creation_via_claude_code`).
- Multi-format data = the already-wired free + xAI sources.
- **Visible process (the "see the steps" requirement):** persist each agent run trace (steps · analyst
  views · tools called · data read · debate · consensus · admission evidence · fill) → `research_notes`
  kind=`agent_run` (or a dedicated table) + a web "run replay" view. Inspiration: TradingAgents
  (multi-agent debate — the Mind's basis); agent-graph trace UIs.
- Reuses what already exists: `cosmu/mind/` (the panel), the `explore` lane, the multi-lane intake plan
  (`origin` ML | Prompt | Index | **agent**), the rejects-watch lane.

## 6. Safety / interlocks (≥ the standard 5)
- A `discretionary` lane flag (off by default) + the unified caps + kill-switch + venue key-gating +
  **manual human launch**. Any one missing ⇒ SIM fill, no real order.
- Memoryless sizing (no martingale/revenge), SL/TP required (`master/sizing.py`).
- Auto-disarm on the daily-loss cap and on edge decay (`master/drift.py`).
- Every decision + fill audited with the admitting evidence recorded.

## 7. Build sequence (after this doc is approved)
1. **Unified per-strategy caps** — model + Settings/front editing (surface #260 caps, make per-strat editable, applies to all lanes).
2. **Gate B admission module** — `event_study` + voice-skill + paper-record → an eligibility signal on the leaderboard.
3. **Agent-strategy artifact** — `origin='agent'`, the Mind→`Decision`, paper twin, trace persistence.
4. **Trace web view** — the run-replay surface.
5. **First cohort** — tweets→coins (NL event-study) + a generalist Mind-panel spot agent + others, Binance-spot, run via Claude Code.

Throughout: live launch stays a **manual human click**; the LLM is **never** on the trigger; **Gate A is untouched**.

## 8. Open / to tune
- Exact Gate-B paper-record thresholds (N days, M fills). Suggested start: ≥14 paper days + ≥10 real
  fills, net-positive after fees — operator-tunable in Settings.
- Whether to later allow auto-launch within caps once trust is established (currently: **manual for all**).
