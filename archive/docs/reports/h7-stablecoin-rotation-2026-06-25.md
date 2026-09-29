# H7 — Stablecoin chain-rotation → native token

**2026-06-25 · EXPERIMENT ONLY · ZERO production impact** — offline event-study, persists nothing to prod,
no Gate constant touched, no behaviour changed. Docs-only PR; the code is the harness, not a wired strategy.

- Harness: `apps/engine/scripts/research/h7_stablecoin_rotation_2026_06_25.py`
- Raw numbers: `apps/engine/scripts/research/h7_stablecoin_rotation_results_2026_06_25.json`
- Self-contained table: `apps/engine/scripts/research/h7_stablecoin_rotation_table_2026_06_25.html`

## TL;DR — KILL

**N = 724 pooled events (only 177 non-overlapping) · sign + · pooled matched +115.2 bps net > 60 bps fee
hurdle · survives the naive placebo — but DIES on the decisive unconditional-drift disconfirmer (per-chain
lift Tron −11.0 bps, Solana +112.7 bps) and the Gate independently kills on PBO (0.571 > 0.50) → KILL.**

The headline 115 bps "edge" is **per-token beta, not a chain-rotation signal**. It fails the disconfirmer
that matters: a real rotation edge must beat *simply being long the native token unconditionally*, and must
**generalize** across the matched chains. On **Tron** — the strongest test, since ~28.5 % of all stablecoin
float lives on Tron — a top-tercile stablecoin-share *inflow* predicts TRX **worse** than TRX's own baseline
drift (event 72.6 bps vs unconditional 83.6 bps; lift **−11 bps**). The entire pooled edge is carried by
**Solana**, and SOL was the window's highest-beta momentum name whose stablecoin-inflow days coincide
*reflexively* with its own bull phases (price pumps → users bridge USDC onto Solana → share rises
*simultaneously*, not predictively). The naive placebo "survives" only because both TRX and SOL out-drifted
BTC over 2023–26 — exactly the confound the unconditional-drift test is built to expose.

This is a genuinely new negative: the **share-CHANGE derivative** (the carrier we pre-registered to dodge the
prior "on-chain LEVEL IC = cycle artifact" failure, see `orthogonal_data_round_2026-06-14`) is *not* subsumed
by the share level (change +115.2 bps vs level +63.9 bps) — yet it still does not survive the drift test. The
chain-rotation axis is dead at this horizon/threshold on a long-the-native-token read.

## The thesis (pre-registered, no sweep)

Stablecoin float **share** rotating **onto** a chain pre-positions on-chain demand before the under-covered
native token reprices. Use the **share-CHANGE** derivative (not the level) — that is what dodges the prior
on-chain-level cycle-artifact failure. Niche mid-tier chains = the attention moat. Direction: a top-tercile
14-day share **inflow** ⇒ **LONG** the matched native token. Pre-registered knobs, locked before any result —
**one** threshold, **one** horizon, **no** best-of-N:

| Knob | Value |
|---|---|
| Forward horizon | 5 days |
| Share-change window | 14 days (the derivative — the carrier) |
| Event | top-tercile dshare INFLOW, trailing 180-day, point-in-time cut (strictly before T) |
| PIT lag | `available_at = ts + 1 day`; enter on the T+1 close (mirrors the wired `stablecoin_eth_share`) |
| Matched chains | Tron→TRX, Solana→SOL (Base has no clean keyless native spot token → denominator only) |
| Reference price | Bybit keyless spot daily close |
| Fee | real Bybit 10 bps taker/leg + 5 bps slippage/leg → 30 bps round-trip all-in; **hurdle = 2× = 60 bps** |

## Data — REAL, point-in-time, keyless

Same free DefiLlama endpoint the wired `stablecoin_eth_share` feature uses
(`https://stablecoins.llama.fi/stablecoincharts/{Chain}`), parsed with the same `totalCirculatingUSD`
extraction as `cosmu/data/sources/stablecoin_flows.py`, and its exact PIT contract (`available_at = ts + 1`).
Native-token spot from the in-tree keyless `BybitSpotOHLCVProvider`.

| Series | Days | From | To | Last value |
|---|---|---|---|---|
| Stablecoin float — ALL chains | 3131 | 2017-11-29 | 2026-06-25 | $314B |
| Tron share / 14d-change | 2628 / 2614 | 2019-04-16 | 2026-06-25 | 28.54 % |
| Solana share / 14d-change | 1507 / 1492 | 2021-09-10 | 2026-06-25 | 4.91 % |
| Base share / 14d-change | 1046 / 1032 | 2023-08-15 | 2026-06-25 | 1.54 % |
| Bybit spot TRX / SOL / BTC | 999 each | 2023-09-30 | 2026-06-24 | — |

The token spot (Bybit caps ~1000 daily bars keyless) binds the testable window to ~2.7 yr
(2023-09-30 → 2026-06-24). Stablecoin share history is deeper and is used for the trailing-180d tercile
context that precedes the first tradeable event.

## The three honest checks — all PASS (necessary, not sufficient)

| Check | Value | Result |
|---|---|---|
| a — N ≥ 30 pooled events | 724 events (**but only 177 non-overlapping** ≥5d apart) | PASS |
| b — sign > 0 | pooled matched mean = **+115.2 bps** net | PASS |
| c — gross edge > 2× round-trip fee (60 bps) | 115.2 bps > 60 bps | PASS |

> 724 events with overlapping 5-day windows are **not independent** — the top tercile fires ~1/3 of days, so
> the forward windows overlap ~4×. That inflates the per-observation Sharpe (and is exactly why the Gate's
> PBO catches it below).

## Disconfirmers — where it dies

### Placebo-chain null (survives, but weakly)

The matched native token must be predicted **specifically** — not a mismatched/random token, not BTC.

| Forward-5d net mean | bps |
|---|---|
| Matched token (TRX/SOL) | **+115.2** |
| Mismatched token (cross-chain: Tron-event→SOL, Solana-event→TRX) | +47.6 |
| BTC (market beta) | +24.0 |

Matched > mismatched > BTC — so the naive placebo **passes**. But it passes only because both TRX and SOL
out-drifted BTC over the window. The naive placebo cannot distinguish a chain signal from per-token beta when
the matched tokens *are* the window's momentum winners. The next test exposes that.

### Share-CHANGE carrier check (passes)

| Forward-5d net mean | bps |
|---|---|
| Share-CHANGE event-set (the thesis) | **+115.2** |
| Share-LEVEL event-set (the prior failed axis) | +63.9 |

Change > level, so the derivative is not strictly subsumed by the level — the pre-registered carrier choice
is honest. Moot once the drift test fires.

### DECISIVE — unconditional-drift disconfirmer (per matched chain)

A real chain-rotation edge must beat **simply being long the token unconditionally** (its own forward-5d drift
over the window), and must **generalize** across the matched chains. Compared GROSS-to-GROSS:

| Chain → token | n | event-conditional gross | token unconditional drift | LIFT | net mean (incl. fee) |
|---|---|---|---|---|---|
| Tron → TRX | 360 | 72.6 bps | 83.6 bps | **−11.0 bps** | +42.6 bps |
| Solana → SOL | 364 | 216.9 bps | 104.3 bps | +112.7 bps | +186.9 bps |
| **pooled** | 724 | — | — | **+51.2 bps** | +115.2 bps |

On **Tron** — the strongest possible test (Tron holds ~28.5 % of *all* stablecoin float, the most "rotation"
to measure) — the signal predicts TRX **worse than its baseline drift** (lift **−11 bps**). The whole pooled
edge is one chain, **Solana**, where the share-inflow days are reflexively confounded with SOL's own bull
phases (the highest-beta name of the window). One positive-but-drift-confounded chain pooled against a
flat/negative one is precisely the per-token-beta artifact the naive placebo was too weak to catch.
**Fails generalization → KILL.**

## BRUT Gate (run anyway, for the record)

| Stat | Value | Gate | Result |
|---|---|---|---|
| Deflated Sharpe prob | 0.9996 | ≥ 0.95 | pass\* |
| PBO (CSCV, horizon family {3,5,7}) | 0.571 | ≤ 0.50 | **FAIL** |
| folds positive | 0.80 | ≥ 0.60 | pass |
| min trades | 724 | ≥ 30 | pass |
| **Gate verdict** | `killed_by = [pbo]` | | **FAIL** |

\* The 0.9996 DSR is an artifact of the inflated, overlapping N (724 vs 177 independent). The PBO correctly
flags the over-fit, and even if the Gate had passed, the drift disconfirmer is the binding KILL.

## Verdict — KILL (cleanly)

| | |
|---|---|
| N | 724 pooled (177 non-overlapping) |
| Sign | + (matched +115.2 bps net) |
| Placebo (matched vs mismatched / BTC) | matched +115.2 > mismatch +47.6 > BTC +24.0 — *survives naively, but it's beta* |
| Unconditional-drift lift | Tron **−11.0 bps**, Solana +112.7 bps → fails generalization |
| Gate | FAIL (PBO 0.571 > 0.50) |
| **GO / KILL** | **KILL** |

The chain-rotation thesis does **not** produce a tradeable edge at this horizon/threshold: the apparent
signal is the matched native token's own drift (negative on Tron, drift-confounded on Solana), the naive
placebo survives only because TRX/SOL out-ran BTC over 2023–26, and the Gate independently fails on PBO from
the overlapping-window N inflation. No production change; docs-only. The wired `stablecoin_eth_share` /
`stablecoin_net_flow_usd` features and their PIT contract are untouched and remain correct as ingested data.

### Honest caveats (what would NOT resurrect it)

- **Window is short and one-sided.** 2023-09 → 2026-06 was a TRX/SOL-favourable regime; a deeper token-spot
  history would only make the drift confound *more* visible, not less.
- **A market-neutral framing** (long the chain's native token vs short BTC, on the inflow signal) would strip
  the beta — but on Tron the *raw* signal already has negative lift, so there is no residual alpha to isolate;
  this is a kill of the signal, not just of the long-only packaging.
- **No sweep was run** and none should be: best-of-N over horizon/window/tercile would manufacture a survivor
  on Solana alone. The pre-registered single point already fails the generalization bar.
