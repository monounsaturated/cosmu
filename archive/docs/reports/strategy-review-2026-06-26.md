# Strategy Population Review — 2026-06-26

**Read-only snapshot of PROD** (Supabase `strategy_versions` / `tracks` / `gate_verdicts` /
`backtest_symbols` / `events`). One question answered for the solo operator: *what's alive,
what's dead, and WHY each is where it is.*

## TL;DR

| Bucket | Count |
|---|---|
| **PAPER** (forward-testing now) | **10** |
| **LIVE** (real money) | **0** |
| **SCREENED** (in-flight, not yet paper) | 77 |
| **KILLED** (rejected) | 1370 |

- **Who's alive:** the **equity-TAA cohort** — 10 documented tactical-asset-allocation
  strategies (DAA / VAA / ADM / GEM / PAA / GTAA / TSMOM / Sector-Mom / Risk-Parity / Dual-Mom),
  all `kind=quant`, armed to paper **2026-06-14 18:13 UTC** (~11 days forward). They are the
  **only** survivors of the locked Gate, and their forward marks were just repaired to honest
  values by #427.
- **Why the rest are dead:** 1370 versions killed, **0** sole-`buy_and_hold` kills — every kill
  is a real statistical/data failure. The biggest single cause is the **data wall**
  (`min_trades` / `min_trades_per_symbol` = 613) — most crypto-price ideas simply don't generate
  enough independent trades on the available history to be judged. The rest die on the real edge
  stats (Deflated-Sharpe / PBO / holdout / folds). **This is the Gate working as designed.**

---

## (1) CURRENTLY PAPER — 10 versions (the equity-TAA cohort)

All 10 are `kind=quant`, `origin=documented` (classic published TAA rules, not generated), each
seeded at **$1,000** paper capital. They were promoted backtest→paper as a block on
**2026-06-14 18:13 UTC** — the moment they cleared the full 0.95 Gate on the NATIVE multi-asset
monthly universe (the project's *first* Gate survivors). Marks below are the **honest forward
equity** after the #427 repair, sorted best→worst.

| Strategy | Scope | Forward equity | Return | Why it's PAPER |
|---|---|---:|---:|---|
| Vigilant Asset Allocation (Keller VAA-G4 Aggressive) | EEM / ibkr | $1,052.18 | **+5.22%** | Passed full Gate 06-14; best forward performer of the cohort |
| Dual Momentum (QQQ/EFA tech-tilt) | QQQ / ibkr | $1,016.06 | +1.61% | Passed full Gate 06-14 |
| Defensive Asset Allocation (Keller DAA top-6) | portfolio (multi-ETF) | $1,015.97 | +1.60% | Passed full Gate 06-14 |
| Protective Asset Allocation (Keller PAA1 top-6) | portfolio (multi-ETF) | $1,004.48 | +0.45% | Passed full Gate 06-14 |
| Risk Parity (Inverse-Vol SPY/AGG/GLD, Monthly) | portfolio (multi-ETF) | $998.33 | −0.17% | Passed full Gate 06-14 |
| Accelerating Dual Momentum (ADM / Engineered Portfolio) | SPY / ibkr | $995.59 | −0.44% | Passed full Gate 06-14 |
| Global Equities Momentum (GEM / Dual Momentum) | SPY / ibkr | $995.59 | −0.44% | Passed full Gate 06-14 |
| Sector-Momentum Rotation (TAA / Top-3 SPDR + SPY-200SMA) | portfolio (multi-ETF) | $995.17 | −0.48% | Passed full Gate 06-14 |
| Diversified Time-Series Momentum (TSMOM Trend / 5-ETF) | portfolio (multi-ETF) | $994.93 | −0.51% | Passed full Gate 06-14 |
| Faber GTAA (5-asset 10mo SMA timing) | portfolio (multi-ETF) | $990.10 | −0.99% | Passed full Gate 06-14 |

**Reading the numbers:** ~11 days of forward paper is *noise, not signal* — the spread
(−0.99% to +5.22%) is within what 11 days of low-frequency monthly-rebalance ETF strategies can
do by chance. These are slow strategies; the forward test is a multi-month scan-immune gate, not
an 11-day verdict. The point of this stage isn't the P&L yet — it's that the marks now move
**honestly** (born with no backtest-OOS seed leak) so the eventual forward number is trustworthy.

*Note:* the cohort predates the per-symbol `backtest_symbols` table, so they have no rows there —
they were judged as a documented cohort via `equity_taa_cohort.py`, not the finder's per-cell path.

## (2) CURRENTLY LIVE — NONE (confirmed)

- `strategy_versions` with `status='live'`: **0**
- `live_toggle` global row: **`enabled=0`** (disabled since 2026-06-01)
- All **43** `executions` rows are `is_paper=1` (33 ibkr paper + 10 binance testnet). Zero real fills.

This is correct and by design: **arming live is a manual human action.** The Gate grants
*eligibility*; the operator clicks launch. Nothing has been launched. (Events confirm: 1
`live_defunded`, 2 `live_rules_set`, **0** live arming/fill.)

## (3) OLDER / KILLED / REJECTED — 1370 killed + 77 screened

### Kill-reason taxonomy (1370 killed versions)

| Category | Count | What it means |
|---|---:|---|
| **Data wall** (`min_trades` / `min_trades_per_symbol` only) | **613** | Idea didn't generate enough *independent* trades on available history to be judged at all — not "no edge," but "can't measure an edge." Biggest single cause. |
| **No passing cell** | 217 | Tested across the symbol×venue grid; **0** cells survived the per-cell BRUT gate. |
| **Gate statistics** (Deflated-Sharpe / PBO / holdout / folds / max-DD) | 523 | A measurable edge that **failed** the multiple-testing-corrected significance bar after fees. The honest "we looked, it isn't real" bucket. |
| Dedup / superseded (`*_dedup`) | 16 | Duplicate watch-tracks collapsed; not a quality verdict. |
| Legacy / other | 1 | One pre-reform `legacy_validating_gate_fail`. |

**Key honesty check — `buy_and_hold` is NEVER the sole killer:** it appears in 265 kill strings
but in **0** cases alone. Consistent with the eval-reform finding that B&H was demoted from a
gatekeeper to a tie-breaker — nothing is killed *just* for failing to beat buy-and-hold.

### What was actually tried (killed-version name/thesis themes)

The killed population is overwhelmingly the **crypto-price edge-hunt** — the ideas the operator
and the finder generated and the Gate honestly refused:

| Theme | Killed | | Theme | Killed |
|---|---:|---|---|---:|
| RSI | 668 | | volatility | 214 |
| mean-reversion | 427 / 247 | | prediction-mkt | 196 |
| momentum | 412 | | carry | 116 |
| breakout | 378 | | sentiment | 109 |
| funding | 236 | | squeeze | 105 |
| ORB / FVG | 168 / 164 | | polymarket | 101 |

(Counts overlap — one strategy can hit several themes.) Every flagship "find a crypto edge" theme
from the research memory — momentum, funding-contrarian, ORB+FVG breakout, squeeze-release,
prediction-market — is here, tested and killed honestly.

### Kill timeline — the finder is running continuously

Kills cluster from 2026-06-16 onward (112 / 80 / **370** / 95 / 68 / 164 / 87 / 63 / 64 / 68 / 53
per day through 06-26). This is the autonomous finder + FarmLoop generating cohorts daily and the
Gate rejecting them at scale — exactly the intended "generate wide, let the Gate refuse" loop.

### Gate verdicts (cohort-level)

90 `gate_verdicts` rows, **all `decision=FAIL`** (every run `n_promoted=0`). Example: an
"ORB + FVG-multiple" cohort with `best_deflated_sharpe_prob=0.0014`, `net_profit=-1.45`,
failing `folds_positive` + `deflated_sharpe` + `fdr`. The Gate has promoted **nothing** through
the finder path — the only survivors (the 10 TAA strategies) came in via the documented-cohort
path, not the finder.

### The 77 SCREENED (in-flight, not yet judged)

Backtested-but-not-promoted candidates, growing daily (12 created 2026-06-26). Current batch is
the crypto edge-hunt: *Momentum trailing-stop runner*, *Breakout scale-out runner*, *DeFi-flow
risk appetite*. These have **zero-capital watch-tracks** (33 tracks at `cap=0`) — the rejects-watch
/ Type-II measurement lane that records what the Gate refused *without* spending capital, so we can
detect if the Gate is over-rejecting. One stale watch-track shows `ret=21.55%` (a $1,000→$1,215
paper line last updated 06-08) — it is **not** funded; it is a measurement artifact, not a live bet.

## (4) THE HONEST STORY (4 lines)

1. **The Gate refuses almost everything by design, and it's working:** 1370 killed, 90/90 cohort
   runs FAIL, 0 finder promotions — and not one kill is a soft "didn't beat buy-and-hold." Every
   rejection is a real data wall or a real failed-significance verdict after fees.
2. **The crypto-price edge ideas were all killed honestly:** momentum, funding, breakout, ORB/FVG,
   squeeze, prediction-market — every flagship theme was generated, tested, and refused. "0 crypto
   survivors" is the machine telling the truth, not a bug.
3. **TAA is the one proven survivor:** 10 classic documented tactical-asset-allocation strategies
   cleared the full 0.95 Gate on 2026-06-14 and are now forward-paper-testing on ETFs (ibkr). They
   are the entire alive population because they are the only edge that survived honest scrutiny.
4. **Nothing is live, and that's correct:** the Gate grants eligibility; the human arms live. The
   operator hasn't armed anything, so the population is exactly: 10 proven-but-young paper
   strategies, a continuously-churning kill pile, and an empty live book waiting on a human click.

---
*Generated read-only from PROD on 2026-06-26. No data was modified. Forward marks reflect the #427
honest-mark repair (cohort armed-to-paper 2026-06-14 18:13 UTC, ~11 days forward at snapshot).*
