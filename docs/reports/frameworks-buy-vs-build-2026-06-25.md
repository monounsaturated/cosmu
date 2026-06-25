# Frameworks Buy-vs-Build Audit — 2026-06-25

Read-only survey of `apps/engine/cosmu`. Question asked by the operator: *where does the codebase
reinvent something an established library/SDK/framework does better — and what should we ADOPT vs
keep custom?* Principle applied throughout:

- **The deterministic Gate + per-combo BRUT honesty is the MOAT → KEEP custom.** No library
  implements per-(strategy×asset×venue) isolation, point-in-time alt-data joins, the shared
  backtest≡live cost model, or the published-spec trial-deflation. These are the asset.
- **Commodity plumbing → ADOPT a vetted lib** where it removes correctness risk or maintenance.
- **Correctness-critical statistics → prefer a vetted lib over hand-rolled.** A subtle bug in the
  Gate math is the worst failure mode (it funds noise). This is where the highest-value adoption sits.

Verdict legend: **ADOPT** (replace/back with a lib now) · **SPIKE** (time-boxed trial, adopt only
if it pays off) · **KEEP-CUSTOM** (the moat or a deliberate, justified hand-roll).

---

## Summary table

| Area | What we do now | Candidate lib/SDK | Verdict | One-line rationale |
|---|---|---|---|---|
| Backtest bar-loop / fills / equity curve | Hand-rolled explicit Python for-loop over bars, `Decimal` cash accounting (`data/backtest.py` ~1600 ln) | vectorbt · backtesting.py · nautilustrader · zipline-reloaded | **KEEP-CUSTOM** (SPIKE vectorbt only as a pre-screen if sweeps >10k) | Per-combo isolation + shared backtest≡live cost model + PIT alt-join are the moat; no lib does them. Loop speed isn't the binding constraint. |
| Backtest cost model (slippage/impact/funding) | `_slippage` sqrt-participation impact + liquidity-tiered floor, shared verbatim with `research/gate.py::_simulate` | (none — libs use flat bps) | **KEEP-CUSTOM** | The shared model is *why* the Gate can't bless an un-tradeable fill. Libraries are strictly less honest here. |
| **Gate stats: PSR / DSR / expected-max-Sharpe / CSCV-PBO** | **Hand-rolled** in `master/scorer.py` (stdlib `NormalDist`/`statistics` only); CPCV hand-rolled in `master/cpcv.py` | No drop-in lib for DSR; **but** parity-pin against an independent reference impl | **ADOPT (parity-pin) — highest leverage** | The math is correctness-critical and has **no parity test against an independent implementation** (unlike FDR/Spearman). A subtle bug funds noise. See "Top 3" #1. |
| Gate stats: BH-FDR | `master/fdr.py` → `statsmodels.stats.multitest.multipletests` | statsmodels | **KEEP-CUSTOM (already adopted ✅)** | Already backed by statsmodels, parity-pinned in `tests/test_fdr_parity.py`. The model to copy. |
| Gate stats: Spearman rank-IC | `master/scorer._spearman` → `scipy.stats.spearmanr` | scipy | **KEEP-CUSTOM (already adopted ✅)** | Already backed by scipy, parity-pinned in `tests/test_spearman_parity.py`. Advisory metric. |
| Holdout split (purged + embargo) | Hand-rolled `_purged_embargoed_split` (`data/backtest.py`) + `master/cpcv.py` | `mlfinlab` (PurgedKFold) | **KEEP-CUSTOM** | mlfinlab is now commercial/unmaintained-OSS; the stream-level purge here is small, tested, and correct. |
| Market data: crypto bars | ccxt with keyless-REST fallback (`data/market.py`, `ingest/bars.py`) | ccxt | **KEEP-CUSTOM (ccxt already adopted ✅)** | ccxt is used and depended-on; the wrapper adds PIT closed-candle drop + freshness guards (correct, not reinvention). |
| Market data: bulk history | Binance Vision monthly ZIP/CSV (`data/binance_vision_backfill.py`) | (ccxt can't do this) | **KEEP-CUSTOM** | Not duplicated functionality — ccxt caps ~1k bars/call; Vision is the bulk backbone. |
| Venue public data (OKX/Kraken-Fut/Hyperliquid/Alpaca/universe) | Hand-rolled `urllib` REST behind injectable seams | ccxt (some) · native SDKs | **KEEP-CUSTOM** (SPIKE ccxt for OKX/Kraken-Fut *data* only if a parser breaks) | Keyless public endpoints + offline-testable seams; stdlib is the right call. Re-evaluate per-venue if maintenance bites. |
| Execution: Binance/Kraken | ccxt (`adapters/exec/`) | ccxt | **KEEP-CUSTOM (ccxt adopted ✅)** | Correct buy. |
| Execution: Polymarket | `py-clob-client` for EIP-712 signing; urllib for reads | py-clob-client | **KEEP-CUSTOM (SDK adopted ✅)** | On-chain signing is unavoidable SDK territory. Correct buy. |
| Execution: live order routing | Hand-rolled per-venue adapters; `spine/venue.py` already names a `nautilus.*` adapter convention | **NautilusTrader** | **SPIKE (BUY-WHEN-LIVE) — pre-staged** | Matches the standing decision: adopt Nautilus' execution/OMS once a strategy survives 30-day forward and goes live. The catalog already anticipates it. |
| Strategy spec | pydantic v2 typed models (`strategy/spec.py`) | pydantic | **KEEP-CUSTOM (pydantic adopted ✅)** | Correct. |
| Param search | Hand-rolled coarse grid (3 pts/param, 256-variant cap) + local refine (`lab/finder.py`) | optuna · scikit-optimize · hyperopt | **SPIKE optuna (low priority)** | Grid is fine and deterministic at current breadth; Optuna's TPE + pruner would help **only** if/when per-spec sweeps get expensive. Determinism + trial-counting for DSR must be preserved. |
| Scheduling / compute | Modal cron fleet | Modal | **KEEP (adopted ✅)** | Correct buy. |
| Portfolio / risk / sizing | Hand-rolled accounting, rule gauntlet, EWMA vol-target (`master/portfolio.py`,`risk.py`,`sizing.py`,`neutral.py`) | PyPortfolioOpt · riskfolio-lib · cvxpy | **KEEP-CUSTOM** | No convex optimization is performed (per-combo sandboxed wallets, not a global MV optimizer). A solver would be over-engineering. Revisit only if a true book-level allocator (T3 Kelly/MV) is built. |
| ML: logistic (meta-label, survival) | Hand-rolled L2 logistic + GD (`ml/logistic.py`), shared by meta-label & survival | scikit-learn `LogisticRegression` | **SPIKE (optional-dep)** | Hand-roll is deliberate (CI runs without sklearn; deterministic). sklearn would be more robust *if* made an optional dep with a pure-Python fallback — mirror the `survival.py` xgboost pattern. |
| ML: survival ranker | XGBoost/LightGBM optional → pure-Python logistic fallback (`ml/survival.py`) | xgboost/lightgbm/scikit-survival | **KEEP-CUSTOM (good pattern ✅)** | The optional-boosting-with-fallback pattern is the right shape. Ranking-only, never vetoes. |
| ML: meta-labeling (triple-barrier) | Hand-rolled barriers + logistic (`ml/metalabel.py`) | mlfinlab | **KEEP-CUSTOM** | mlfinlab commercial now; the barrier logic is small + tested + on the backtest hot path. |
| Regime / Markov | Hand-rolled causal no-repaint hysteresis classifier (`ml/regime.py`, `research/regime.py`) | hmmlearn · statsmodels MarkovRegression | **KEEP-CUSTOM** | The no-repaint/causal property is the whole point and is *why* a library HMM (which repaints on refit) is wrong here. Documented FAIL as an edge; kept as a feature. |
| Vector memory | pgvector / `knowledge/` | pgvector | **KEEP (adopted ✅)** | Correct. |

---

## Per-area verdicts (detail)

### 1. Backtesting engine — KEEP-CUSTOM (vectorbt SPIKE only as a pre-screen)
`data/backtest.py` is an explicit Python bar-loop (`for idx in range(start, len(bars))`), pure
stdlib (`math`, `statistics`, `Decimal`), no numpy/pandas. It hand-rolls the position state machine,
fills, TA indicators (RSI/ATR/ADX/BB with Wilder smoothing), and the equity curve — roughly ~45% of
the file is mechanical plumbing that vectorbt/backtesting.py/nautilus also provide.

But the remaining ~16% plus the architecture is the moat and **no library does it**:
- **Per-combo BRUT isolation** (`metrics_for_run`, the per-symbol `SymbolRun` map): each
  (strategy×symbol×venue) cell scored on its OWN validation, OWN holdout, OWN buy-and-hold — never
  pooled. This directly implements the locked S×A×V model.
- **Shared backtest≡live cost model**: `_slippage` (liquidity-tiered floor + `impact·sqrt(participation)`,
  `DEFAULT_SLIPPAGE_BPS=5`, `DEFAULT_IMPACT_BPS=50`, `LIQ_FLOOR_K=15`, `LIQ_FLOOR_MAX_BPS=50`) is shared
  verbatim with `research/gate.py::_simulate` and pinned in `tests/test_gate_backtest_cost_parity.py`.
- **Point-in-time alt-data join** (`align_asof` + `max_age` staleness guard) and per-bar funding accrual.
- **Purged/embargoed split** + calendar-aware per-asset-class annualization.

Adopting vectorbt would mean re-implementing all of the above *on top of* it — net negative. The
loop is not the binding constraint (per the 2026-06-18 pre-compute audit, hypothesis diversity is).
**Keep.** The only opening: if/when a single sweep exceeds ~10k variants, SPIKE vectorbt as a *fast
Modal pre-screen* that shortlists candidates the honest engine then re-runs — exactly the standing
"VectorBT SPIKE-IF >10k sweeps" decision. Don't let it touch the Gate.

### 2. Gate statistics — the split decision (ADOPT for the hand-rolled half)
Two-tier reality:
- **Already vetted ✅**: BH-FDR (`master/fdr.py` → statsmodels, parity-pinned) and Spearman
  (`master/scorer._spearman` → scipy, parity-pinned). This is the gold standard — a vetted lib
  behind a thin wrapper with a byte-parity test.
- **Hand-rolled, NOT parity-pinned ⚠️**: PSR, DSR, `expected_max_sharpe` (SR0), `cscv_pbo`
  (`master/scorer.py`), and CPCV (`master/cpcv.py`). These use only stdlib `NormalDist`/`statistics`.
  Tests (`test_strategy_dsr_prob.py`, `test_cpcv.py`, `test_gate_constants_pinned.py`) check internal
  coherence and pinned numeric constants, but **none pin the math against an independent reference
  implementation**. This is the single highest correctness risk in the codebase: a subtle bug in the
  expected-max-Sharpe estimator or the variance-inflation term would silently mis-calibrate the
  one number between us and funding noise.

No off-the-shelf library exposes a drop-in DSR (it's a López de Prado construction). So the adoption
here is **not "replace with a lib"** — it's **"parity-pin the hand-roll against an independent,
vetted implementation"** (a reference DSR/PSR in a research-only script using scipy.stats + numpy, or
a vendored second implementation), the same discipline already applied to FDR/Spearman. See Top 3 #1.

### 3. Market data / venues — KEEP-CUSTOM (already buying the right things)
No reinvention found. ccxt is used for crypto bars (with a deliberate keyless-REST fallback for
geo-blocking) and Binance/Kraken execution; py-clob-client signs Polymarket orders. Hand-rolled
`urllib` is reserved for *keyless public* endpoints (OKX/Kraken-Futures/Hyperliquid/Alpaca/Stooq
data, venue-universe listings) behind injectable seams — cheaper, offline-testable, no SDK needed.
Binance Vision ZIP backfill is genuinely not a ccxt capability. The custom layers that wrap ccxt
(closed-candle drop, freshness, universal-price unify/fallback) are PIT-honesty guards, not
duplication. **Keep.** Minor optional SPIKE: if an OKX/Kraken-Futures *data* parser ever breaks on a
venue API change, swapping that one fetch to ccxt is a reasonable maintenance trade — not urgent.

### 4. Strategy spec & param search
Spec = pydantic v2 (correct, keep). Param search = hand-rolled coarse grid (`_GRID_POINTS=3`,
`_MAX_VARIANTS=256` cap, stride-sample, then `refine_around` ±15% local) in `lab/finder.py`. No
optuna/skopt/hyperopt anywhere in core. At current breadth a deterministic grid is the *right* call
(determinism matters: the trial count feeds DSR deflation). **SPIKE optuna only** if per-spec sweeps
become a compute bottleneck — and only if its TPE/pruner can be made deterministic and its trial
count fed honestly into the deflation. Low priority.

### 5. Scheduling / portfolio / risk
Modal = correct buy, keep. Portfolio/risk/sizing are hand-rolled accounting + a rule gauntlet +
EWMA(λ=0.94) vol-target — **no convex optimization is performed**, because the design is per-combo
*sandboxed wallets*, not a global mean-variance book. Pulling in cvxpy/PyPortfolioOpt/riskfolio
would be over-engineering for what's currently algebra. Re-evaluate **only** when the deferred
T3 book-level allocator (Kelly tilt / cross-strategy MV) is actually built — *that* is where a
solver (cvxpy) earns its place.

### 6. Regime / ML
All money-path ML is hand-rolled pure-Python (logistic via GD, triple-barrier meta-label,
deterministic regime), with `survival.py` optionally using xgboost/lightgbm and falling back to the
pure-Python logistic. The regime classifiers are deliberately **not** hmmlearn/statsmodels HMMs
because a library HMM *repaints* on refit — the no-repaint/causal property is the entire correctness
argument (DECISIONS 2026-06-07). The one defensible adoption is making **scikit-learn an optional
dependency** behind the existing pure-Python logistic (mirror the survival.py xgboost pattern): more
robust optimizer/regularization when present, identical determinism + zero-dep CI when absent.
Medium-low priority — the current logistic is advisory and tested.

### 7. Vector memory
pgvector — correct, keep.

---

## Top 3 highest-leverage adoptions

1. **Parity-pin the hand-rolled Gate stats (PSR / DSR / expected-max-Sharpe / CSCV-PBO / CPCV)
   against an independent reference implementation.** *(Correctness — highest value.)*
   These are the only correctness-critical statistics with **no independent parity test** (FDR and
   Spearman already have one each). The Gate's entire credibility — and the "never fund noise"
   guarantee — rests on this math being right. Action: write a reference DSR/PSR/PBO in a
   research-only harness using `scipy.stats` + `numpy` (allowed off the lean hot path) and pin
   `master/scorer.py` + `master/cpcv.py` against it in a `test_gate_stats_parity.py`, exactly as
   `test_fdr_parity.py` / `test_spearman_parity.py` do today. Low effort, removes the worst silent
   failure mode. Keeps the lean stdlib runtime; the reference is test-only.

2. **Pre-stage NautilusTrader for the execution/OMS lane (BUY-WHEN-LIVE).** *(Reliability at the
   money-path edge.)* This confirms and operationalizes the standing decision. The hand-rolled
   per-venue exec adapters are fine for paper/SIM, but live order management (partial fills,
   reconnects, position reconciliation, idempotency) is exactly what Nautilus does better than we
   ever should. `spine/venue.py` already encodes a `nautilus.<venue>` adapter naming convention —
   the seam is anticipated. Action: keep building paper on the custom adapters; when the first
   strategy clears 30-day forward and is armed for real capital, adopt Nautilus behind that seam for
   *execution only* (never the Gate/backtest). No work now beyond keeping the seam clean.

3. **Make scikit-learn an optional dependency behind the pure-Python logistic (and lean on the
   already-correct vetted-lib pattern elsewhere).** *(Robustness without losing determinism.)*
   The `ml/logistic.py` GD logistic powers meta-labeling and the survival ranker. Mirroring the
   `survival.py` optional-xgboost pattern — `try: from sklearn... except ImportError: <pure-python>` —
   buys a battle-tested optimizer/regularizer when sklearn is present while preserving zero-dep
   deterministic CI when it isn't. Lower stakes than #1 (these models are advisory, never gate or
   veto), but cheap and reduces a class of hand-rolled-numerics risk.

---

## Cross-check vs the standing buy-vs-build decisions (memory + DECISIONS.md)

| Prior decision | This audit |
|---|---|
| **MLflow NO-GO** (keep custom experiment-tracking) | **Confirmed.** `gate_verdicts` + `verdict_log.py` + per-combo persistence already serve this; MLflow adds nothing the per-combo BRUT trace doesn't. |
| **VectorBT SPIKE-IF >10k sweeps** (Modal pre-screen) | **Confirmed + refined.** Keep the honest engine; SPIKE vectorbt only as a fast pre-screen above ~10k variants, never touching the Gate. |
| **NautilusTrader BUY-WHEN-LIVE** (first 30-day forward survivor) | **Confirmed + pre-staged.** Now Top-3 #2; the `spine/venue.py` `nautilus.*` convention shows the seam is already anticipated. |
| **CrowdIntel NO-GO** (retroactive scores = look-ahead) | **Confirmed.** Nothing in the audit changes this; PIT discipline is enforced in `align_asof`. |
| **(NEW) Gate-stats parity-pinning** | **New highest-leverage item** — not previously captured. The hand-rolled PSR/DSR/PBO/CPCV are the one correctness gap a vetted reference should close. |

---

*Read-only audit. No code changed. Verdicts are recommendations for the operator; the locked Gate
constants and the per-combo BRUT model are untouched and remain the moat.*
