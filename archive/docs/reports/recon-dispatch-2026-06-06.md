# COSMU — Dispatch Recon (2026-06-06)

Read-only 14-agent workflow (10 recon + 3 adversarial verify + 1 synthesis), branch `main`.
Produced the bulletproof T1–T7 dispatch spec, a GitHub Actions cost-cut, and a compute-placement
matrix. **Headline: the "~7 of 40 features wired" claim is refuted** — see §1.

## ⚡ Corrections that change the plan
1. **Feature counts (high confidence, verdict-confirmed):** registry = **67** enabled features (not 40);
   **18** consumed by gate.py + ml_panel.py (not 7); **30** routed-but-unconsumed (cheap wins);
   **13** truly unrouted (`UnknownAltMetricError` if requested) → delete-or-wire.
2. **NEW BUG — finder forward-test clock gap (P0 for the POC):** `lab/finder.py` survivors never write
   `track_opened`, so their forward-test clock never starts → they can never become live-armable.
   Only `evolution/loop.py:460` starts the clock. Must fix before the search can graduate a finder survivor.
3. **forward-test IS enforced now** (not cosmetic — old memory was stale): `api/routers/live.py:296-302`.
4. **`origin/claude/fix-bars-rest-fallback` already on main** (PR #61) — do NOT merge; delete the branch.
5. **CI was already optimized** — the real cut is deleting the redundant `typecheck` job (done 2026-06-06).
6. **No branch protection** (private/free) — pytest enforced ONLY by PR CI; direct-to-main bypasses it.

## 🔎 Live-checks still required before shipping
- Binance Vision exact URL scheme / `.CHECKSUM` / futures CSV header (T1).
- FRED ALFRED `realtime_start` vintage endpoint shape (T2 §3d).
- Binance REST geo-availability from Modal's US region (compute matrix).

---

## Full synthesis

I'll produce the consolidated dispatch package directly from the findings and verdicts provided. The data is comprehensive and file-level; I don't need to re-read the codebase. Let me reconcile the one number that needs care (the wired-feature count, where findings and verdict differ) and assemble the spec.

The reconciliation: the recon FINDINGS say 18 consumed / 13 unrouted-everywhere / 54 routed, while the VERDICT independently re-derives 18 consumed / 49 unwired (67 − 18). Both agree on 67 total and 18 consumed. The difference is "unwired" definition: the verdict's 49 = "defined but not consumed by ml_panel+gate"; the findings' 13 = "no data route at all." I'll present both axes explicitly since they answer different questions.

### 1. UNWIRED FEATURES — reconciled counts

**Headline (kills the stale "~7 of 40" claim, verdict-confirmed):**
- **67** features defined in `apps/engine/cosmu/config/feature_registry.py:33-272` (0 have `enabled=False`; default `enabled=True` at line 27). NOT 40.
- **18** distinct registry features are actually **consumed** by the two named surfaces (`ml_panel.py` + `gate.py`). NOT 7.
- Two different "unwired" denominators:
  - **49 not-consumed** (67 − 18) = defined but never read by ml_panel/gate.
  - **13 unrouted** = no data path *at all* (the true dead weight to delete or wire).

**The 18 CONSUMED:**
- ml_panel `DEFAULT_ALT_FEATURES` (`ml_panel.py:34-37`, 8): `funding_rate, open_interest, perp_spot_basis, exchange_netflow, fear_greed, news_event_score, macro_regime, vix_level`.
- gate.py (13, overlaps on funding_rate/fear_greed/macro_regime): `galaxy_score` (:100), `funding_rate` (:459,788), `fear_greed` (:461,790), `pm_risk_on` (:769), `macro_regime` (:770), `news_sentiment` (:781), + 7 `MULTIASSET_METRICS` `gold_xau, silver_xag, wti_crude, spx_index, ndx_index, eurusd, usdjpy` (`data/sources/multiasset.py:53`, read at gate.py:773).

**The 13 TRULY UNROUTED (delete-or-wire):** `xasset_risk_appetite, cftc_net_positioning, days_to_earnings, insider_buy_ratio, short_interest_ratio, xsec_momentum_rank, social_volume_accel, social_attention_z, social_excess_attention_z, galaxy_score_z, btc_social_accel, authority_weighted_claim_signal, author_authority`. HARD-FAIL with `UnknownAltMetricError` (`store.py:242-278`).

**The middle band — 30 routed-but-unconsumed** (cheapest wins, add to `DEFAULT_ALT_FEATURES`): e.g. `reddit_sentiment, social_volume, dvol, gdelt_tone, putcall_ratio, dxy, liquidation_cascade`.

**Routing:** 48 store-routed (`store.py:123-183`) + 6 computed-in-backtest (`ret_Nd, rsi, bb_z, vol_realized, atr, adx` — `backtest.py:665`) = 54 with a data path; 13 with none.

### 2. T1 BAR BACKBONE
- Match the **window-filter seam** (StooqBarBackfiller, `bars.py:174-207`), NOT the paginated ccxt seam (Vision is archive-per-month → download-then-filter; the page-walk risks double-emit).
- `BinanceVisionBarBackfiller.fetch_history(symbol, timeframe, *, start_ms, end_ms=None) -> list[Bar]`, injectable `_fetcher(url)->bytes`. Enumerate month URLs, download+unzip CSV, reuse `_klines_to_ohlcv` (`bars.py:37-40`, first 6 cols), window-filter, sort, dedup. **Do NOT write the cache** — return Bars; `manage.backfill_bars` (`manage.py:151-168`) writes via `write_bars_cache`.
- Wire a venue token in `_default_bar_backfiller` (`manage.py:42-45`) e.g. `binance_vision`. Test fixture: copy `test_manage_data.py:128` injection.
- **URL scheme (live-verify):** spot `data/spot/monthly/klines/{SYM}/{INT}/{SYM}-{INT}-{YYYY}-{MM}.zip`; perp `data/futures/um/monthly/klines/...`. Parse defensively (header row varies).
- **Collision:** `origin/claude/fix-bars-rest-fallback` is already on main (PR #61) — do NOT merge; Vision class is purely additive.
- **Tail gap:** `backfill_bars` doesn't pass `end_ms` → Vision defaults end→now; latest incomplete month missing from archives → pair with ccxt/REST tail.

### 3. T2 HONEST + COMPLETE HARNESS (one PR)
- **3a wire-all:** expand `DEFAULT_ALT_FEATURES` (`ml_panel.py:34-37`) to absorb the 30 routed-unconsumed; for the 13 unrouted, add a route+ingest OR delete from registry (the §3e guard forces it).
- **3b exchange_netflow → rename `perp_long_short_ratio`** (it's `globalLongShortAccountRatio` stored as `longShortRatio-1.0`, `onchain.py:93-104`). Atomic rename across: feature_registry.py:46, store.py:139, onchain.py:79-104, catalog.py:202, run.py:103/287-289, ml_panel.py:35, mind/analysts.py + rubric.py:98, BRIEF_TEMPLATE.md:22, + tests (test_dormant_sources, test_mind:107/113, test_ingest:65, test_manage_data:44, test_xai_twitter:225/248). Migrate/re-fetch any parquet under the old key. (DISABLE = cheaper alt.)
- **3c funding annualization:** real defect = 8h funding collapsed to one daily print → ~3× UNDER-charge + hardcoded cadence (`backtest.py:330-342` accrue, `640-658` align). Fix: sum prints per bar interval via a funding-only join; read per-symbol interval. Bug is conservative (under-states cost) but corrupts perp net-of-fee ranking. (The "2–8×" doc figure is lore; verified defect is the dropped intra-day prints.)
- **3d FRED vintage:** `data/providers/macro.py` returns latest *revised* values → look-ahead. Fix = ALFRED `realtime_start` vintage, or a documented conservative publication lag.
- **3e registry⊆routable guard** in `tests/test_alt_features.py`:
  ```python
  def test_every_enabled_feature_is_routable_or_computed():
      from cosmu.config.feature_registry import feature_names
      from cosmu.data.backtest import PRICE_FEATURES
      from cosmu.data.providers.store import _STORE_PROVIDER_OF
      unaccounted = feature_names() - (PRICE_FEATURES | set(_STORE_PROVIDER_OF))
      assert not unaccounted, f"enabled features with no route and not bar-computed: {unaccounted}"
  ```
- **Ordering:** 3b rename atomic → catalog↔store consistency test → 3a wiring → 3e guard (RED until 13 resolved) → 3c funding → 3d FRED → full suite.

### 4. T6 THE SEARCH (spot+perp BH-FDR family)
- No combined cohort runner exists — build `run_cohort` applying BH-FDR across the whole spot+perp family, then `promote_cohort` once. Reuse per-signal gate (`research/gate.py`, `evaluate_gate`).
- **Meta-labeling** = second-stage filter on the survivor set before promotion (consumes the widened ml_panel); it gates the Gate's survivors, doesn't replace the Gate.
- **Missing overlay harness:** no cohort joins market-wide `pm_risk_on` — build a market-wide regime series joined once to all members (not per-symbol).
- **Prereq:** funding fix (§3c) must land before the perp arm runs.

### 5. FORWARD-TEST — start the clock instantly
- Clock origin = first `track_opened` event (`master/live_eligibility.py:71-79`); `forward_age_days` (`master/forward_maturity.py:43-54`); maturity ≥30d AND net_return>0 (`forward_maturity.py:57-74`, `settings.py:19` "ADVISORY" comment is STALE — enforced hard).
- `track_opened` written in ONE place: `evolution/loop.py:460`.
- **GAP:** `lab/finder.py:477,503-525` opens a tracks row but appends `finder_survivor`, NOT `track_opened` → finder survivors never start the clock, never go live. Fix: route through evolution loop, OR have finder write `track_opened` + `proven_regimes`.
- Hard enforcement already wired at `api/routers/live.py:296-302,313`; `override` waives forward-test only, never the regime gate.

### 6. COMPUTE-PLACEMENT MATRIX

| Workload | Placement | Why | Prereq |
|---|---|---|---|
| Bulk bar backfill | **local-M2** | Modal has no Volume → ephemeral cache re-fetches every run | M2 disk |
| Alt-data ingest (6h) | **Railway** | Postgres warm + cron | Railway PG + cron |
| BH-FDR gate sweep | **Modal** | OOMs M2; HEAVY cpu4/mem8192, scale-to-zero | Modal secret `cosmu-engine` |
| Forward-test marking (hourly) | **Railway** | cheap, must run reliably | Railway cron |
| Backtests | **local-M2** one-offs / **Modal** large sweeps | M2 free for one-offs | Modal secret for sweeps |

Modal ref: `apps/engine/remote/app.py:43` (HEAVY/secret), gate_sweep :54-59, ingest :62-65, forward_mark :68-71. No Volume → bars ephemeral. Risk: Binance REST geo from Modal US unverified.

### 7. GITHUB ACTIONS COST-CUT
- Single workflow `verify.yml`, already PR-only + concurrency-cancel + paths-filter + caches.
- **PRIMARY CUT: delete the `typecheck` job** — redundant with `build` (`next build` typechecks the same fileset incl. contracts-ts via tsconfig include). Removes one runner per web PR. **DONE 2026-06-06.**
- Advisory: cache key `apps/web/src/**` is a dead path → fixed to `app/**,components/**,lib/**`.
- **Engine suite guarantee:** `engine_test` (`-n auto`, all ~887 tests/114 files, no `addopts`/`-k`/`-m`) UNTOUCHED, runs on every engine PR. The cut removes only the duplicate type-check runner.
- DO NOT: disable engine_test, change `-n auto`, re-add `push:[main]`.

### 8. OPEN RISKS / UNKNOWNS
1. No branch protection (private/free) → direct-to-main or merging-red bypasses CI; pre-push hook runs naming+contracts only, not pytest.
2. Binance Vision URL scheme — live-verify before T1.
3. FRED/ALFRED endpoint — live-verify before T2 §3d.
4. Binance REST geo from Modal US — live-verify before Modal self-fetch.
5. Funding "wide multiple" is lore; verified defect = dropped intra-day prints (~3× under-charge), conservative but corrupts perp ranking.
6. `run_cohort` / overlay harness shape are build decisions (no code yet).
7. exchange_netflow stored parquet may need migration on rename.
8. Finder-clock fix needs a `proven_regimes` passport too, or survivors stay regime-gated.
