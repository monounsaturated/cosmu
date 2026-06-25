# Edge Sprint — Consolidated Synthesis (2026-06-25)

> A full, honest, **zero-production-impact** edge hunt: two live themes + a 41-agent hypothesis workflow → 7 distinct experiments, all run on real keyless data through the locked BRUT Gate. Every testable hypothesis is now resolved. This is the single entry point; individual reports are linked at the bottom.

## TL;DR

- **Every testable signal died honestly** — on one of three walls: **cost**, **data-access**, or **genuine absence**. **Never** on the Gate being too strict. The deflation machinery (PBO, β-orthogonality, survivorship, expected-max-Sharpe) repeatedly caught false edges that looked real.
- **One survivor worth real money on a small test:** the **Polymarket intraday over-extension fade via MAKER execution, geopolitics-only** — the first edge in the sprint whose gross signal clears the Gate (DSR=1.0) and whose honest net stays positive after execution modelling.
- **One proven-but-unwoken lane:** **credibility/voices** — mechanically proven to separate skill from noise; dormant only because its voice panel is empty.
- Both next steps cross the zero-impact line (a live test / a prod wake) → **operator's call.**

## Scoreboard — every experiment

| Experiment | Verdict | Why it dies (or lives) |
|---|---|---|
| Xsec-momentum (long-only, daily) | ❌ reject | buy-and-hold beta + <30 trades |
| Xsec-momentum (market-neutral, dense, low-turnover) | ❌ **uneconomic** | gross +53–89% real, **turnover cost eats 100%+**, 0/16 clear the Gate |
| H3 cross-venue funding divergence | ❌ clean negative | spread doesn't revert (−19.8 bps); fails fee hurdle |
| H8 signed liquidation skew | ⚠️ **data wall** | N=0, no reachable signed-liq feed |
| H7 stablecoin chain-rotation → token | ❌ KILL | per-token beta, not rotation (PBO 0.571 catches the over-fit) |
| H5 basis-momentum carry | ❌ KILL | β-clean but α = −40%/yr; closes a 2nd crypto-majors family |
| H9 Polymarket long-shot theta-decay | ❌ KILL | survivorship YES-tail eats the NO-harvest; no decay |
| **Polymarket INTRADAY over-extension (taker)** | ❌ KILL (taker) | **gross edge REAL, clears Gate (DSR 1.0)** — taker spread eats 2–6× |
| **Polymarket INTRADAY over-extension (maker)** | ✅ **worth a live test** | maker-net **+1.0 to +3.1c/$1** (exp +1.7), geopolitics-only, clears Gate |

## Why everything died — the three walls

1. **Cost.** The crypto cross-sectional momentum premium is *real and large* (gross +53–89%), but two-leg taker + liquidity slippage at our fee tier consumes all of it. Lowering turnover starves the thin signal faster than it saves cost. Basis-momentum is outright negative-α. → public crypto **price-derived** signal space is effectively exhausted.
2. **Data-access.** Signed liquidations have no reachable keyless feed; the shipped `liquidation-cascade-zscore-v1` feature is also direction-blind (sums the legs). Polymarket hourly odds exist but only via windowed requests.
3. **Genuine absence.** Funding divergence doesn't revert; long-shots don't decay; stablecoin-rotation is disguised beta.

The Gate never over-rejected. It **validated itself**: PBO caught H7's overlapping-window over-fit, β-orthogonality proved H5 wasn't a beta artifact (and still killed it), the survivorship control killed H9's lottery-ticket mirage, and expected-max-Sharpe deflation held throughout.

## The one live candidate — Polymarket intraday over-extension (maker)

- **Signal is real and gated.** Fade a ≥2.5σ intraday (3h) over-extension, exit in 6h, never inside the final 48h. Gross +0.70c/$1 pooled (+1.62c sports), N≈3,100 events, clears the BRUT Gate at DSR=1.0, all three leakage disconfirmers pass (PIT, not-trend-toward-truth, spread-honest).
- **Taker dies, maker lives.** Taker pays ~one full spread (median 1c / mean 2.9c from 1,345 live books) → net −2.86c. A maker earns ~the half-spread back; honest net **+1.0 to +3.1c/$1 (expected +1.7c)**, positive across the worst/expected/best fill band. The **no-spread-credit floor is still positive** (adverse fills enter at a deeper, better level) — so it is not merely an artifact of assuming spread capture.
- **Honest constraints.** Carried by **geopolitics (0% fee)**; sports (3%) goes net-negative. The "no-fill tax" forfeits the best immediate-reverters. Exact queue position / partial fills / own-size impact are **unknowable offline** → only a small **live passive-order test** confirms the fills materialize. (P(aggressor=BUY | price↑)=0.89 confirms adverse selection is real.)
- **Next step:** a small geopolitics-only forward maker test with a passive-order fill log + pre-set success/kill criteria. Needs the held [#393](https://github.com/monounsaturated/cosmu/pull/393) (hourly odds ingest) + a UMA resolution join.

## The second candidate — credibility / voices

Mechanically proven (offline dry-run): separates a "sniper" (early+right, skill 0.70) from a "spammer"/"follower" (0.00); a lead-lag-symmetry test kills the echo. Runs today (`XAI_API_KEY` + `OPENROUTER_API_KEY` already present; Reddit/RSS keyless). Dormant only because `VOICE_PANEL` is empty and it needs a schedule slot. Non-price, segmentation-moat — the one untested *kind* of signal. Waking it is a prod change (a panel + a schedule).

## Surfaced prod bugs (captured as chips, not fixed under no-impact)

1. `KrakenFuturesFundingRateProvider` — stale URL + wrong field parse → silently returns `[]`.
2. `liquidation-cascade-zscore-v1` — direction-blind (sums long+short legs) **and** data-starved (0 rows ever ingested; cron silently failing).

## Decision map — all four cross the zero-impact line

| Option | Needs | Promise |
|---|---|---|
| 🥇 Wake credibility/voices | a voice panel + a schedule (prod change) | proven mechanism, non-price moat, cheap |
| 🥈 Polymarket intraday maker | a small live/forward maker test (+ #393 + UMA join) | proven gross edge; honest net positive geopolitics-only |
| 🥉 Build H1 (weather) / H2 (resolution-lag) | a forecast-archive / CLOB-depth feed | untested; leak-prone; heavier |
| 🛠️ Structural cost levers | maker/VIP fee tier; delisted-inclusive R2 universe | recover the real-but-uneconomic xsec premium |

## Appendix — reports & PRs

Slate: `edge-hypothesis-slate-2026-06-25.md` (#392). Experiments: edge-hunt (#390), market-neutral (#391), low-turnover (#396), H3 (#394), H8 (#395), H7 (#397), H5 (#398), H9 (#399), intraday taker (#400), maker feasibility (#401). Foundations: leakage tripwire (#387), Polymarket/credibility scouts (#385/#386/#388/#389). All docs-only or held; Gate untouched throughout.
