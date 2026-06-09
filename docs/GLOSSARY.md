# Cosmu Glossary — Canonical Vocabulary

The single source of truth for product terms. **DB tables, API fields, UI labels, and docs all use these exact words.** If a name here and a name in code/UI disagree, this file wins — fix the other side (ask before a broad rename; see `AGENTS.md`).

> **The lifecycle is LOCKED:** **Backtest → Simulation → Live.** There is **NO pooled wallet** — each survivor proves itself on its **own standalone track**. The dead words **"Paper"** (as a stage/label), **"Forward-test"** (as a user-facing stage name), and **"Incubate"** must not reappear in new UI/labels. (Code symbols `forward_test` / `is_paper` may remain as internal identifiers until fully migrated.)

## Strategy lifecycle

| Term | One-line definition |
|------|---------------------|
| **Strategy** | The idea / thesis — the economic *why* (e.g. "fade crowded perp funding"). One Strategy, many Versions. |
| **Version** | A parameterized variant of a Strategy — a concrete `StrategySpec` with a fitted `param_space`. What actually gets scored. |
| **Track** | A Version's **standalone** SIM forward-test (default **$1,000** — a single adjustable setting `sim_track_capital`), judged in **net-of-fee %**. Each Version runs its **own** track — there is no shared pool and no cross-strategy allocation. Every track uses the same standardized size so results compare apples-to-apples. |
| **Aggregate read-out** | The Σ of all standalone Tracks, shown on the Overview ("are we making money?"). A pure read-out — **not** an account you trade from, and **not** a pooled wallet. |

## Stages (where a Strategy lives)

| Term | One-line definition |
|------|---------------------|
| **Backtest** | Discovery + screening. The research brain, Strategy Finder, and the Gate run Walk-Forward OOS + holdout on historical data — no real money, no live prices. Formerly called "Lab". |
| **Simulation** | Validation on live data. Each gate-passed Version gets its own standalone SIM track (default **$1,000**, `sim_track_capital`). The daily clock first **EXECUTES** each gate-lane track's own spec/params on the latest real bars — its stop / take / time-stop / signal-exit closes the position, its entry signal re-enters (`orchestrator/forward_step.py`, sim fills with real fees + slippage) — then **marks** every held position to the real close. Deploy-lane rotation arms rotate via their own arm modules (stale legs close first). A **≥ 30 forward-day net-of-fee proof** is the recommended live-readiness signal (advisory — the operator decides; the 5 interlocks are the hard gate). Formerly called "Forward-test" and (earlier) "Paper". |
| **Live** | Real money. Off by default; only gate-passing Versions promote, and only when the live toggle is armed. Live bots are launched manually with dedicated capital (1-button + confirm). |

## Judging

| Term | One-line definition |
|------|---------------------|
| **Score** | **Deflated Sharpe** — the one ranking scalar. Everything sorts by this so no metric can be cherry-picked. |
| **Gate** | The deterministic pass/fail bar (min-trades, max-drawdown, untouched holdout) **plus** a cohort-level **Benjamini-Hochberg FDR** correction — a Version must clear the per-candidate stats AND survive false-discovery control across its whole cohort before it can be funded, so authoring more candidates per tick can't manufacture a winner. The Gate decides what gets *money*, never what gets *tried*. **Deterministic, out of any LLM path.** |
| **Profit factor** | A **displayed** secondary metric (gross wins / gross losses). Shown for context; ranking stays **Score** (deflated Sharpe). |

## Money state

| Term | One-line definition |
|------|---------------------|
| **SIM** | Simulated money, no real funds. The badge shown next to every figure in **Simulation**. |
| **LIVE** | Real capital, off until armed via the live toggle. |

> There is **no "demo"** and **no "paper"** money state in the product. When there is no engine or no data, show an honest **empty / connect** state — never fabricated numbers.

## The Mind (agentic reasoning)

The agent's standardized self-knowledge, surfaced on the **Mind** page (`/mind`) and the `GET /mind` endpoint. A **reasoning surface only** — it never funds or fires. The deterministic **Gate** alone disposes of money.

| Term | One-line definition |
|------|---------------------|
| **Mind** | The single surface answering, in one vocabulary, **what the agent knows** (its data sources + freshness), **how it thinks** (the analyst panel), and **what it has learned** (memory, the ML survival model, regime coverage, gate efficiency). |
| **Analyst panel** | A team of perspectives — **Technical · Macro · Sentiment · Social & News · Positioning · OSINT** (market) plus **ML survival · Memory** (process) — each reading one family of the agent's existing point-in-time signals. ML is *a* pillar, not the whole story. |
| **Stance** | One perspective's standardized read: a **lean** (bullish · bearish · neutral · **abstain**), a **conviction**/confidence (0–1), a signed **score** (-1..1), a headline and the evidence. A perspective with no ingested data **abstains** — it never fabricates a read. Carries its verdict **source**: `heuristic` (deterministic), `llm` (a rubric-scored judge verdict), or `abstain`. |
| **Rubric** | How one **market** pillar is scored (`cosmu/mind/rubric.py`): its trading **prior**, the **criteria** it weighs, and what a positive vs negative **score** means. Pure description — it steers the LLM judge's prompt and nothing else. |
| **Verdict** | The typed, instructor-style structured output an **LLM judge** returns for one pillar: `{lean, score, confidence, rationale}` (Pydantic, `extra="forbid"` — no smuggled fields/thresholds). The model **scores**; it may not abstain (a no-data abstain is decided in Python before any judge runs) and it never funds. |
| **LLM-as-judge** | The Mind's **opt-in** committee (`MIND_JUDGE_ENABLED`, off by default): when on + an LLM key, each pillar *with data* is rubric-scored by the model. **LLM-optional & offline** — no key / invalid output falls back to the deterministic heuristic, so the Mind is identical with the judge off. |
| **Consensus** | The weighted directional vote of the **market** analysts — a **deterministic** aggregation of the per-pillar verdicts (`sum(source_weight × confidence)` per lean, argmax with a fixed tie-break). **Conviction** = how strongly the agreeing analysts feel; **Agreement** = how dominant the consensus is over the panel (low agreement = a **contested** read). *The LLM scores; the math combines; the gate disposes.* |
| **Consensus audit** | The aggregation laid bare (`consensus_audit`): the rule, the per-lean tally, and the per-pillar contributions that sum to it — so the committee's vote is replayable. No LLM, no money on this path. |
| **Reflection** | A point-in-time record of the panel's debate (`mind_reflections`, additive table), written each autonomous tick so the agent accrues a memory of *how it thought* over time. |
| **Railguard** | The hard rule shown wherever the Mind appears: *it reasons; it never funds or fires an order.* An LLM may **score** a pillar or narrate a reflection, but **never** in any scoring/**gate**/money path — the deterministic gate alone disposes. |

## Authoring

| Term | One-line definition |
|------|---------------------|
| **StrategySpec** | The typed hypothesis contract a Version is authored as (`apps/engine/cosmu/strategy/spec.py`): universe, horizon, catalyst, entry/exit *structure* over named features, risk rules, and a `param_space`. **No magic numbers** — thresholds live in `param_space` and are fit from data. |
| **Feature** | A named, point-in-time data signal from the **feature registry** (`apps/engine/cosmu/config/feature_registry.py`). Specs reference features by name only. |
| **Composable module** | A reusable, named entry/exit building block (e.g. `multi_tp`, `break_even+runner`, `ma_trend_filter`, `orb`, `fvg_retest`/`fvg_multiple`) that a Version declares instead of re-deriving structure. See the create-strategy skill. |
| **Inbox** | `apps/engine/strategies/inbox/` — drop a `*.md` / `*.pine` / `*.json` strategy file here; it is scanned on deploy/boot, parsed to a `StrategySpec`, and flows through `static_check → Lab → Finder → Gate`. |

## Canonical identifiers (code ↔ DB ↔ API)

These exact spellings are enforced; the dead spellings on the right must not return.

| Concept | Canonical | Dead (do not use) |
|---------|-----------|-------------------|
| UI stage label — discovery/screening | **Backtest** | `Lab`, `Farm`, `Research` (as a stage name) |
| UI stage label — live-data validation | **Simulation** | `Forward-test`, `Paper`, `SIM` (as a stage label) |
| Code status value (`strategy_versions.status`) | `forward_test` (internal, pending rename) | `paper`, `incubate` |
| Money-state / sim venue label | `sim` | `paper` |
| Heavy compute vendor | **Modal** | `Fly.io`, `Render` (worker) |
| Per-strategy unit (class · table) | `Track` · `tracks` | `Sleeve` · `sleeves` |
| Aggregate snapshot scope | `aggregate` | `pool` |
| Per-track snapshot scope | `track` | `sleeve` |
| Overview endpoint · model | `GET /overview` · `OverviewResponse` | `/portfolio` · `PortfolioResponse` |
| Funding entrypoint | `fund_tracks_from_survivors` | `fund_wallet_from_survivors` |
| Portfolio of record (class) | `Portfolio` | `PaperPortfolio` |
| Pooled cross-strategy allocator | *(removed)* | `rotate` / `Allocation` / capped-Kelly pool sizing |
