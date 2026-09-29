# Hyperliquid long-tail positioning hoard-logger + crowding/liq-density feature + disconfirmer-gated BRUT harness

**Date:** 2026-06-28
**Branch:** `claude/hl-positioning-logger-2026-06-28`
**Status:** DRAFT PR — **NOT deployed, NOT applied, NOT merged.** Fully reversible. Does not touch the Gate or the money path.

> ⏱️ **DEPLOY ASAP to start the forward-hoard clock.** Native Hyperliquid history is shallow; the only way to get
> depth is to hoard FORWARD. **Every day of delay is a day later the Gate can rule (~2–3 wks out).** The hourly
> ingest cron already carries the hoard the moment Modal is redeployed — no schedule slot needed.

---

## The axis (why this is the #1 next data axis)

Deep-research (2026-06-28) concluded that **Hyperliquid per-account / aggregate on-chain positioning on
LONG-TAIL perps** is the best next data axis:

- **$0 / keyless** — the full clearinghouse state is served from `api.hyperliquid.xyz/info` with no key.
- **PIT-clean by construction** — an on-chain snapshot is immutable and is only knowable AT the capture instant,
  so `ts == available_at == capture-now`. No revision, no look-ahead — the leakage class that kills most alt data
  cannot exist here.
- **Structurally desk-invisible** — a Wall-St desk cannot (and largely does not) reconstruct crowd positioning on
  a $1–50M/day perp from a public chain. The thesis is the **thin tail**, so BTC/ETH/SOL/HYPE are EXCLUDED.
- **The binding cost is TIME** — native history is shallow, so we HOARD FORWARD. The sooner the poller runs, the
  sooner the Gate can rule.

---

## What was built

### 1. Forward-only poller — `apps/engine/cosmu/data/sources/hyperliquid_positioning.py`
Keyless `/info` poller. Per capture instant it snapshots, for a **configurable basket of 20 long-tail perps**
(majors excluded; `DEFAULT_LONGTAIL_COINS`):
- **Aggregate** (`metaAndAssetCtxs`): open interest, OI-notional ($), funding, mark, 24h notional volume.
- **Per-account** (`clearinghouseState` over a configurable `accounts` watchlist): Σ signed/gross position $,
  long/short **liquidation density** ($ within X% of liq price), and crowd breadth (# accounts in coin).

Append-only; stamps the **capture timestamp** (`ts == available_at == now`); never re-pulls a past instant.
One dead coin / one unreachable account is caught and skipped — never aborts the pass. Offline-testable via an
injected `_post` callable. `hoard_once(store, poller)` runs one capture and appends every metric point.

### 2. Durable sink — the existing alt-data store (state→Postgres hot, history→R2 cold)
Rows flow through the **standard `alt_data` path** (`provider='hyperliquid_positioning'`, `symbol=coin`,
`metric=…`), so no new table is needed and the cold-tier R2 DuckLake pipeline ages them out automatically.
A **NOT-applied** additive migration `apps/engine/cosmu/knowledge/migrations/2026-06-28_hyperliquid_positioning_hoard.sql`
adds a partial index for fast PIT reads of the high-cadence hoard (reversible: `DROP INDEX`). For tests, an
in-memory store is used.

### 3. Cron registration — `apps/engine/remote/app.py` (NOT deployed)
- The hoard is folded into the **hourly `ingest` cron** (`cosmu.research.loop._hoard_hl_positioning`), best-effort
  — so the forward hoard starts the moment Modal is redeployed, with **no new schedule slot** (Modal Free caps at 5).
- A dedicated **`hl_positioning` Modal function** (on-demand + a commented-ready `*/10 * * * *` decorator) lets the
  operator opt into the denser ~10-min thesis cadence by freeing a slot. Registered in the `main()` job dispatch.

### 4. PIT-honest features — `apps/engine/cosmu/data/sources/positioning_features.py`
- `hl_crowding_extreme_z` — trailing z-score of NET positioning (falls back to OI-notional × funding-sign when no
  per-account series exists).
- `hl_long_liq_density_norm` — long-liq density / OI-notional (the share of the book that is down-cascade fuel).

Both are **registered** in `config/feature_registry.py` (tier1, crypto) and **routed** in
`data/providers/store.py::_STORE_PROVIDER_OF` + owned by a new `hyperliquid_positioning` catalog source — so the
registry↔route guard and the catalog↔store lock-step both hold. The two features are **materialized** from the raw
hoard on each pass (`materialize_features`), so the correlation scan + Gate read them via the normal as-of join.

### 5. Disconfirmer-gated BRUT harness — `apps/engine/cosmu/research/hl_positioning_cohort.py`
Tests ONE **pre-registered hypothesis** — *"a crowding extreme on a thin perp predicts a 1–3d mean-reversion, net
of maker fees; the edge is the AGGREGATE stress, not copying any account"* — per coin through the **LOCKED**
`metrics_for_run → promote_brut` path (trials=1, per-cell min_trades floor; the DSR/PBO math is untouched), with
the **four named disconfirmers** baked in:
- **(a)** must **FAIL on BTC/ETH** — any promoted major makes the whole run `UNTRUSTWORTHY`.
- **(b)** must **survive a shuffled/lagged placebo** of the positioning series (`research.disconfirmers.shuffle_null`).
- **(c)** must **add IC over realized-vol + funding controls** (residualization keeps ≥50% of the raw IC).
- **(d)** **rejected if only "copy the biggest winner" works** (aggregate IC ≥ copy-whale IC).

**MUST NOT RUN NOW** — the CLI refuses until ≥14d of hoard exists (honest no-op on empty/shallow data).

---

## Tests — `apps/engine/tests/test_hl_positioning_logger.py` (16 tests, all PASS)
Offline + deterministic on synthetic snapshots (network never touched):
- Poller: aggregate parse, majors excluded, per-account net/gross/liq-density fold, dead-account skip, PIT +
  append-only `hoard_once`, None-metric omission.
- Features: trailing PIT crowding z (honest gap before window fills), OI-normalized liq density, funding-sign
  proxy, materialize-writes-derived-metrics.
- Harness: **positive control** (a seeded reversion edge clears the BRUT gate AND all four disconfirmers) + each
  disconfirmer **flags its own artefact** (a BTC/ETH leak → UNTRUSTWORTHY; a no-edge coin → killed by shuffle;
  a copy-whale-only edge → killed by (d)).
- Wiring: registry membership + routability + catalog lock-step + basket excludes majors.

```
16 passed in ~2.3s
```
Related suites re-run green (no regressions): `test_alt_features`, `test_catalog`, `test_correlation_scan`,
`test_hyperliquid_adapter`, `test_universe_hyperliquid_exclusion`, `test_disconfirmer_harness`,
`test_placebo_panel`, plus coverage/manage-data/feature-registry/leakage-tripwire/scan-signals (77 more).

## Live smoke-poll (read-only, through the shipped code path)
The keyless `/info` aggregate poll parses cleanly: 230 perps available; long-tail names (ZEC, WLD, SUI, ENA, TAO)
return OI, OI-notional ($18–45M), funding, mark. `clearinghouseState` per-account returns `assetPositions[]` with
`szi`, `entryPx`, `liquidationPx`, `positionValue`. `snapshot_to_points` stamps `ts == available_at == capture`.
**Parsing verified end-to-end; no long hoard was run (M2 discipline — a handful of snapshots only).**

## Confirmation: nothing deployed/applied
- No `modal deploy` was run (the cron change is in source only).
- The migration was NOT applied to any DB.
- No data was mutated; no merge; no money-path / Gate change. Reversible = delete the new files + drop the index.

## Honest limitations
- **Per-account watchlist is operator-supplied.** The keyless aggregate (OI/funding/mark) needs no address, but
  the per-account net / liq-density needs known large-account addresses via `HL_POSITIONING_ACCOUNTS`. There is no
  keyless leaderboard on `/info` (the `leaderboard` type returns 422), so without a watchlist the crowding feature
  falls back to the OI-notional × funding-sign **aggregate proxy** (weaker, but still PIT and keyless). Curating a
  good watchlist of large/representative accounts is the highest-leverage follow-up.
- **Data-starved at birth.** The two features + the harness are wired but cannot rule until the forward hoard
  accrues (~2–3 wks). This is the whole point — deploy ASAP.
- **Cadence.** Default is hourly (rides the ingest cron). The thesis wants ~10 min; that needs a freed Modal Free
  schedule slot (decorator is commented-ready).
- **The harness's live run needs bars.** The CLI verifies readiness; the operator passes `bars_by_coin` (HL
  candleSnapshot, already supported by the existing adapter) when running the experiment for real.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
