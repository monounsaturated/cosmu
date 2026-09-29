# Phase-0 Non-Price Data-Blocked Sources — Coverage + Gate Verdict (P0.8)

> **The pivot after price/funding was falsified.** Spot price- and funding-based signals are
> well-powered FAILs (`phase0-carry-verdict.md`, `phase0-funding-crowding-verdict.md`). This report
> turns to the operator's claimed real edge: **non-price signals that are currently DATA-BLOCKED** —
> (1) cross-market transfer, (2) Polymarket positioning, (3) social-authority / insider. For each we
> ran the **profile-source data-trust audit FIRST** (PIT / look-ahead / revision — the same scrutiny
> that made CrowdIntel a NO-GO), attempted a backfill via **manage-data**, authored a typed
> `StrategySpec`, and routed the gateable one through the **EXISTING deterministic Gate**. No
> threshold was changed; no PASS was manufactured.

Status legend: **PASS** · **FAIL (STOP)** · **DATA-BLOCKED** (honest abstention — no PIT history to gate).

---

## 0. TL;DR — honest verdict per source

| Source | Data state after backfill | profile-source | Gate verdict |
|---|---|---|---|
| **Cross-market transfer** | **UNBLOCKED** — 7 series × ~1000 PIT daily rows, ~4 yr, 0 look-ahead | **REVIEW** (only weekend/holiday calendar gaps; PIT-honest) | **FAIL (STOP)** — 0/48 grid variants pass; every variant's holdout deflated-Sharpe is **negative** |
| **Polymarket positioning** | **DATA-BLOCKED** — 0–5 live-snapshot rows, span < 1 day; no history endpoint | REVIEW-too-shallow → effectively NO-GO | **DATA-BLOCKED** — spec joins 0 PIT rows → 0 trades; cannot gate |
| **Social-authority / insider** | **DATA-BLOCKED** — key-gated feeds return 0 rows; keyless proxies snapshot-thin | NO-GO (no data) | **DATA-BLOCKED** — spec joins 0 PIT rows → 0 trades; cannot gate |

**One source was genuinely unblockable for free (cross-market, via the Yahoo daily alternate) and it
was tested honestly — it does not carry an exploitable edge. The other two remain blocked by the data
layer itself (no free history endpoint / paid-key-gated), so they are queued, not gated.**

---

## 1. Pre-registered criteria (untouched Gate)

The Gate's statistical thresholds are the existing, untouched `GateSettings` / scorer
(`min_trades=30`, `min_deflated_sharpe_prob=0.95`, `max_cscv_pbo=0.50`, `regimes_positive ≥ 2`,
`max_drawdown=0.25`, `must_beat_buy_and_hold`, untouched one-shot holdout) **and** the cohort BH-FDR
at **q = 0.10**. **None changed.** The profile-source audit thresholds (`coverage_depth ≥ 60 rows /
≥ 30 d`, `gaps ≤ 10%`, `look_ahead` hard-stop on `available_at < ts`, `pit_lag` hard-stop) are also
the existing defaults.

- **PASS** — a spec clears all five Gate criteria AND survives the cohort FDR.
- **FAIL (STOP)** — no variant clears after a fully-powered run.
- **DATA-BLOCKED** — the PIT store holds no usable history for the feature, so the backtest joins
  `None` and the conditions cannot fire (0 trades). The honest outcome is *abstain*, never a
  fabricated read.

---

## 2. Source profiling + backfill (manage-data → profile-source)

profile-source was run against the **same point-in-time store the Gate reads** (`PgAltDataStore`
over Supabase), so the audit reflects exactly what the backtest would see — not a throwaway local
JSONL. `provider` is the store-bucket routing key; `MARKET` = market-wide; declared lag = the
source's release semantics.

### 2a. Cross-market transfer — UNBLOCKED, REVIEW

The wired source (`cosmu/data/sources/multiasset.py`) defaulted to **Stooq**, whose free CSV
endpoint now demands a captcha-gated `apikey` (it returns `"Get your apikey…"` instead of data → the
provider degrades to `[]`). The documented drop-in **`YahooDailyProvider`** is keyless and returns
full daily history; the default factory was switched to it (5 yr range). The PIT contract is
identical (daily close finalized after the session → `available_at = ts + 1 day`, a conservative
floor — never look-ahead).

`manage-data fetch multiasset` → **7000 PIT points** ingested. profile-source (declared lag 24 h):

| metric | rows | span (d) | look-ahead viol. | verdict |
|---|---|---|---|---|
| gold_xau | 1000 | 1452 | 0 | REVIEW |
| silver_xag | 1000 | 1452 | 0 | REVIEW |
| wti_crude | 1000 | 1452 | 0 | REVIEW |
| spx_index | 1000 | 1456 | 0 | REVIEW |
| ndx_index | 1000 | 1456 | 0 | REVIEW |
| eurusd | 1000 | 1405 | 0 | REVIEW |
| usdjpy | 1000 | 1405 | 0 | REVIEW |

The only failed check is the soft `gaps` one — daily market series are closed on weekends/holidays,
which trips the >10% missing-bucket test against a calendar-day grid. This is a **consciously
accepted REVIEW** (weekends are not real gaps for a market feed); no hard check (look-ahead, PIT-lag)
fails. **Deep, fresh, PIT-honest — safe to gate.**

### 2b. Polymarket positioning — DATA-BLOCKED

`manage-data fetch polymarket_clob` only writes what the CLOB returns *now* — a **live order-book
snapshot**, not history. There is no positioning-history endpoint, so the store holds only what has
accumulated from prior ingest ticks:

| metric | rows | span (d) | verdict |
|---|---|---|---|
| pm_implied_prob | 4 | 0.2 | REVIEW (too shallow — < 60 rows) |
| pm_book_depth | 4 | 0.2 | REVIEW (too shallow) |
| risk_on (pm) | 5 | 3.3 | REVIEW (too shallow) |
| pm_prob_velocity | 0 | 0.0 | **NO-GO** (no data) |
| pm_risk_on | 0 | 0.0 | **NO-GO** (no data) |

A handful of same-day snapshots cannot span a regime or produce ≥ 30 trades. **DATA-BLOCKED** until a
continuous CLOB-snapshot backfill has run for weeks/months. (This is the *correct* discipline: the
CLOB midpoint is a forward read; back-dating it to the event date would manufacture look-ahead,
exactly the CrowdIntel failure mode.)

### 2c. Social-authority / insider — DATA-BLOCKED

The authority-sentiment feeds are **key-gated** and the keyless proxies are snapshot-thin:

| metric | source | rows | verdict |
|---|---|---|---|
| twitter_sentiment | xai | 0 | **NO-GO** (key-gated / empty) |
| twitter_influencer_sentiment | xai | 0 | **NO-GO** (key-gated / empty) |
| social_volume / social_sentiment / galaxy_score | lunarcrush | 0 | **NO-GO** (needs LUNARCRUSH_API_KEY) |
| reddit_sentiment | reddit | 0 | **NO-GO** (no history) |
| osint_air_activity | opensky | 4 | REVIEW (too shallow) |

No point-in-time history exists for the high-authority signal. **DATA-BLOCKED** until either a paid
key is funded (xAI / LunarCrush) or a continuous keyless-proxy backfill accumulates.

---

## 3. The Gate — cross-market transfer (the only gateable source)

**Spec:** `apps/engine/strategies/inbox/cross-market-dollar-weak-momentum.json` —
*dollar-weakness-gated crypto momentum*. The dollar is the canonical cross-market transfer channel
into crypto (weak USD → looser global conditions → risk-on). Entry: crypto medium-term momentum
`ret_Nd > mom_floor` **and** `eurusd > usd_weak_floor` (dollar weak). Exit: stop / take-profit /
time-stop + a disconfirmer `eurusd cross_down usd_exit` (dollar re-strengthens → stand aside). No
magic numbers — every threshold is a fitted `param`.

**Run (deterministic, real data):** 5-symbol Binance-spot universe (BTC/ETH/BNB/SOL/…), 1000 daily
bars each; the **EUR/USD PIT series joins to all 1000 bars per symbol** (full coverage — the
cross-market data is wired and aligning as-of with no look-ahead). The spec's coarse Finder grid
(`build_grid`, 48 variants) was screened on the real bars + alt join through the existing
`run_strategy_backtest` + deterministic `score()` — the same scorer the Modal cohort sweep uses.

**Result: 0 / 48 variants pass the Gate.**

| | passed | OOS ret | holdout DSR | trades | PF |
|---|---|---|---|---|---|
| best holdout variant | ✗ | +2.85% | **−0.371** | 569 | 1.07 |
| highest-PF variant | ✗ | +4.92% | **−0.456** | 33 | 4.16 |
| midpoint variant | ✗ | +9.35% | **−0.499** | 167 | 1.58 |
| worst holdout | ✗ | — | **−0.500** | — | — |

Several variants are profitable **in-sample** (PF up to 4.16, OOS leg up to +12.8%), but **every
single variant's one-shot holdout deflated-Sharpe is negative** (−0.37 … −0.50) and the midpoint's
deflated-Sharpe probability is 0.62 (< 0.95 bar). The cross-market regime gate is an in-sample
artifact that **reverses out-of-sample** — a well-powered **FAIL (STOP)**. Since 0 variants clear
even the per-candidate gate, the cohort BH-FDR (which only tightens) cannot rescue it.

This mirrors the carry / funding-crowding verdicts: a plausible non-price thesis, tested honestly on
real PIT data, **does not survive cost + out-of-sample discipline.**

### Modal cohort sweep (offloaded) — and a prod bug it surfaced

The three specs were dropped in `apps/engine/strategies/inbox/` and the cohort sweep was offloaded to
Modal (`pnpm modal:gate` → `cosmu.master.scheduler`, image built from this branch's engine source so
the Yahoo fix is included). The **first** run failed at DB connect:
`database "postgres# Supabase Postgres connection" does not exist` — `scripts/sync_modal_secret.py`
was pushing the **inline `# comment`** from the `.env.local` `DATABASE_URL` line into the secret, so
**every Modal job was broken**. Local pydantic-settings strips that comment (which is why the local
gate ran fine), masking the bug. Fixed here (`_parse_env` now ends an unquoted value at its first
` #`, matching python-dotenv); the re-synced secret parses to a clean `…/postgres?pgbouncer=true`.

The **local deterministic per-candidate sweep above is the binding verdict** (same scorer Modal uses)
— cross-market STOPs, and the two data-blocked specs join 0 PIT rows on the same shared Supabase, so
they are un-gateable on Modal too.

**Secret fix confirmed end-to-end (re-run):** with the corrected `_parse_env`, `pnpm modal:gate`
connects to Supabase with **zero** `database "…" does not exist` errors (previously every job died at
DB connect) and proceeds into the scheduler's ingest/gate cycle on bigger compute. (One unrelated
note surfaced: `ingest source funding_rate failed … HTTP Error 451` — Binance geo-blocks Modal's
egress IPs; a pre-existing region issue independent of this work, tracked separately.) This cannot
overturn a 0/48 per-candidate STOP; it confirms the Modal lane is unblocked again.

---

## 4. What changed / next actions

- **Provider fix (real unblock):** `multiasset` default Stooq → `YahooDailyProvider` (Stooq's free
  path is dead). Cross-market is now a live, PIT-honest feed everywhere (local + Modal) — it was 0
  rows before. This is reusable infra regardless of this spec's STOP.
- **Cross-market:** the dollar-channel framing FAILs. Before retrying, the honest blocker is *signal
  construction*, not data: the backtest reads alt features as **raw point-in-time levels**, so an
  absolute EUR/USD gate overfits the sample regime. A fair retest needs a **stationary** cross-market
  transform (expanding z-score / change), which today only the ML panel computes — wiring multiasset
  into the cross-asset ablation's feature set (`research/gate.py:_xa_features`) is the clean next
  step, not another level-gated spec.
- **Polymarket & social:** genuinely DATA-BLOCKED. The only way forward is **time** (accumulate CLOB
  snapshots tick-by-tick) or **money** (fund xAI / LunarCrush keys). Both specs are authored and
  queued; they begin to fire the moment real PIT history exists, and the Gate judges them then.

**No threshold was changed. No PASS was manufactured. One source was unblocked and honestly failed;
two remain blocked by the data layer and were not gated.**
