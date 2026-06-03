# Cosmu Glossary — Canonical Vocabulary

The single source of truth for product terms. **DB tables, API fields, UI labels, and docs all use these exact words.** If a name here and a name in code/UI disagree, this file wins — fix the other side (ask before a broad rename; see `AGENTS.md`).

> **The lifecycle is LOCKED:** **Lab → Strategies → Forward-test → Live.** There is **NO pooled wallet** — each survivor proves itself on its **own standalone track**. The dead words **"Paper"** (as a stage) and **"Incubate"** must not reappear.

## Strategy lifecycle

| Term | One-line definition |
|------|---------------------|
| **Strategy** | The idea / thesis — the economic *why* (e.g. "fade crowded perp funding"). One Strategy, many Versions. |
| **Version** | A parameterized variant of a Strategy — a concrete `StrategySpec` with a fitted `param_space`. What actually gets scored. |
| **Track** | A Version's **standalone** $100k SIM forward-test, judged in **net-of-fee %**. Each Version runs its **own** track — there is no shared pool and no cross-strategy allocation. Every track uses the same standardized size so results compare apples-to-apples. |
| **Aggregate read-out** | The Σ of all standalone Tracks, shown on the Overview ("are we making money?"). A pure read-out — **not** an account you trade from, and **not** a pooled wallet. |

## Stages (where a Strategy lives)

| Term | One-line definition |
|------|---------------------|
| **Lab** | Discovery. The research brain + **Strategy Finder** + the config-library author screen Versions before any SIM money. |
| **Strategies** | The screened pipeline — Versions that cleared the screen, grouped by stage. |
| **Forward-test** | The validation stage — each proven Version trades on its **own standalone Track** in SIM 24/7. A **≥ N=30 forward-day** net-of-fee proof is the **recommended** live-readiness signal (surfaced, advisory — the operator decides when to launch; the 5 interlocks are the hard gate). (This stage was formerly mislabelled "Paper".) |
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
| **SIM** | Simulated money, no real funds. The badge shown next to every figure in Forward-test. |
| **LIVE** | Real capital, off until armed via the live toggle. |

> There is **no "demo"** and **no "paper"** money state in the product. When there is no engine or no data, show an honest **empty / connect** state — never fabricated numbers.

## The Mind (agentic reasoning)

The agent's standardized self-knowledge, surfaced on the **Mind** page (`/mind`) and the `GET /mind` endpoint. A **reasoning surface only** — it never funds or fires. The deterministic **Gate** alone disposes of money.

| Term | One-line definition |
|------|---------------------|
| **Mind** | The single surface answering, in one vocabulary, **what the agent knows** (its data sources + freshness), **how it thinks** (the analyst panel), and **what it has learned** (memory, the ML survival model, regime coverage, gate efficiency). |
| **Analyst panel** | A team of perspectives — **Technical · Macro · Sentiment · Social & News · Positioning · OSINT** (market) plus **ML survival · Memory** (process) — each reading one family of the agent's existing point-in-time signals. ML is *a* pillar, not the whole story. |
| **Stance** | One perspective's standardized read: a **lean** (bullish · bearish · neutral · **abstain**), a **conviction** (0–1), a headline and the evidence. A perspective with no ingested data **abstains** — it never fabricates a read. |
| **Consensus** | The weighted directional vote of the **market** analysts. **Conviction** = how strongly the agreeing analysts feel; **Agreement** = how dominant the consensus is over the panel (low agreement = a **contested** read). |
| **Reflection** | A point-in-time record of the panel's debate (`mind_reflections`, additive table), written each autonomous tick so the agent accrues a memory of *how it thought* over time. |
| **Railguard** | The hard rule shown wherever the Mind appears: *it reasons; it never funds or fires an order.* An LLM may narrate a reflection, but **never** in any scoring/gate/money path. |

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
| Forward-test stage value (`strategy_versions.status`) | `forward_test` | `paper`, `incubate` |
| Money-state / sim venue label | `sim` | `paper` |
| Per-strategy unit (class · table) | `Track` · `tracks` | `Sleeve` · `sleeves` |
| Aggregate snapshot scope | `aggregate` | `pool` |
| Per-track snapshot scope | `track` | `sleeve` |
| Overview endpoint · model | `GET /overview` · `OverviewResponse` | `/portfolio` · `PortfolioResponse` |
| Funding entrypoint | `fund_tracks_from_survivors` | `fund_wallet_from_survivors` |
| Portfolio of record (class) | `Portfolio` | `PaperPortfolio` |
| Pooled cross-strategy allocator | *(removed)* | `rotate` / `Allocation` / capped-Kelly pool sizing |
