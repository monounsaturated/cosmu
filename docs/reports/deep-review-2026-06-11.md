# Deep review — 2026-06-11 (full-codebase audit, cloud session)

> Five parallel review lanes over the whole repo: money-path correctness · architecture/maintainability ·
> agentic/self-learning design · data pipeline + ops · API/web/security. Every headline claim below was
> re-verified against source by the orchestrating session before being written down. Two findings were
> **fixed in this PR** (marked FIXED); the rest are recorded as pre-live gates in `BACKLOG.md`.

## Verdict in one paragraph

The statistical core is unusually well-engineered (textbook-correct PSR/DSR/CSCV/BH-FDR, real trial
registration, PIT joins, two-sided costs on the long path, LLMs verifiably outside the money path, live
orders unwireable today). The honesty culture — intent headers, naming guard, no-synthetic-data rule,
honest-empty UI — is top-decile and genuinely maintained. But the review found two implementation defects
that undermined the system's core claims (short-side fees inverted; scheduled ingest non-idempotent —
both FIXED here), and three structural gaps that mean the forward-test "live-ready" signal does not yet
measure the gated hypothesis (funder's static first entry, arbitrary symbol assignment, structurally
reused holdout). Scores from the dedicated assessment: **agentic-first 8/10 · pattern-discovery 6/10 ·
self-learning 5/10**. Grades: structure C+ · LLM-readability A− · leanness B+ · maintainability B.

## FIXED in this PR

1. **Short-side fee inversion** (`data/backtest.py` entry booking). For `direction=-1` the old
   `d`-mirrored entry (`qty = notional*(1-fee)/fill; cash -= d*notional`) shrank the LIABILITY by the fee
   while crediting full proceeds — the entry fee booked as a GAIN. A flat-price short round trip netted
   **+fee²·notional instead of −2·fee·notional** (≈ +$0.02 vs −$40 on $20k at 10 bps). Per-trade
   `pnl_pct` charged fees correctly, which is why no sign test caught it — but every equity-curve-derived
   metric the gate scores (return/Sharpe/DSR/drawdown/folds) was gross-of-fee for shorts, poisoning the
   perp/short research lane. Fixed: a short now sells the full liability and receives proceeds net of fee.
   Regression: `test_short_pays_fees_like_a_long_on_a_flat_path` (fails on the old code).
   `perp_market_neutral.py` was NOT affected (turnover-based fee model); `research/gate.py` is long-only.

2. **Scheduled ingest was non-idempotent** (`ingest/pipeline.py`). `ingest_numeric`,
   `ingest_market_wide_numeric`, `ingest_liquidations`, `ingest_news_sentiment`, `ingest_news_event_score`
   appended the full provider window (default 1000 points) with NO dedup — despite the module's own
   "idempotent" intent header. `alt_data` has no unique index and `PgAltDataStore.append` is a plain
   INSERT, so every cron pass added a full duplicate copy of each window. Since the 2026-06-11 cadence
   change (6h → 15min) that is ~96 duplicate copies/day/series. Two consequences: (a) unbounded `alt_data`
   growth (~6 GB of the 8 GB Supabase cap already used); (b) **the gate silently saw less history than it
   asked for** — `StoreBackedAltProvider.fetch_series` returns `read_all(...)[-limit:]`, so duplicates
   compressed the DISTINCT span inside the slice (the PIT *values* stayed correct via `read_asof`; the
   *depth* and the n_rows telemetry did not). Fixed: scheduled paths now write only new
   `(ts, available_at)` rows (vendor revisions still land), and `fetch_series` collapses exact duplicates
   before the trailing slice so `limit` counts distinct points. **Operator action: compact the existing
   prod duplicates** — see BACKLOG.

## Open findings (recorded in BACKLOG as pre-live gates)

### High — these contaminate the live-readiness evidence
- **H2 — the funder's first entry is not the strategy's** (`orchestrator/loop.py:206-221`): every newly
  funded track opens an immediate static long (side=1, conviction 0.5, 0.95/1.10 brackets) at the current
  mark regardless of the spec's entry signal. The first (often longest) leg of the ≥30-forward-day proof
  measures buy-and-hold-from-funding-day. The forward executor should open only when the spec's own entry
  fires (track starts FLAT).
- **H3 — forward-test symbol assignment is arbitrary** (`orchestrator/loop.py:96-110`): survivors are
  round-robined across catalog instruments (Binance: only BTCUSDT/ETHUSDT) instead of the universe they
  were screened on (BTC/ETH/BNB/SOL/XRP pooled). The forward test is not a test of the screened hypothesis.
- **H4 — the "untouched holdout" is structurally reused** (`data/backtest.py:144-167`,
  `master/holdout.py:27-37`): holdout metrics are computed for every variant on every screen and gate
  promotion requires a holdout pass; the HoldoutLedger only memoizes per-version verdicts — it never stops
  the next variant/tick from evaluating the same last-20% window. With 4-hourly cohorts over the same bar
  history, the holdout is a shared second validation set selected on thousands of times; DSR/FDR do not
  deflate this channel.
- **Web app has no auth of its own** (`apps/web/app/api/engine/[...path]/route.ts:22-25`): the proxy
  injects `x-api-key` server-side for ANY visitor to the Vercel URL — the engine's secret gate only stops
  direct engine calls. Anyone who finds the URL can toggle live / launch / defund (mitigated today only by
  the live-keys interlocks). Add Vercel Deployment Protection or an auth middleware, and assert
  `api_secret_key` is set when `APP_ENV=production`.
- **Silent source death** (`ingest/run.py:217-224`): failures log a 0 count; coverage `verify()` is
  CLI-only. Nothing pushes an alert when a source has been stale for days. Add a daily coverage diff →
  Slack degraded alert.

### Medium — structural honesty gaps, already partially tracked
- **M1 — fill-convention mismatch screen↔executor** (already a BACKLOG pre-live gate; confirmed): screen
  fills next-bar OPEN on idx-1 signals; executor decides AND fills on the latest CLOSE. Baked-in
  SIM/screen divergence that `master/drift.py` will misattribute to edge decay.
- **M2 — gap-through stops fill AT the stop** (`data/backtest.py` stop leg; `research/gate.py:318-319`):
  a bar that opens through the stop still fills at `stop*(1−slip)` — optimistic on gaps; entry-bar
  stop-check is skipped entirely.
- **M3 — equity marks can freeze + no total return** (`data/market.py:163-170, 332-339, 523-551`):
  Stooq/Yahoo serve any existing cache forever (no closed-bar guard, no freshness refetch — crypto
  providers have both), and Yahoo reads raw `close` not `adjclose` (dividends absent from marks and B&H
  baselines).
- **M4 — DSR benchmark dilutes as the trial ledger fills with duds** (`master/trials.py:25-30`): SR0
  scales with the cross-sectional σ of all trials' Sharpes; thousands of inert ~0-Sharpe LLM-authored
  trials shrink it toward plain PSR-vs-0.
- **M5 — FarmLoop's BH family is not deduplicated** (`evolution/loop.py:261-270, 347-355`): correlated
  mutants of one parent enter a single BH family (the finder clusters at ρ≥0.95; FarmLoop doesn't), and
  the novelty gate fails OPEN (`except: return True`).
- **M6 — `/live/defund` is a ledger wipe, not an exit** (`api/routers/live.py:113-126`): sets qty='0' in
  SQL — no order, no realized P&L; unrealized loss vanishes from equity. Dangerous shape if ever copied
  into a live lane.
- **M7/M8 — live-order hygiene before any live wiring**: live fills book at intended price corrected only
  by best-effort reconciliation (`master/execution.py:189-193, 316-318`); `gate_passed` on
  `IntendedOrder` is a caller-supplied literal — derive it from the store inside `execute_orders`.

### Architecture (drift bombs for AI-agent maintenance)
- **Gate bar duplicated under RENAMED keys**: `research/gate.py:31-39` `PREREGISTERED_BAR` vs
  `config/settings.py` GateSettings (`max_cscv_pbo` vs `max_pbo`, `must_beat_buy_and_hold` vs
  `require_beat_buy_and_hold`…). A calibration change to one silently diverges the other and grep can't
  catch it. Single-source the values.
- **Circular package graph**: 6 mutually-dependent top-level packages (`data↔master`, `api↔research`,
  `data↔ingest`, `lab↔research`, `master↔ml`, `master↔spine`) patched with deferred imports. Extract
  shared leaf types into the nearly-empty `cosmu/core/` and add an import-direction lint.
- **`data/backtest.py` is a 1,100-line god module** at the center of the cycle knot (fill sim + indicators
  + regimes + funding + meta-label + stats). Split into engine/signals/metrics/funding.
- **`research/` (34% of the engine) mixes** the production Gate + two cron entry points with ~35 closed
  one-shot campaign scripts. Quarantine campaigns into `research/campaigns/`.
- **Name traps**: `cosmu.master.portfolio` vs `cosmu.portfolio`; five modules named `loop`/acting as loops.
- **5 bps sim slippage defined in 3 places** (`research/gate.py:46`, `master/execution.py:29`,
  `spine/engine.py:240`); cohort metric helpers copy-pasted ~5× across campaign files.

### Agentic / self-learning (the "is it smart?" answer)
- **What's real**: graveyard memory → authoring avoidance + novelty gate; skill curator grades recipes by
  descendant pass-rate; brief rotation spans the whole feature registry; drift defunds with teeth; voice
  credibility → two PIT features. The statistics are top-decile; the placebo/control features (astro,
  earthquakes, weather) are a genuinely good idea.
- **What's not yet real**: the ML "survival model" trains on the gate's OWN verdicts (it learns to imitate
  its judge, not to predict money); nothing learns from forward/live divergence (`master/divergence.py` is
  display-only; `forward_exit` reasons never reach memory or priors); the Mind's consensus is consumed by
  nothing downstream and `reflect()` isn't even on the cron; the heavy discovery machines (event-study,
  `cross_feature_scan`, `matrix_search`) are CLI-only and their outputs don't auto-author hypotheses; the
  hypothesis language is 4 templates × single-feature thresholds on 5 Binance majors — most "weird hidden
  patterns" are inexpressible in it; **0 honest gate survivors to date**, so the evolve/compound flywheel
  has never fired.
- **Highest-leverage upgrades** (in order): (1) relabel survival/meta models with realized forward-track
  P&L and pipe forward_exit/divergence into graveyard memory; (2) schedule the discovery machines on
  Modal/cron and auto-author FDR-surviving cells into the inbox (propose-only); (3) expand the spec
  language (interactions, conditional/regime entries, cross-asset spreads, two-sided) and widen the
  autonomous screen universe; (4) replace fixed n=4 rotation with explore/exploit allocation over
  feature-family priors; (5) wake the dormant intelligence (register voices, put `reflect()` on the cron,
  emit Mind consensus as a PIT feature, upgrade the authoring model).

## What is verifiably done well (keep these invariants)
- PSR/DSR (Bailey–López de Prado), CSCV-PBO, BH-FDR implementations are formula-correct; pooled
  significance deflated by cross-symbol correlation; trials registered before scoring.
- Long/spot backtest: prior-bar signals, next-bar-open fills, adverse two-sided slippage, real per-venue
  fees, causal indicators, purged+embargoed holdout split, PIT as-of joins on `available_at`.
- LLM containment: zero LLM imports in scorer/fdr/cohort/trials; LLM output enters only authoring,
  narration, and ingest standardization.
- Live safety: no production code path calls `execute_orders(live_enabled=True)`; adapter defaults
  testnet; reduce-only is structurally verified; risk gauntlet is unbypassable for sim and live.
- Security: no hardcoded secrets; parameterized SQL throughout; keys server-side with `configured`
  booleans only; `hmac.compare_digest` auth; secrets never on adapter instances.
- Web honesty: `{data, connected}` everywhere, structurally-empty fallbacks, zero mock data, generated
  contracts with a drift gate, engine-enforced interlocks.
- Test culture: 1,687 tests, session-wide socket guard, deterministic seams, exact-value assertions,
  meta-tests that enforce conventions.

## Cleanups applied in this PR
- Deleted 4 closed-campaign orphans (~1,450 lines): `research/social_dominance_cohort.py`,
  `research/social_dominance_scan.py`, `research/equity_ibkr_refee_retest.py`,
  `research/equity_sector_cohort.py` (zero code references; campaigns closed in DECISIONS.md; run logs
  preserved under `docs/runs/`).
- Removed the dead `sqlalchemy>=2.0` dependency from the Railway image (zero imports in the engine; the
  Supabase MCP has its own requirements) and the unused `evals` pytest marker.
- Removed unused `formatEventKind()` + its label map from `apps/web/lib/utils.ts`.
- AGENTS.md skills table: removed the ghost `pine-from-url` row; added `strategize`, `manage-data`,
  `backfill-summaries`.
