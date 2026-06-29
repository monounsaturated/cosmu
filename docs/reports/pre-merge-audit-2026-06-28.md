# Pre-merge audit — 2026-06-28 autonomous-run batch (#458–#479)

READ-ONLY audit. PROPOSE fixes; nothing risky applied. All evidence is `file:line` against the
worktree at branch `claude/pre-merge-audit-2026-06-28` (forked from `main`). Scope: the three
operator concerns — (1) per-combo BRUT integrity, (2) granular/realistic fees (esp. Polymarket),
(3) env-var operational-toggle hygiene.

---

## PART 1 — NO COMBO IS EVER POOLED INTO A VERDICT

**VERDICT: per-combo BRUT is INTACT across the whole batch. No PR introduces per-strategy averaging
into a VERDICT, SIZING, or FEE.**

### The live verdict is still per-cell on its own streams

`apps/engine/cosmu/master/cohort.py:196` `promote_brut(...)`:
- `apps/engine/cosmu/master/cohort.py:219` — `trials = trials if trials is not None else TrialStats(count=1)`.
  The family count is 1; each cell's deflation rides only on `metrics.trials_counted` (its OWN
  param-search), invariant to how many OTHER cells the sweep produced.
- `cohort.py:223-224` — loops candidate-by-candidate, `score(c.metrics, gates, trials=trials,
  check_holdout=False)`. No `register_trial`, no Benjamini-Hochberg, no `cluster_representatives`,
  no net-profit rank. `promoted == passed`.
- Each candidate's metrics come from its OWN `per_symbol_run` (own `bar_returns` + own
  `fold_returns`): `apps/engine/cosmu/data/backtest.py:273,321` build `per_symbol_runs[symbol] =
  v_run` per symbol; `data/backtest.py:397 metrics_for_run(...)` builds metrics from one cell's own
  run + its own holdout. Consumed at `apps/engine/cosmu/lab/finder.py:53` (`from
  cosmu.master.cohort import promote_brut`).

### The pooled `fmean` stays DISPLAY-only

- `apps/engine/cosmu/data/backtest.py:321` writes a per-symbol `per_symbol[symbol]` dict
  (`return`/`sharpe`/`max_drawdown`/`trades`) — display, never fed to `promote_brut`.
- The only `statistics.fmean` in `data/backtest.py:517` is inside the Pearson `corr()` helper used
  for dedup clustering of DISTINCT cohort candidates — not a verdict average across a strategy's
  symbols.
- `data/backtest.py:323,366` — the beat-buy-and-hold check is each cell vs ITS OWN benchmark
  (`per_symbol_buy_and_hold[symbol]`, `_symbol_buy_and_hold(val_bars, sym_fee)`), never the pooled
  basket mean.

### The 5 PRs called out — each checked

| PR | Concern | Finding |
|----|---------|---------|
| **#474** fee parity | Is the order-path fee per-CELL/instrument, not pooled/averaged? | **Per-cell.** `master/execution.py:252` now passes `instrument=instrument` into `_pit_fee_for_order`; `execution.py:326+` resolves via `effective_taker_bps(venue, instrument, reference_price=float(price))` → `asset_taker_bps` (per category/per asset-class/per price). NO averaging across symbols; the fee is computed from THIS order's instrument + fill price + notional. |
| **#475** provenance | Per-cell? Any gate leak? | **Per-cell, display-only.** New `CellProvenanceResponse` + `/strategies/{id}/cell-provenance` keyed on `cell_id(version, symbol, venue)` (`api/routers/strategies.py`), served from the cell's own `track_opened` payload. Model docstring states "Display/audit only; never a gate input." `data/price_cells.py` `bar_source` is "never a gate input". No verdict/sizing/fee touch. |
| **#471** capital-path eligibility | Per-cell? | **Per-cell (this is the FIX).** `api/routers/live.py:644+` threads `symbol=request.symbol, venue_id=request.venue_id` into `live_eligibility_verdict` / `paper_clock_origin`, so arming evaluates the SAME BRUT cell key (`version:symbol:venue`). The version-scope fallback is gated on `attribution_confirmed` (the version's one funded cell IS the requested symbol@venue) — it widens which PROVEN cells arm, never which UNPROVEN cells arm, and never pools. `paper_step.py` adds `rejected`/`rejections` + `arm_opened_nothing` audit — surfacing only, no verdict math. |
| **#470** loop novelty | Verdict averaging? | **No.** `evolution/loop.py` adds an authoring-DOOR novelty gate (`_wave0_novelty_verdict`: "ok"/"skip"/"flag" with a human-vs-agent policy split) that protects the BH-FDR budget for the COHORT lane (`promote_cohort`, not `promote_brut`). It dedups near-duplicate inbox seeds before they each spend an FDR slot — this is the existing multiple-testing-honesty machinery, unrelated to per-cell BRUT. No pooling. |
| **#465** capital_guard | Verdict/sizing pooling? | **No — per-track.** `ops/capital_guard.py:3` judges each funded track "on ITS OWN cell-keyed marked equity (scope='track')"; `_latest_track_equity` / `_peak_track_equity` read `portfolio_snapshots WHERE scope='track' AND ref_id = version:symbol:venue` (`capital_guard.py:98-117`). Reduce-only, never opens/sizes-up. The `run_capital_guard_pass` wiring in `orchestrator/loop.py` is scheduling only. (Its env toggle is a PART-3 finding, not a BRUT one.) |

**No file:line violation found.** The batch is clean on per-combo BRUT.

---

## PART 2 — FEES granular + realistic per asset/contract

### Cost-path architecture (context)

- The production **gate cost path is ALWAYS-TAKER by design**:
  `apps/engine/cosmu/spine/asset_fees.py:4-8` header — "ALWAYS-TAKER (the OHLCV Bar model has no
  depth to justify a maker assumption, so crediting a maker rebate would inflate edge = leak)" and
  "FEES-PINNED-TO-TODAY". The screen resolves per-(symbol,venue) via
  `master/screen_universe.py:93 _asset_aware_fee` → `asset_taker_bps`.
- `#474` makes the **paper/live order path mirror the screen**: `master/execution.py` →
  `effective_taker_bps` → `asset_taker_bps`. Backtest == paper fee, per cell. This is correct and
  closes a real leak (paper formerly charged Polymarket ~0 / IBKR 0.5 flat).
- `apps/engine/cosmu/spine/fee_router.py` exposes maker/taker explicitly but is **PURE PLANNING**
  (`fee_router.py:8` "never sends an order or touches the money path") — it ranks venues by fee, it
  does not price a backtest.

### (a) Polymarket — GRANULAR and REALISTIC (one small gap + one minor over-charge)

`apps/engine/cosmu/spine/asset_fees.py:23-60`. The model is **per-category × (1−price)**, which
exactly matches Polymarket's published formula `fee = C × feeRate × p × (1−p)`
([docs.polymarket.com/trading/fees](https://docs.polymarket.com/trading/fees)). Makers pay 0
(modelled as 0, never credited a rebate — honest). Per-category rates vs the official March-2026
schedule:

| Category | Code rate (`asset_fees.py:23`) | Official docs | Verdict |
|----------|------|---------------|---------|
| crypto | 0.072 | 0.07 | OK (conservative over-charge by 0.2 pts) |
| sports | 0.03 | 0.03 | ✓ |
| finance | 0.04 | 0.04 | ✓ |
| politics | 0.04 | 0.04 | ✓ |
| tech | 0.04 | 0.04 | ✓ |
| economics | 0.05 | 0.05 | ✓ |
| culture | 0.05 | 0.05 | ✓ |
| weather | 0.05 | 0.05 | ✓ |
| other | 0.05 | 0.05 | ✓ |
| geopolitics | 0.00 | 0.00 | ✓ |
| world | 0.00 | (not an official category) | **MINOR UNDER-CHARGE RISK** — "world" maps to 0% but is not in the published table; the general/"other" rate is 5%. If a real market is tagged `world`, this under-charges. Low impact (most edge markets are geopolitics anyway). |
| **mentions** | **MISSING → defaults to crypto 0.072** | **0.04 (4%)** | **GAP** — "mentions" is a real category at 4% taker; the code lacks the key, so it falls to the 7.2% conservative default. Over-charges, not a leak, but not granular. |

**Proposed fix (low-risk, tightens-or-neutral):** add `"mentions": 0.04` to
`POLYMARKET_CATEGORY_FEE_RATE`; optionally bump `crypto` 0.072→0.07 to match docs exactly (leave
conservative if preferred); reconsider `world: 0.00` → `0.05` (treat as general) unless a verified
0% "world" subcategory exists. Sources:
[docs.polymarket.com/trading/fees](https://docs.polymarket.com/trading/fees),
[marketmath.io Polymarket fees March 2026](https://marketmath.io/blog/polymarket-fees-explained).
Note: the per-category rates are the FRACTION; effective bps = `feeRate × (1−price) × 10_000`, so a
50¢ economics share = 5% × 0.5 × 1e4 = 250 bps (`asset_fees.py:49-60`), correct.

### (b) Perp maker-vs-taker — production path is correct; the H1b research figure is over-conservative (NOT a gate bug)

- **Production**: there is **no Binance USDⓈ-M perp venue in the catalog** (grep of
  `spine/venue.py` for `binance_futures`/`usdm` → empty; only spot `binance` at 10/10 bps exists).
  The wired perp venues are `hyperliquid` (`venue.py:286` maker 1.5 / taker 4.5 bps) and
  `kraken_futures` (`venue.py:265` maker 2 / taker 5 bps), both with realistic tiered schedules.
  Because the gate is ALWAYS-TAKER, perps are charged at TAKER (HL 4.5, KF 5) — realistic and
  conservative. ✓
- **H1b research spike (#473)** is MAKER-ONLY and computes its round-trip from
  `_maker_round_trip_bps` = `2 × (maker_bps + slippage_bps)`. With `VENUE_ID="binance"` (SPOT) that
  is `2 × (10 + 5) = 30 bps RT`. The real **Binance USDⓈ-M perp maker is 0.02% = 2 bps**
  ([binance.com/en/fee/futureFee](https://www.binance.com/en/fee/futureFee)), so the catalog SPOT
  10-bps maker over-charges a perp-MAKER strategy by ~5×. The H1b file itself flags this: "the real
  USDⓈ-M perp maker is ~2bps so 30bps is CONSERVATIVE; we keep the catalog fee." This is a
  research-lane file, NOT the production gate, so it does not over-reject anything that funds. But
  the operator's H1b finding (perp-maker priced at spot catalog ~30bps RT vs realistic ~14bps) is
  confirmed accurate.

  **Proposed fix (if perp-maker becomes a real lane):** add a `binance_futures` (USDⓈ-M) venue to
  `spine/venue.py` with maker 2 / taker 5 bps + tiers, and a perp-maker research path that prices
  against it instead of spot. Do NOT credit maker rebates into the production always-taker gate
  (that would re-introduce the leak the header guards against). Until a maker lane is funded, the
  30-bps conservatism is safe (it can only over-reject in research, never mis-fund).

### (c) IBKR / Kraken / Binance spot — granular and matching published schedules

- **IBKR** (`asset_fees.py:68-124`): per-share `$0.0035` + `$0.35` min + 1% value cap (US equity/ETF
  — matches IBKR Tiered: $0.0035/share, $0.35 min, 1% cap), `$0.85`/contract US future, `$0.90`/contract
  EU future, `0.05%` EU equity + `€1.25` min, plus the French FTT 0.40% buy-leg asymmetry
  (`ibkr_ftt_buy_leg_bps`). Per-(asset-class × contract), evaluated at a $10k reference notional.
  Realistic and granular. ✓
- **Kraken spot** (`venue.py:184`) 25/40 bps base with a full 7-tier schedule down to 0/12;
  **Kraken Futures** (`venue.py:265`) 2/5 base, 6-tier to −1/2. **Binance spot** (`venue.py:158`)
  10/10 base, 5-tier; **OKX** (`venue.py:242`), **Coinbase** (`venue.py:204`), **Hyperliquid**
  (`venue.py:286`) all tiered. All match each venue's public tier tables and are per-venue. ✓
- **Alpaca** (`venue.py:230`) 0/0 — correct (commission-free US equities). The DAA arm
  (`research/equity_daa_arm.py`, #465) keeps a conservative 1.0 bps/side ETF fee anyway, so a track
  never looks better than reality.

**Fee summary:** Polymarket is granular + realistic with ONE missing category (`mentions`) and one
questionable `world: 0.00` mapping. Perp production fees are correct (always-taker, realistic
venues); the only "over-conservative" perp figure is in a research-only spike and is explicitly
accepted as conservative. No fee in the production money path is wrong in a way that mis-funds.

---

## PART 3 — ENV-VAR audit + operational toggles → frontend, NOT Railway

### (a) Full inventory of env vars the engine reads (classified)

INFRA — KEEP (API keys, DB, deploy/host config, secrets — legitimately env):

| Env var | Where | Why keep |
|---------|-------|----------|
| `PORT`, `HOST`, `APP_ENV` | `api/app.py:183-185`, `config/settings.py:144` | deploy/runtime host config |
| `DATABASE_URL` | `research/replication_cohort.py:408`, `rerun_cohort.py:468` | DB connection |
| `PG_READ_POOL_MAX` | `knowledge/store.py:76` | DB pool sizing (infra) |
| `API_SECRET_KEY` / `COSMU_BARS_KEY` | `data/market.py:175` | secret |
| `OPENROUTER_API_KEY`, `XAI_API_KEY` | `research/llm_narrative_pipeline.py:110`, settings | LLM keys |
| `REDDIT_CLIENT_ID/SECRET`, `SLACK_WEBHOOK_URL` | `data/sources/reddit_volume.py:199-200`, `notify/slack.py:39` | API keys / webhook |
| `MODAL_TOKEN_ID/SECRET`, `R2_*`, `BINANCE_*`, `ALPACA_*`, `POLYMARKET_*`, `RAILWAY_API_TOKEN`, `FRED_API_KEY`, `LUNARCRUSH_API_KEY`, `CRYPTOPANIC_API_KEY` | `api/routers/settings.py` key table | venue/infra secrets (presence-only inventory) |
| `COSMU_BARS_URL`, `COSMU_BARS_VENUE`, `COSMU_BARS_SRC`, `COSMU_BINANCE_CACHE`, `COSMU_EQUITY_CACHE` | `data/market.py:218,228`, `research/equity_*.py`, `remote/app.py:63` | data-source location/cache paths (infra) |
| `LIVE_JURISDICTION` | `ingest/venue_fees_refresh.py:63` | deploy locale (infra) |

OPERATIONAL TOGGLES — these change *what the autonomous machine DOES*, and several are the kind the
operator does NOT want as a Railway/Modal env var:

| Env var | Where | Class | Recommendation |
|---------|-------|-------|----------------|
| **`COSMU_CAPITAL_GUARD_ENABLED`** (#465) | `orchestrator/loop.py:520` | **SAFETY ACTION toggle** | **DELETE env var → DB-backed frontend setting.** This gates the reduce-only capital-protection watchdog — exactly the safety action the operator wants surfaced/controlled in the UI, not buried in Railway env. (See design below.) |
| **`COSMU_EQUITY_VENUE`** (#465) | `research/equity_daa_arm.py` | operational routing toggle | **MOVE to a frontend/DB setting** (it labels which venue an equity survivor arms on — alpaca vs ibkr). A routing default belongs in the settings store, not env. Low urgency (SIM-only, never arms), but it IS an operational choice. |
| `COSMU_SCREEN_DEEP` | `lab/depth.py:29`, `lab/finder.py`, `evolution/loop.py:1037`, `scripts/research/rescreen_cohort.py` | research/compute knob | Keep as a per-process CLI/research knob OR move to a settings flag. Not safety; default-off; acceptable as env for ad-hoc runs, but a frontend "deep screen" toggle would be cleaner. |
| `VOICES_LIVE_ENABLED` | `config/voices.py:98`, `ingest/voices_template.py:115`, `remote/app.py:218` | spend/operational toggle (flips $0 mock → paid LLM + network) | **MOVE to a frontend/DB setting** — it controls real spend and a live data lane; the operator should flip it in the UI, not redeploy env. |
| `AUTONOMY_CRON_ENABLED` | `master/scheduler.py:453`, `strategy/agent_run.py:18` | operational pause toggle | **MOVE to a frontend/DB setting** — "is the autonomous loop running" is an operational on/off the operator should control in the UI (the scheduler already reads a DB `live_toggle`; this should be a sibling DB flag, not env). |
| `COSMU_CRYPTO_SCREEN_N` (`evolution/loop.py:999`), `COSMU_MAX_BATCH` (`lab/strategize.py:79`), `COSMU_MAX_SWEEP_CELLS` (`remote/app.py:121`), `COSMU_PER_VENUE_BARS` (`data/price_cells.py:176`) | compute/breadth knobs | research/compute tuning — acceptable as env for now; surface in a frontend "engine tuning" panel if it becomes operator-facing. |
| `CORRELATION_SWEEP/PERSIST`, `CROSS_FEATURE_SWEEP/PERSIST`, `MATRIX_SWEEP/PERSIST/ASSET/TF`, `SCAN_UNIVERSE`, `NARRATIVE_SYMBOL/DAYS_BACK`, `REGIME_ASSET/FEE_BPS` | research scripts (`research/*.py`) | per-run CLI args (have `sys.argv` equivalents) | KEEP — these are research-script invocation params, not deployed-app operational toggles. |

NOTE: `COSMU_PLACEBO_RIDER` and `HL_POSITIONING_ACCOUNTS` were named in the task but do **not appear
as `os.environ` reads in the merged tree** (grep returned nothing). #461's placebo rider and #479's
HL logger are flag-gated but the flag is not surfaced as one of these env reads in
`apps/engine/cosmu`; if those PRs add such env reads they should follow the same rule (observe-only
research toggles → at minimum default-off, ideally a settings flag). Flag for the operator to
confirm against the #461/#479 branch diffs.

### (b) The specific new toggles — which should NOT be Railway env vars

- **`COSMU_CAPITAL_GUARD_ENABLED` — SHOULD NOT be a Railway env var.** It is a safety-action toggle.
  The whole point of #465 is that the watchdog runs on every paper-clock cycle; gating it behind a
  silent Railway env means a safety net can be disabled invisibly with no audit trail and no UI
  reflection. **This is the one to fix first.**
- **`COSMU_EQUITY_VENUE` — SHOULD NOT be a Railway env var** (operational routing default).
- **`VOICES_LIVE_ENABLED`, `AUTONOMY_CRON_ENABLED` — SHOULD NOT be Railway env vars** (spend / loop
  on-off — operator-facing operational toggles).
- `COSMU_SCREEN_DEEP` and the compute-breadth knobs are borderline (research/compute, default-off);
  acceptable as env for ad-hoc runs but cleaner as frontend tuning settings.

### (c) The existing runtime-settings mechanism to reuse

There IS already a DB-backed, frontend-surfaced runtime-settings mechanism — the **Go-Live caps /
kill-switch / Rules modal**:

- **Table `live_toggle`** (`apps/engine/cosmu/knowledge/schema.sql:295`): `id='global'`, `enabled`,
  `enabled_at`, `enabled_by`. Read at `master/scheduler.py:100 _live_enabled(store)` and
  `api/routers/live.py:279,334`.
- **Table `live_caps`** (`schema.sql:302`): per-scope rows (`pool`/`venue`/strategy), written by the
  Rules modal via `api/routers/live.py` (`/live/activate`, `/live/rules` →
  `INSERT INTO live_caps ...` at `live.py:109,541,553,681`).
- These are written through the `/api/live/*` routes and surfaced in the web's Go-Live caps +
  kill-switch modal. This is the canonical "operational toggle lives in the DB, surfaced in the
  frontend, audited via events" pattern.

(The separate `api/routers/settings.py` is a read-only *Keys inventory* — presence booleans for API
keys, no mutable values. It is NOT the mechanism to reuse for runtime toggles; reuse `live_toggle`/a
sibling settings table.)

### Concrete proposed design — route capital_guard through the existing mechanism

1. **Add a tiny `app_settings` (or reuse `live_toggle`-style) DB row** for operational toggles —
   the minimal change is a generic key/value settings table:
   `CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at
   TEXT, updated_by TEXT);` in both `schema.sql` and `schema_postgres.sql`. (If a settings table
   already exists in a later migration, reuse it; none found in the audited tree beyond
   `live_toggle`/`live_caps`.)
2. **Read it in `orchestrator/loop.py`**: replace `_capital_guard_enabled()` (`loop.py:520`, which
   reads `os.environ`) with a `store`-backed read —
   `SELECT value FROM app_settings WHERE key='capital_guard_enabled'`, default ON (`'1'`) when the
   row is absent (preserves today's default-on behaviour). `run_capital_guard_pass` already takes
   `store`, so no signature change at the call sites (`orchestrator/loop._main`, `remote/app.tick`).
3. **Add an `/api/settings/toggles` (or extend `/api/live/rules`) write route** that upserts the row
   and appends an audit event (`actor="human", kind="setting_changed",
   payload={"key":"capital_guard_enabled","value":...}`) — mirroring how `live.py` audits caps.
4. **Surface it in the frontend** alongside the Go-Live caps / kill-switch modal (the same web
   component that already reads `live_toggle`) as a "Capital guard (auto-protect)" on/off switch,
   default ON, with the existing audit feed showing who flipped it.
5. **DELETE `COSMU_CAPITAL_GUARD_ENABLED`** from the env / Railway config and from the
   `_capital_guard_enabled` helper once (2) lands. Apply the same pattern to `VOICES_LIVE_ENABLED`,
   `AUTONOMY_CRON_ENABLED`, and `COSMU_EQUITY_VENUE` (each becomes an `app_settings` key surfaced in
   the relevant UI panel).

**Env vars to DELETE (operational toggles → frontend settings):**
`COSMU_CAPITAL_GUARD_ENABLED` (safety — first), `VOICES_LIVE_ENABLED`, `AUTONOMY_CRON_ENABLED`,
`COSMU_EQUITY_VENUE`.

**Env vars to KEEP (infra/secrets/deploy):** all keys, DB URL, host/port/APP_ENV, cache/bars-source
paths, `LIVE_JURISDICTION`, `PG_READ_POOL_MAX`, and the per-run research-script CLI knobs.

**Existing mechanism to reuse for the capital_guard toggle:** the `live_toggle`/`live_caps` DB tables
(`schema.sql:295,302`) written via the `/api/live/*` Rules-modal routes and surfaced in the Go-Live
caps/kill-switch frontend component — add a sibling `app_settings` row + a small write route + a UI
switch, and read it from `orchestrator/loop.py` instead of `os.environ`.

---

## Bottom line for the orchestrator

1. **Per-combo BRUT: INTACT.** No PR pools into a verdict/sizing/fee. #474's fee is per-cell
   (instrument + price), #475 is display-only, #471 is the per-cell arming FIX, #470 is the cohort
   FDR door (not BRUT), #465's guard is per-track. No violation.
2. **Fees:** Polymarket is granular + realistic (per-category × (1−price), formula matches docs);
   ONE gap — `mentions` category missing (defaults to 7.2% over-charge; real 4%) — and `world: 0.00`
   is a questionable under-charge. Production perp fees are correct (always-taker, real venues); the
   only over-conservative perp figure (30bps RT) is in research-only H1b and explicitly accepted.
   IBKR/Kraken/Binance/Alpaca all per-venue/per-asset and match published schedules.
3. **Env vars:** DELETE the operational toggles `COSMU_CAPITAL_GUARD_ENABLED` (safety — first),
   `VOICES_LIVE_ENABLED`, `AUTONOMY_CRON_ENABLED`, `COSMU_EQUITY_VENUE`; route them through a new
   `app_settings` DB row read by the engine and surfaced in the existing Go-Live/Rules frontend
   modal (the `live_toggle`/`live_caps` mechanism via `/api/live/*`). Keep all keys/DB/host/cache
   env.
