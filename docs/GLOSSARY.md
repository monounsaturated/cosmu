# Cosmu Glossary — Canonical Vocabulary

The single source of truth for product terms. **DB tables, API fields, UI labels, and docs all use these exact words.** If a name here and a name in code/UI disagree, this file wins — fix the other side (ask before a broad rename; see `AGENTS.md`).

## Strategy lifecycle

| Term | One-line definition |
|------|---------------------|
| **Strategy** | The idea / thesis — the economic *why* (e.g. "fade crowded perp funding"). One Strategy, many Versions. |
| **Version** | A parameterized variant of a Strategy — a concrete `StrategySpec` with a fitted `param_space`. What actually gets scored. |
| **Sleeve** | A Version's standardized **$100k paper test**, judged in **net-of-fee %**. Every Version runs the same sleeve so results compare apples-to-apples. |
| **Wallet** | The single pooled paper account that all live Sleeves share. |
| **Allocation** | A Version's share of the Wallet — how much of the pool its Sleeve currently controls. |

## Stages (where a Strategy lives)

| Term | One-line definition |
|------|---------------------|
| **Lab** | Discovery. The research brain + **Strategy Finder** + the config library author and screen Versions before any paper money. |
| **Paper** | The Wallet validation stage — Sleeves trade simulated funds 24/7 to earn (or lose) Allocation. |
| **Live** | Real money. Off by default; only gate-passing Versions promote, and only when the live toggle is armed. |

## Judging

| Term | One-line definition |
|------|---------------------|
| **Score** | **Deflated Sharpe** — the one ranking scalar. Everything sorts by this so no metric can be cherry-picked. |
| **Gate** | The deterministic pass/fail bar (min-trades, max-drawdown, untouched holdout, multiple-testing correction). A Version must clear the Gate even to be ranked. The Gate decides what gets *money*, never what gets *tried*. |
| **Profit factor** | A **displayed** secondary metric (gross wins / gross losses). Shown for context; ranking stays **Score** (deflated Sharpe). |

## Money state

| Term | One-line definition |
|------|---------------------|
| **Paper** | Simulated funds, no real money. |
| **Live** | Real money, off until armed via the live toggle. |

> There is **no "demo" state** in the product. When there is no engine or no data, show an honest **empty / connect** state — never fabricated numbers.

## Authoring

| Term | One-line definition |
|------|---------------------|
| **StrategySpec** | The typed hypothesis contract a Version is authored as (`apps/engine/cosmu/strategy/spec.py`): universe, horizon, catalyst, entry/exit *structure* over named features, risk rules, and a `param_space`. **No magic numbers** — thresholds live in `param_space` and are fit from data. |
| **Feature** | A named, point-in-time data signal from the **feature registry** (`apps/engine/cosmu/config/feature_registry.py`). Specs reference features by name only. |
| **Composable module** | A reusable, named entry/exit building block (e.g. `multi_tp`, `break_even+runner`, `ma_trend_filter`, `orb`, `fvg_retest`/`fvg_multiple`) that a Version declares instead of re-deriving structure. See the create-strategy skill. |
| **Inbox** | `strategies/inbox/` — drop a `*.md` / `*.pine` / `*.json` strategy file here; it is scanned on deploy/boot, parsed to a `StrategySpec`, and flows through `static_check → Lab → Finder → Gate`. |
