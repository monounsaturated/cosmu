# Cross-sectional crypto momentum — REAL edge that decayed OOS (not tradeable today)

**Date:** 2026-06-15 · **Script:** `apps/engine/scripts/research/xsec_momentum_study.py`
**Lens:** `xsec_momentum` (Jegadeesh-Titman / AQR "momentum everywhere")

## What was tested
Rank the 30 longest-history liquid Binance-spot crypto by trailing {30,60,90}d return each day (skip-1-day gap),
trade the spread t→t+1 on info known at t (PIT). Two portfolios:
- **neutral** — long top tercile / short bottom tercile, dollar-neutral, daily rebalanced (the true xsec spread).
- **longdecile** — long top decile equal-weight, fully invested, long-only (spot-friendly).

Real Binance daily klines 2018-06-11 .. 2026-06-14, median 25 live assets/day. MATIC delists Sep-2024 and
naturally drops from the rank (no forward-fill of dead assets — honest survivorship). Costs: 10 bps round-trip
charged on |Δweight| turnover (~0.17–0.33/day). Nulls: randomized-rank permutation **and** circular block-shift
(preserves each asset's own autocorrelation — the strong null for a near-trending signal). OOS split train≤2022-12-31.
Deflated Sharpe at the true trial count (6 = 3 lookbacks × 2 modes).

## Result
| config        | full SR | OOS SR | OOS t(mean) | beta→mkt | perm p | shift p | DSR p | TRADEABLE |
|---------------|--------:|-------:|------------:|---------:|-------:|--------:|------:|:---------:|
| neutral lb30  |   0.87  |  0.23  |   **0.43**  |  −0.05   | 0.000  |  0.001  | 0.807 |   **No**  |
| longdecile lb30| 0.85  |  0.72  |    1.33     | **+0.97**| 0.000  |  0.030  | 0.799 |   **No**  |

Benchmarks (OOS 2023+): EW buy&hold SR 0.47 · **BTC buy&hold SR 1.08** (ret +49%, DD −51%).

## Why it's NOT tradeable (the trap the naive gate fell into)
A naive gate (net+ ∧ full-null p<.05 ∧ OOS_SR>0.5) flagged longdecile TRUE. That is a **false positive**:

1. **The neutral spread is genuinely market-neutral (β=−0.05) and clears both full-sample nulls** — but its premium
   is concentrated in **2018-2021** (per-year SR 1.0→2.2) and **decays to nothing after**: 2024 SR 0.46, 2025 −0.13,
   2026 −2.3. OOS mean-return **t-stat = 0.43** → indistinguishable from zero. The full-sample null rejection is
   carried entirely by the rich early years; the live edge is dead. Classic post-publication anomaly decay.
2. **The longdecile "edge" is leveraged crypto beta, not alpha.** β=+0.97 to the equal-weight market, OOS alpha
   t-stat ≈ 1.0, −91% drawdown, and it **loses to a plain BTC buy&hold** (SR 0.72 vs 1.08, half the drawdown).
   "Buy whatever pumped, all-in" looks good only because crypto trended up; it carries no significant alpha.

## Honest gate (added to the script)
Beyond net+ and the full-sample null, a real edge must also pass:
- **OOS economic significance** — test-period mean-return t-stat > 2 (a rich early period must not carry it);
- **not-just-beta** — near market-neutral (|β|<0.3) **or** beats BTC buy&hold on OOS Sharpe.

Both candidates fail. **Verdict: cross-sectional momentum WAS a real, market-neutral edge in early crypto; it has
been arbitraged out by 2023+. Net-of-fee positive in aggregate, but no significant OOS premium today → do not deploy.**
Confirms the standing pattern: real signals show faint TRAIN strength that decays OOS.
