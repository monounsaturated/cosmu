# Edge-Hypothesis Slate — ranked research backlog (2026-06-25)

> **Findings only, zero production impact.** Produced by a multi-agent workflow (41 agents, 32 hypotheses generated across 8 edge lenses → adversarial critique → 9 survived → 7 distinct experiments). Complements the three real experiments run the same day: the [edge hunt](edge-hunt-experiment-2026-06-25.md) (0/126 survivors — long-only loses to B&H beta + <30 trades on daily), the [Polymarket trust experiment](polymarket-trust-experiment-2026-06-25.md) (PIT-clean data, daily wiring is the wall), and the [credibility dry-run](credibility-dryrun-2026-06-25.md) (the voices lane separates skill; the panel is empty).

## Convergent finding

The binding constraint is **not** data acquisition, plumbing, or leakage. It is two cheap things:

1. **Surfacing a derived feature the codebase currently throws away** — the cross-venue funding *spread*, the *signed* liquidation legs (shipped feature wrongly *sums* them), the stablecoin share-*change* derivative, the basis time-*derivative*.
2. **Clearing the 30-trade floor by pooling into baskets / shrinking the bucket interval**, rather than per-cell entries.

Every strong survivor exploits a **segmentation or attention moat** — KYC-siloed funding arbs, small-cap forced-flow nobody watches, under-covered mid-tier chains, reg-grey Polymarket categories desks ignore — i.e. *who can't or won't compete*, **never speed**. And each carries a **named, runnable disconfirmer** (placebo-chain, placebo-lag, β-orthogonality, Brier-OOS) that isolates the real edge from a beta/leakage artifact *before* the Gate — exactly where the prior round's blow-ups lived.

## Ranked top experiments

| # | Title | Mechanism | Data (keyless?) | Why high-leverage | Smallest <1-day kill experiment |
|---|-------|-----------|-----------------|-------------------|---------------------------------|
| **1** | **Cross-venue funding divergence** | Fade the perp venue whose 8h funding is the outlier vs cross-venue median; spread mean-reverts as KYC-siloed arbs slowly close it | **Yes** — all 3 funding providers (Binance/OKX/Kraken-Futures) already ingested, `available_at==ts`, no revision; new feature = `funding − cross_venue_median`, z-scored | Cleanest PIT story, zero new data, orthogonal to the entire failed single-venue funding-LEVEL set, pure venue-segmentation moat; 30-trade floor solved by basket pooling | Offline z-score across ~10 overlapping perps, 2yr; label each \|z\|>2 by forward N×8h Kraken-spot return. Check ≥30 pooled entries, reversion sign, gross edge > 2× round-trip fee. One pre-registered z+window, no sweep |
| **2** | **Liquidation asymmetry snap-back** | Fade the side that got wiped — `long_liq ≫ short_liq` exhausts one side of the small-cap perp book → overshoot reverts | **Yes** — both legs in the same keyless Coinglass payload; shipped feature wrongly *sums* them; only a 2-leg surfacing edit | Tiny code delta, proven-PIT source, captures the short-squeeze exhaustion the long-only total spec is blind to and can buy into | Re-parse Coinglass at 4h/8h, signed `liq_skew`, event-study forward 1–2 bar on small-caps. Check N≥30 and snap-back sign before any spec |
| **3** | **Stablecoin chain-rotation → native token** | Stablecoin float share rotating ONTO a chain pre-positions on-chain demand before the under-covered native token reprices | **Yes** — DefiLlama `/stablecoincharts/{Chain}`, same +1d PIT contract as wired `stablecoin_eth_share`; extend to TRON/Solana/Base | Exogenous liquidity signal, share-CHANGE derivative dodges the "on-chain level IC = cycle artifact" failure, niche mid-tier chains = moat | 2yr TRON/SOL/Base share series, 14d share-change tercile crossings; forward-return on matched native token vs **placebo-chain null**. Kill if it survives placebo or N<30 |
| **4** | **Polymarket resolution-convergence decay** | Long-shot YES on dated binaries theta-decays toward 0 as deadline nears; retail lottery-buyers don't time-decay probability | **Yes** — CLOB keyless, odds-ingest + BRUT per-market gate wired; backfill resolved `conditionId`s | Fully-built ingest+gate path, PIT-safe (deadline fixed at creation), reg-grey/no-desk moat | Backfill resolved long-shots in 0%-fee geopolitics + 3% sports (exclude 7.2% crypto); measure realized YES decay vs entry net of category fee. Kill if net decay < fee or <30 trades/category |
| **5** | **Recurring-market forecast gap** | Calibrated NOAA/open-meteo ensemble beats retail-eyeballed odds on REPEATING scheduled Polymarket binaries | **Partly** — open-meteo keyless but must wire `historical-forecast` (forecast-issued-as-of), not the reanalysis answer-key | Highest edge_fit (5), genuine weak-signal niche retail market; but make-or-break is unbuilt + a live leakage trap today | Calibration pre-gate only: wire forecast-archive with `available_at`=issue time + a tripwire rejecting `available_at ≥ resolution`. Test `forecast_prob` vs realized on Brier/log-loss OOS. No Brier edge → dead |
| **6** | **Basis-momentum carry** | Ride an *accelerating* perp-spot basis (leverage build-up trends for days) instead of fading its level | **Yes** — `perp_spot_basis` registered tier0 PIT; new feature = `d(basis)/dt`, z-scored, 4h bar | Trades the time-derivative (opposite sign) of an already-tested level signal — novel + PIT-clean | Compute basis-momentum z on 4h; forward-return AND **regress strategy returns on B&H, require residual α>0 net of fees**. Kill if α collapses to beta |
| **7** | **Resolution-lag on niche markets** | Buy lagging YES once a FREE truth-feed (Kraken bar crossed threshold / RSS pubDate) confirms an outcome slow retail hasn't priced | **Yes** but heavy build — needs CLOB depth replay + placebo-lag null | Real moat (illiquid, externally-verifiable, no-HFT) but highest build cost + leakage risk; edge may be near-zero fillable size | Scoping spike: does fillable CLOB depth exist at the lagging quote at the FIRST timestamp after truth `available_at`, and does a **placebo-lag null** (+N min) kill it? Depth≈0 or survives placebo → dead |

**Tail / deprioritized:** *pre-settlement funding drift* (blocked on a PIT predicted-funding feature that isn't wired); *authority meta-label* (blocked on the VOICE_PANEL backfill below — thesis sound but un-runnable until the panel has 1–2yr PIT history).

**Blocking infra task (not a hypothesis):** Pre-register ~10–15 voices in `config/voices.py`, replay their public timelines through `compute_authority` to mint a 1–2yr backfilled PIT authority series, run `profile-source` to confirm density. LLM/key-gated, forward-only today — gates the whole social-credibility lane.

## Test FIRST — H3: Cross-venue funding divergence

Maximum-leverage, minimum-risk:

- **Zero new data, zero new keys, zero leakage exposure** — all three funding providers are already ingested and verified `available_at==ts`. Nothing to wire, nothing to leak. (Contrast H1/H2, whose first day is spent *building* an endpoint just to find out if a signal exists.)
- **The single feature edit (`funding − cross_venue_median`, z-scored) is the entire experiment** — a derived column computable offline against 2yr of history.
- **Structurally orthogonal to the failed single-venue funding-LEVEL set** → a positive result is genuinely new information.
- **Its one real Gate threat (sparse entries) is solvable by design** — pooling the z-signal into one basket across ~10 assets × 3 settlements/day clears N≥30 honestly.

If the offline event-study shows ≥30 pooled entries, right-signed reversion, and gross edge beating 2× round-trip Kraken fees on a *single pre-registered* threshold, promote to the BRUT Gate. Else killed in <1 day, no code debt, no prod impact — then move to H8 (same cheap-surfacing + offline-event-study profile).
