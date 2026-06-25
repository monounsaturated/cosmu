# H5 — basis-momentum carry (d(basis)/dt cross-sectional book) — 2026-06-25

**EXPERIMENT ONLY. Zero production impact.** No Gate constant touched, no prod wiring, nothing persisted to any
store, nothing merged that changes runtime. This is one findings report + a disposable self-contained HTML table +
the harness script. Slate item **#6 (H5)** from `docs/reports/edge-hypothesis-slate-2026-06-25.md`; sits alongside
`docs/reports/edge-hunt-mktneutral-2026-06-25.md` (which confirmed crypto **price** xsec-momentum is uneconomic).

## The hypothesis (slate #6, pre-registered)

> Ride an **accelerating** perp-spot basis. Leverage build-up **trends for days**, so the tradeable signal is the
> **time-derivative `d(basis)/dt`**, NOT the level (level-fade was already tested). Because this is a different
> signal **family** from price-momentum, it is *not mechanically blocked* by the just-confirmed "crypto xsec
> price-momentum is uneconomic at our cost tier" result. The honest open question: is basis-momentum a **real**
> carry/positioning edge, or just **disguised price-momentum / bull-beta** wearing a basis mask?

**Decisive disconfirmer (pre-registered in the slate):** regress the strategy's returns on buy-and-hold (BTC),
require **residual α > 0 net of fees**. **Kill if α collapses to β.**

## Answer: **KILL.** 0 / 12 survivors. The β-test rules out the beta trap — but the residual α is *negative*.

This is a **cleaner-than-usual reject**, and the prior called it: crypto carry/basis on liquid majors is arbitraged
out, and chasing its *acceleration* loses **net of fees** — and even **gross**, the spread has *negative* skill once
it is genuinely beta-neutral. The β-orthogonality test did exactly its job: it cannot be dismissed as "just bull
beta", because the book provably has none.

## How it was tested (faithful to the registered PIT feature; honest costs)

- **Basis, reconstructed the honest way.** The production provider (`cosmu/data/providers/onchain.BinanceBasisProvider`)
  computes the registered tier0 `perp_spot_basis` as `(mark − index) / index` with `available_at == observation
  time` (no look-ahead). That provider only ever fetches the **current** snapshot — there is **no historical basis
  series** in any store. To get ~3.65 yr offline, the harness fetches **both legs** keyless from Bybit v5 (paginated
  `spot` + `linear` perp klines), intersects on common bar timestamps, and computes
  `basis_t = (perp_close_t − spot_close_t) / spot_close_t` — the **same `(mark−index)/index` shape**, evaluated
  strictly at bar close (PIT: a bar's basis is only knowable once the bar has closed; signal at bar *i* trades the
  *i→i+1* forward return, never the same bar). Measured mean |basis| ≈ **4.6–8.0 bps** per name — a sane, real basis.
- **Signal.** `basis_momentum_t = basis_t − basis_{t−LB}` (the discrete d(basis)/dt over LB bars), then
  **cross-sectionally z-scored** across the universe each bar (PIT — only names present at that bar). Long the
  top-z names (basis accelerating most positively), short the bottom-z (most negatively). Market-neutral by
  construction.
- **Pre-registered headline config (fixed before any result):** **LB = 6 bars (24 h)**, **quantile = 0.33 (tertile
  legs)**, **rebalance every 6 bars (~daily)**. A 12-cell diagnostic grid (LB ∈ {3,6,12} × q ∈ {0.20,0.33} ×
  cadence ∈ {6,12}) is also run, but **only** to give the Gate's own-overfit deflation (DSR/PBO) an honest trial
  count — the **GO/KILL verdict is read off the one pre-registered cell**, never the grid's best.
- **Costs (the same honest floor as the mkt-neutral run).** Binance taker (10 bps) + liquidity-tiered slippage on
  **both legs'** turnover each rebalance, plus **real Binance funding** (PIT, 4h accrual) on each held leg (long pays,
  short receives).
- **Data realized:** **12 names × 7,999 × 4h bars/leg = 1,333 days ≈ 3.65 yr**, common-windowed. Funding coverage is
  real on 11/12 names (ATOMUSDT had no cached funding → 0 accrual, handled honestly; basis/price legs intact, so the
  cross-sectional rank is unaffected — basis is computed from price, not funding).
- **Scoring.** Each config's **own** equity curve scored **BRUT** through the **locked** Gate (DSR ≥ 0.95, PBO ≤ 0.50,
  folds ≥ 0.60, min_trades ≥ 30, holdout DSR > 0, beat-benchmark = cash/0 for a neutral book), with `TrialStats(count
  = grid size, sr_correlation = ρ̄)` — the legitimate per-book deflation. PBO is the true CSCV across the grid. Champion
  confirmed on its **own embargoed holdout** (last 20%, boundary bar dropped). **Plus** the decisive β-regression.

## The numbers (pre-registered cell, then the wall each leg of the thesis hit)

**Pre-registered cell `bybit:240:lb6:q0.33:reb6`:**

| metric | value | read |
|---|---:|---|
| N (leg trades) | **11,882** | min_trades floor (30) never binds — trade-count is a non-issue at 4h |
| net book return | **−0.817** | loses badly after two-leg cost |
| gross book return | **−0.101** | **loses even cost-free** — the spread itself has the wrong sign |
| residual **α** (annualized, net of fees) | **−0.398 / yr** | **NEGATIVE → KILL** |
| **β to BTC** | **−0.016** | ≈ 0 — genuinely market-neutral |
| α **t-stat** | **−2.46** | the negative skill is *statistically real*, not noise |
| corr to BTC | **−0.021** | ≈ 0 — confirms no disguised beta |
| DSR | 0.001 | nowhere near 0.95 |
| holdout DSR | −0.484 | fails the embargoed exam too |

**Across all 12 grid cells:** DSR ∈ [0.000, 0.019], **every** cell net-negative, **every** cell α < 0 (range
−0.27 to −0.75 /yr), **every** β-BTC ∈ [−0.02, +0.04], **every** corr-BTC ∈ [−0.02, +0.04]. PBO = 0.33 across the
grid (the configs are not over-fit to each other; they consistently, genuinely lose).

### The decisive β-orthogonality test — and why this reject is *clean*

The slate's kill-condition was "α collapses to β". **It did not** — there was never any β to collapse into:
**β-BTC ≈ 0 and corr-BTC ≈ 0 on every cell.** The book is *provably* market-neutral. That **rules out the
bull-beta failure mode** that killed price xsec-momentum (#390/`edge-hunt-mktneutral`). So the result cannot be
hand-waved as "same beta trap in a new mask."

What kills it instead is the **other** branch of the disconfirmer: the residual α is **negative and significant**
(−40 %/yr, t = −2.46). Basis-momentum on liquid majors does not have *zero* skill — it has *negative* skill. Names
whose basis is accelerating up underperform names whose basis is accelerating down, over the next bar, even gross.
Economically sane: an accelerating positive basis is **late-stage crowded leverage** (it tends to mean-revert /
get liquidated), so chasing the acceleration buys exactly the names about to unwind. Layer ~11.9k leg-trades of
two-leg cost on a −10 % gross spread and you reach −82 % net.

## Verdict

**KILL — basis-momentum carry has no exploitable edge on liquid crypto majors at our cost tier.** Stated plainly,
per the brief: the residual α did not collapse to β — it is *negative outright* (−40 %/yr, t = −2.46), and the
gross spread is negative before any cost. The β-orthogonality gate worked perfectly and shows this is **not** a
disguised-beta artifact. This **confirms the prior** ("carry/funding/basis largely arbitraged to ~0 by 2026") and,
together with `edge-hunt-mktneutral`, closes a second crypto-majors signal family as uneconomic.

**Do not** pursue: more basis/carry variants on the same liquid-majors universe, longer/shorter d(basis)/dt windows,
or a level+derivative combo (level-fade is already tested; the derivative is negative-skill). The basis *level* and
*derivative* both point the same direction — away from a tradeable edge here.

**The one honest open door (not pursued here, flagged for the slate):** the negative α is *real and significant* —
which means the **sign is informative**. A basis-momentum **reversal** (fade the acceleration: short accelerating-up,
long accelerating-down) is the mirror book and would have *positive* gross α, but it inherits the same ~11.9k-trade
turnover, so it is almost certainly still cost-killed — and it is a *level-fade-adjacent* idea already covered by the
"basis level mean-reverts" prior. Worth a one-line confirm only if a *much* lower-turnover (weekly, top/bottom-1)
construction is tried; not worth a full slate slot on this universe. The more promising frontier remains thinner,
less-arbitraged markets and orthogonal (non-price-derived) data — not another transform of the basis.

## Reproduce

```
cd apps/engine
APP_ENV=test python3 scripts/research/h5_basis_momentum_2026_06_25.py        # fetch + score (keyless, ~1 min)
python3 scripts/research/h5_basis_momentum_make_html.py                       # render the table
```

Artifacts (all under `apps/engine/scripts/research/`): `h5_basis_momentum_2026_06_25.py` (harness),
`h5_basis_momentum_make_html.py` (renderer), `h5_basis_momentum_results_2026_06_25.json` (every config's numbers),
`h5_basis_momentum_table_2026_06_25.html` (disposable table).
