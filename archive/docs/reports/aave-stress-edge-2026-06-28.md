# Aave on-chain money-market stress → 24–72h vol-cascade lead — research verdict

**Date:** 2026-06-28 · **Axis:** next-data-axis #2 (Aave / on-chain money-market stress) · **Branch:** `claude/aave-stress-edge-2026-06-28`
**Module:** `apps/engine/cosmu/research/aave_stress.py` · **Test:** `apps/engine/tests/test_aave_stress.py` (11 passing)

## VERDICT: KILL — wall: `no_signal`

The pre-registered hypothesis does **not** survive. An Aave money-market stress spike does **not** lead a
tradeable 24–72h vol cascade on the majors after costs. **It does NOT add IC over trailing realized-vol + funding
controls** (the partial IC is ~0 / negative). **DO NOT MERGE — autonomous-run experiment.**

---

## The pre-registered hypothesis (fixed before looking)

- **H1:** an Aave stress spike (stress z-score > **1.5** on day *t*) leads an elevated realized-vol / drawdown
  cascade on crypto majors over the next **3 days (24–72h)**. Direction: stress → risk-OFF.
- **The trade (maker-feasible, spot, long-only de-risk overlay):** hold the major long by default; on a stress
  spike, **step OUT (flat) for 3 days**, then re-enter. Every step-out / step-in is a LIMIT (maker) fill charged
  the real **Binance maker fee = 10 bps/side** (`spine/venue.py` catalog, not a magic number).
- **Pass bar:** each (symbol × venue) cell must clear the **LOCKED BRUT Gate** (`metrics_for_run` → `promote_brut`,
  `GateSettings` defaults, judged BRUT on its OWN streams) net of the maker fee, **AND** beat all three
  disconfirmers below.

## Data

| series | source | coverage | PIT status |
|---|---|---|---|
| Aave stress proxy | DefiLlama yield chart (**keyless**), mean **supply APY** across the 4 major v3-Ethereum pools (USDC/USDT/WETH/WBTC) | ~1230 daily pts, 2023-02 → 2026-06 | **PIT-COMPROMISED** (see below) |
| BTC/ETH daily bars | local Binance spot cache | 1024 bars, 2023-09 → 2026-06 | PIT (real OHLCV) |
| funding control | local Binance perp funding cache | BTC from 2024-06 (partial → control degrades to vol-only on the early span, honest) | PIT |

## Results (REAL data, net of 10 bps maker fee)

| cell | promoted | DSR | net return | Sharpe | maxDD | trades | raw IC | partial IC (over vol+funding) | shuffle passes | lag passes | gate reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT × binance | **no** | 0.8914 | +0.8809 | +0.732 | 0.418 | 56 | **−0.088** | **−0.046** | no | no | max_drawdown, pbo, deflated_sharpe, buy_and_hold |
| ETHUSDT × binance | **no** | 0.5776 | −0.2843 | +0.117 | 0.755 | 56 | −0.004 | +0.015 | no | no | max_drawdown, folds_positive, pbo, deflated_sharpe, buy_and_hold |

Spikes: 97 stress spikes (z > 1.5) over 1024 bars per symbol (~9.5% of days — supply APY is fat-tailed/clustered).

### Why it fails
- **No cell clears the BRUT Gate.** BTC gets the closest (DSR 0.89 < 0.95) but still **loses to buy-and-hold**,
  breaches the 0.25 max-drawdown bar (0.42), and fails PBO. ETH is outright **negative** net.
- The de-risk overlay's whole premise is that stepping out around a stress spike avoids a forward-vol cascade.
  Instead it mostly steps out of *upside* (buy-and-hold beats it), i.e. the stress spike does not select for
  forward downside/vol.

## Required disconfirmers (the experiment's teeth)

**(a) IC over trailing-vol + funding controls — FAIL (the decisive one).**
Partial Spearman IC of the stress z-score vs. realized forward 3-day vol, after residualizing out trailing
realized vol + funding: **−0.046 (BTC), +0.015 (ETH)** — both ~0. The raw IC is also ≈0/negative (−0.088, −0.004).
**The stress signal carries no positive forward-vol information, with or without the controls.** Even if it had,
the partial IC says there is nothing left once you know trailing vol — it would be a repackaged vol proxy.

**(b) Shuffle + lag placebos — pass (vacuously, but clean).** Neither the shuffled nor the +17-day-lagged stress
series promotes a cell either. Consistent with the real signal also being non-predictive (no spurious structure to
exploit). No false-positive risk.

**(c) PIT honesty — PROVISIONAL / compromised.** See below. Moot here because the verdict is a KILL — a signal that
cannot clear the Gate on the *recompute-friendly* DefiLlama series will not clear on a stricter block-timestamped
one.

## PIT assessment (honest, per the brief's warning)

The brief mandated the **Aave subgraph** (block-timestamped, immutable) for the stress metric and flagged DefiLlama
as PIT-compromised. At experiment time:

- The **Aave subgraph is unreachable keyless**: the legacy hosted subgraph is dead (HTTP 301), and the
  decentralized Graph gateway returns `auth error: missing authorization header`. **There is no Graph API key in
  `.env.local`.**
- The only reachable keyless on-chain stress series is **DefiLlama's yield chart**, which is **PIT-compromised**:
  it backfills/recomputes history and its yield-chart timestamps are scrape-times, not block times. Its
  **borrow-side / utilization history (`chartLendBorrow`) is paywalled** ("Upgrade to the paid API plan"), so the
  utilization metric the thesis really wants is not even available keyless — the proxy used is the **supply-APY
  spike** (a faithful proxy since supply APY ≈ borrow APY × utilization × (1 − reserve factor)).

So this run is **PIT-provisional by construction**. The KILL stands regardless (a stricter, block-timestamped
source cannot rescue a signal whose IC over trailing vol is already ~0), but the axis cannot be *confirmed* as a
true edge here without the subgraph.

## Modal run warranted?

**No.** This is a clean local KILL: no cell clears the Gate, the partial IC over vol/funding is ~0, and the signal
is essentially noise w.r.t. forward vol. Scaling to more symbols / a Modal sweep would only manufacture
multiple-testing risk on a non-signal. **Do not spend compute here.**

The honest unblock if this axis is ever revisited: a **Graph API key** to read the block-timestamped Aave subgraph
(supply + borrow + utilization, PIT-clean), then re-test the *utilization/LTV-stress* metric directly (the supply-APY
proxy used here is a second-best). Given the ~0 IC even on the recompute-friendly proxy, expected value is low.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
