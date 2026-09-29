# Polymarket odds — data-trust scout (gate-ready research source)

**Date:** 2026-06-25 · **Lens:** `profile-source` (coverage · PIT-honesty · revision-safety · resolution-join · min-trades) · **Mode:** READ-ONLY (one report doc, no code changes)

**Mission tie-in:** the epics audit (`docs/reports/epics-backlog-audit-2026-06-25.md` §5) calls this "the cleanest shot at a first forward survivor from the axis the giants ignore." This scout de-risks **edge-option-2** so it is READY the moment the operator picks it.

---

## Verdict: **REVIEW** (GO-on-three-fixes)

The plumbing is **real and PIT-correct in shape**, but Polymarket odds is **NOT yet a gate-ready research source** for trading the prediction contract itself. Three concrete, code-verified gaps stand between today and a defensible first forward survivor. None is a rewrite; all are wiring. After the three fixes below it is a **GO**.

The data-trust lens lands as:

| dimension | status | one-line |
|---|---|---|
| Coverage | ⚠️ thin-but-extensible | top-~30 liquid OPEN markets, 180–400 daily rows each; per-market series **defined but never ingested in prod** |
| Granularity | ❌ **daily only** | every fetch path hardcodes `fidelity=1440` → ~1 trade/market → the per-cell min-trades Gate **correctly refuses it** |
| PIT-honesty | ⚠️ **structurally honest, one baked-in caveat** | `read_asof(available_at <= as_of)` is correct + revision-safe; BUT `available_at == ts` in BOTH fetch paths = a 1-bucket look-ahead on the entry bar |
| Revision safety | ✅ | append-only, `ON CONFLICT DO NOTHING`, last-write-wins per ts; CLOB midpoints are revision-free |
| Resolution join (UMA) | ❌ **MISSING in the research path** | `payoutNumerators` lives ONLY in the exec adapter; the backtest trades odds-drift with `tp/stop/time_stop`, never the authoritative resolved outcome |
| Min-trades Gate | ✅ working-as-designed | daily odds is correctly rejected; the fix is hourly bars, NOT loosening the Gate |

---

## What I verified (file-by-file, code-level)

### 1. Two ingest lanes exist — one populated, one orphaned

- **MACRO aggregate lane** (`PolymarketClobSource`, `data/sources/polymarket.py`; `PolymarketClobProvider`, `data/providers/prediction.py`): three composite market-wide series `pm_implied_prob / pm_prob_velocity / pm_book_depth`, stored under `symbol="MARKET"`. Wired into `feature_registry.py:282-284`, `ingest/catalog.py:140,546`, and **actually scheduled** — the hourly Modal `ingest` cron (`remote/app.py:147`) → `cosmu.research.loop --ingest` → `ingest/run.py::run_once` (`run.py:409`). These are **crypto FEATURES** (used by `polymarket-prob-velocity-belief-shock-momentum.json` etc. to trade `binance/crypto`), not the prediction-contract lane.

- **PER-MARKET odds lane** (`PerMarketOddsSource.fetch_odds`, `data/sources/polymarket.py:229-298`; `ingest/polymarket_odds.py::ingest_per_market_odds`): the per-conditionId `(provider="polymarket", symbol=conditionId, metric="odds")` series — the one the **gate-ready prediction lane** reads via `PredictionDataAdapter` (`adapters/data/prediction.py`) and `finder.py::_prediction_bars` (line 357). This is the lane `g2-prediction-prob-overextension-fade-short.json` (`asset_classes:["prediction"]`) trades directly.

  **⚠️ FINDING: `ingest_per_market_odds` is never called by any scheduled job or script.** Grep across `cosmu/` + `scripts/` + `remote/app.py` finds it defined, unit-tested (`tests/test_polymarket_per_market_odds.py`), and read by the finder — but **no cron, no run entrypoint, no Modal function populates it.** In prod, `alt_data` has **zero** `(polymarket, <conditionId>, odds)` rows, so the prediction-contract finder branch (`finder.py:434`) screens **no markets**. The lane is wired end-to-end but **starved of data**.

### 2. PIT-honesty — structurally correct, with one known baked-in look-ahead

- The look-ahead guard is real and lives in the store, not the source: `read_asof` (`data/providers/store.py:45-59`, `:126` for Postgres) returns, per `ts`, the latest-revised row with `available_at <= as_of`, ordered by ts. Revisions append; a later-available revision never rewrites an earlier as-of read. This is the correct PIT contract and it is **shared** with every other alt source (not bespoke), so the CrowdIntel "score recomputed at resolution" trap is **structurally prevented** — provided `available_at` is honest.

- **The caveat (load-bearing):** both fetch paths stamp `available_at = ts` (`polymarket.py:144`, `:295`; `providers/prediction.py:29`). A CLOB daily bucket is the price *as of that bucket's start*, so treating it as "known at bucket time" gives the backtest the **bucket's own price on the entry bar** — a **1-bucket look-ahead** the `social-llm-edge-lane.md` plan (lines 197-200) flags explicitly and the `edge-sprint-plan` claim #3 names. It does **not** embed the *future resolution* (no CrowdIntel-style outcome leakage), but it does let an entry signal use same-bucket price. The fix is a **+1-bucket PIT lag** (`available_at = ts + bucket`), which the in-flight leakage tripwire is precisely designed to catch.

### 3. The UMA resolution join — the real money gap

- `payoutNumerators` appears **nowhere in the engine Python** — only in two docs (`plans/social-llm-edge-lane.md`, `reports/epics-backlog-audit-2026-06-25.md`). The audit's claim that it is "used in EXEC, not the research/alt path" is **confirmed**: the only authoritative-outcome handling is in `adapters/exec/polymarket.py` (`parse_positions`/settlement), and even there it is the order/settlement path, not a stored historical outcome label.

- The research path **never joins the resolved outcome.** `fetch_polymarket` (`venue_universe.py:294-322`) ingests only `closed=false&active=true` markets and sets `delisted_at` from the *scheduled* `endDate`, not the actual UMA resolution timestamp/outcome. `PredictionDataAdapter.universe` (`adapters/data/prediction.py:46-60`) drops a market once `as_of >= resolves_at` (no resolved-market look-ahead — good), but there is **no `(conditionId → {resolved_ts, winning_outcome, payout})` table** anywhere.

- **Consequence (verified in the spec):** `g2-prediction-prob-overextension-fade-short.json` exits purely on `tp / stop / time_stop` over the odds price. Its own **Disconfirmer 2** says "rich contracts can keep rising to resolution (the favorite wins); if the edge is dominated by resolution losses, the fade is on the wrong side of the longshot bias" — **but the backtest cannot test that**, because the resolution outcome is not joined. A favorite-bias / longshot edge is *defined* by what happens at resolution; without the join, the backtest measures odds mean-reversion, not the real P&L. This is the single most important de-risking item.

### 4. Coverage & granularity

- Per-market series: top-~30 most-liquid OPEN markets (`ingest/polymarket_odds.py::top_liquid_condition_ids`, `DEFAULT_MAX_MARKETS=30`, `PREDICTION_SCREEN_LIMIT` in `screen_universe.py`), each 180–400 daily rows from market inception — IF ingested. History depth is per-market and short (event markets are months, not years).
- **Granularity is the binding constraint:** every path hardcodes `fidelity=1440` (daily) — `polymarket.py:133,284`, `providers/prediction.py:21`. Daily odds on a months-long market ≈ a handful of regime states ≈ **~1 trade/market**, which the per-cell min-trades floor (`MIN_TRADES_PER_SYMBOL=5` pre-screen, `_BRUT_MIN_TRADES=30` gate, `finder.py:82,85`) **correctly refuses**. The CLOB `prices-history` endpoint accepts a smaller `fidelity` (e.g. `60` = hourly), so **hourly is available** and is the right unlock for trade frequency.

### 5. Does the parallel leakage-tripwire risk apply? — **Yes, directly.**

This source is the **canonical reference case** the tripwire is built for (`social-llm-edge-lane.md:197-200`). The two tripwire-relevant exposures here are exactly (a) the `available_at == ts` PIT-lag, and (b) the resolution-outcome join (the place a CrowdIntel-style future-leak would enter if done naively). Wiring the resolution join **without** the tripwire would be the highest-risk way to ship this; the tripwire (shuffle-null + PIT-lag check on `(conditionId, odds)`) must gate it.

---

## Exact minimal wiring to make Polymarket odds gate-ready (de-risk option-2)

Three fixes, ranked by leverage. All are additive; none touch the locked Gate constants.

### Fix A — schedule the per-market odds ingest + go **hourly** (unblocks min-trades)
1. **Schedule `ingest_per_market_odds`.** Add a call in the hourly ingest path (or a dedicated entrypoint invoked by the Modal `ingest` cron) that runs `ingest_per_market_odds(alt_store, store, max_markets=30)`. Today it is orphaned — this is the one-line wiring that makes the prediction-contract lane have any data at all.
2. **Add an hourly source variant.** Parameterize `fidelity` in `PerMarketOddsSource.fetch_odds` (currently hardcoded `1440`) and ingest hourly (`fidelity=60`) for the active per-market lane. Hourly ≈ 24× the rows → markets clear `MIN_TRADES`/`_BRUT_MIN_TRADES` honestly without loosening the Gate. Keep daily for the macro composites (those are crypto features, fine as-is).

### Fix B — the **UMA resolution join** (the look-ahead-killer + the real edge)
3. **Ingest authoritative outcomes, point-in-time.** Add a resolution source that, for each ingested `conditionId`, fetches the resolved `payoutNumerators` / winning outcome + the actual resolution timestamp (Gamma `umaResolutionStatus`/`endDate` + the CTF `payoutNumerators`), stored append-only as `(provider="polymarket", symbol=conditionId, metric="resolution")` with `available_at = real_resolution_ts` (NOT the market's scheduled endDate). This is the single source of truth the backtest needs to compute terminal P&L (a YES share pays \$1 if the outcome resolves YES, \$0 otherwise).
4. **Join it in `PredictionDataAdapter` / the prediction backtest** so a position held to resolution settles at the authoritative payout, not the last odds quote. PIT-safe: the resolution row is only visible once `available_at <= as_of`, so it can never leak into the entry signal. This converts the lane from "odds mean-reversion" (untestable favorite-bias) to a real, resolution-settled backtest — directly enabling Disconfirmer 2.

### Fix C — PIT-lag fix + the tripwire gate (revision/leakage safety)
5. **+1-bucket PIT lag.** Change `available_at` from `ts` to `ts + one_bucket` in the per-market fetch path so the entry bar can't use its own same-bucket price. Small, surgical, removes the one baked-in look-ahead.
6. **Run it through the leakage tripwire** (the parallel build): shuffle-null + PIT-lag check on `(conditionId, odds)` BEFORE the `odds`/`resolution` features are trusted by the Gate. This source is the reference case; do not ship Fix B without Fix C's tripwire in front of it.

### Then — the panel/cross-market Gate (the statistical shape this edge needs)
7. The favorite-bias edge is **cross-market** (+7–13% in the prior probe, per the audit/plan). The honest evaluation is a **panel**: each market = 1 clustered observation, held-out markets, not 30 within-market trade sequences. This is the `polymarket-master-plan` E1–E5 work (build on Modal, sandbox-first); flag it as the follow-on so the per-cell BRUT Gate isn't misread as the final word.

---

## Bottom line

Polymarket odds is the **lowest-cost, highest-evidence niche-market lane** and the engine is ~80% wired for it: PIT store, revision safety, per-market adapter, finder branch, cost overlay, and exec adapter all exist. It is **REVIEW not GO** for exactly three reasons, each a known, bounded fix: (A) the per-market odds ingest is **orphaned + daily** (min-trades correctly refuses it), (B) there is **no UMA resolution join in the research path** (the backtest can't measure the favorite-bias edge it's hunting), and (C) a **1-bucket look-ahead** + missing tripwire gate. Land A+B+C and this is a **GO** — and the cleanest shot at COSMU's first forward survivor from an axis NY ignores. Gate stays locked throughout; every fix is wiring + data, not a softening.
