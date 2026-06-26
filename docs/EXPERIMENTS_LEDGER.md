# COSMU — Experiments Ledger

> **The single canonical record of every edge experiment COSMU has run — and *why* each one worked or died.**
> Read-only synthesis. One row per experiment: hypothesis · method · verdict · the one-line killer · doc-link.
> Grouped by theme; patterns distilled at the bottom; a "not-yet-tested" shortlist at the end.
>
> **Last synthesized:** 2026-06-26 · **Sources:** `docs/reports/*`, `docs/research/*`, the standardized Research Registry (`r2://cosmu-lake/research_registry/`, 19 records), and the 2026-06-25 edge sprint.

---

## How to read the verdict column

| Verdict | Meaning |
|---|---|
| ✅ **EDGE** | Cleared the full honest Gate AND is economically real (the rare survivor). |
| 🟡 **LIVE-CANDIDATE** | Gross signal clears the Gate; honest net is plausibly positive but needs a small live/forward test to confirm (the open frontier). |
| ❌ **KILL** | Signal genuinely absent, negative, or a beta/overfit artifact — a real reject of the *thesis*, not a plumbing gap. |
| 💸 **UNECONOMIC** | Signal is *real and large gross*, but transaction cost / fees consume it entirely at our tier. |
| 🧱 **DATA-WALL** | Untestable today — no reachable PIT-honest data feed. Not disconfirmed; *unmeasurable*. |
| 🛠 **INFRA** | A pipeline/data-trust finding (not an alpha claim) — but load-bearing for everything else. |

**The cardinal rule throughout:** the Gate was *never* the thing that over-rejected. Every kill routed through one of three walls — **cost**, **data-access**, or **genuine absence** — or through a *correct* statistical catch (PBO, β-orthogonality, survivorship, deflated-Sharpe). The empty result is the machine working.

---

## 1. Price-derived crypto signals

> The single most-tested family. **Verdict: exhausted on liquid majors at our cost tier.** The cross-sectional momentum premium is *real and large gross*, but cost eats it; carry/basis is arbitraged to negative-α; funding doesn't revert. Closed twice over with clean gross-vs-net decompositions.

| Experiment | Date | Hypothesis (1 line) | Data / method | Verdict | Why (the one-line killer) | Doc |
|---|---|---|---|---|---|---|
| Xsec-momentum (long-only daily) | 06-25 | Long relative-strength leaders beats the market | 126 (theme×symbol×venue×config) combos, Binance+Kraken real bars, BRUT per combo | ❌ KILL | 5/126 reach 30 trades, all DSR≈0; long-only crypto can't out-return B&H in a bull tape (kills 88/126) | [edge-hunt](reports/edge-hunt-experiment-2026-06-25.md) |
| Xsec-momentum (market-neutral 4h) | 06-25 | Long-leaders/short-laggards spread removes the beta wall | Bybit keyless 4h paginated to 3.65yr, 12 names, genuine L/S book, funding both legs | 💸 UNECONOMIC | Both beta + trade-count walls *broke* (corr-BTC≈0, 3k–24k trades) — but gross +53–89% is **entirely eaten by two-leg turnover cost** | [mkt-neutral](reports/edge-hunt-mktneutral-2026-06-25.md) |
| Xsec-momentum (low-turnover deadband) | 06-25 | Slowing the rebalance saves the cost the L/S book bleeds | Pre-registered 16-config grid (weekly/bi-weekly × 4 bands × 2 lookbacks), identical cost floor | 💸 UNECONOMIC | 0/16 clear the Gate; the no-trade band **starves the thin 12-name signal faster than it saves cost** — no sweet spot. Thesis closed *twice* | [low-turnover](reports/edge-hunt-lowturnover-2026-06-25.md) |
| Funding-contrarian (daily conjunction) | 06-25 | Long spot when funding deeply-negative AND RSI oversold | Same combo harness; Binance perp funding signal | ❌ KILL | The `negative-funding AND oversold` conjunction fires ≤4× in 2yr — a **non-event**, not a near-miss | [edge-hunt](reports/edge-hunt-experiment-2026-06-25.md) |
| Funding-contrarian (continuous percentile) | 06-25 | Replace the hard conjunction with a rolling funding-percentile long | 4h, per (symbol×venue), BRUT | ❌ KILL | Now fires 150–320×; best (LTC) hits DSR 0.62 and beats own B&H — but **holdout DSR is negative**, in-sample only | [mkt-neutral](reports/edge-hunt-mktneutral-2026-06-25.md) |
| H3 — cross-venue funding divergence | 06-25 | Fade the perp venue whose 8h funding is the cross-venue outlier; spread reverts | Offline event-study, 597 events, Binance/OKX/Kraken-Futures funding, Kraken-spot reference | ❌ KILL | The spread **doesn't revert** — gross −19.8 bps (wrong sign), ≪ the 160 bps fee hurdle. Killed in <1 day on cheap checks | [h3](reports/h3-funding-divergence-2026-06-25.md) |
| H5 — basis-momentum carry | 06-25 | Ride an *accelerating* perp-spot basis (`d(basis)/dt`), a different family from price-momentum | 12 names × 3.65yr 4h, β-orthogonality disconfirmer | ❌ KILL | β-clean (β-BTC≈0, *not* a beta trap) but **residual α = −40%/yr, t=−2.46** — chasing acceleration buys late-stage crowded leverage about to unwind | [h5](reports/h5-basis-momentum-2026-06-25.md) |
| Squeeze-release + range-floor reversion | 06-16 | Grid-bot-video TA: BB-width squeeze + range-position accumulation | Real Binance 4h, 8 symbols, 48-variant grids, 10 bps | ❌ KILL | 0/42 and 1/48 net-positive; PBO≈0.50, holdout DSR≈0. Stayed flat through a −48.6% crash = **cash, not alpha** (spot can't monetize crash-avoidance) | [squeeze](research/squeeze_range_reversion_study.md) |
| Trend-following SHORT leg | 06-16 | Would a perp short have monetized the down-trend the reversion specs avoided? | `direction=-1` ADX+neg-momentum grid vs passive-short beta control | ❌ KILL | Timed short **loses to passively holding short** — the whole positive number is down-window beta you can't time, not alpha | [squeeze](research/squeeze_range_reversion_study.md) |
| Xsec-momentum (historical decay study) | 06-15 | Is the classic Jegadeesh-Titman crypto momentum premium tradeable today? | 30 names, 2018–2026, neutral + long-decile, circular-shift null, DSR | ❌ KILL | **Real edge in 2018–21 (SR 1.0→2.2), arbitraged out by 2023+** (2025 SR −0.13, 2026 −2.3); OOS t-stat 0.43 ≈ 0. Post-publication anomaly decay | [xsec](research/xsec_momentum.md) |

---

## 2. Prediction markets (Polymarket) — the one live frontier

> The lane "the giants ignore" (reg-grey, no-desk, weak-signal). The hold-to-resolution longshot fade is dead; the **intraday over-extension fade has a real, Gate-clearing gross edge** — dead as a taker (spread eats it), but **plausibly net-positive as a maker, geopolitics-only.** This is the one experiment that points across the zero-impact line to a live test.

| Experiment | Date | Hypothesis (1 line) | Data / method | Verdict | Why (the one-line killer / liver) | Doc |
|---|---|---|---|---|---|---|
| Polymarket data-trust experiment | 06-25 | Are Polymarket odds a trustworthy PIT research source? | Real keyless Gamma+CLOB fetch, 6 resolved markets, leakage tripwire | 🛠 INFRA | **Data trust = GO** (PIT-honest, immutable, resolution-true); **daily wiring = NO-GO** (hardcoded `fidelity=1440` → ~1 trade/market → Gate correctly refuses). Hourly exists only via windowed requests | [trust](reports/polymarket-trust-experiment-2026-06-25.md) |
| Polymarket odds scout | 06-25 | Is the prediction-contract lane gate-ready? | Read-only code audit (ingest/PIT/resolution-join) | 🛠 INFRA | REVIEW: 3 bounded fixes — orphaned+daily ingest, **missing UMA resolution join**, 1-bucket PIT-lag. ~80% wired | [scout](reports/polymarket-odds-scout-2026-06-25.md) |
| H9 — resolution-convergence theta-decay | 06-25 | Long-shot YES theta-decays toward 0; short it and hold to resolution | 294 survivorship-complete closed trades (geo 0% / sports 3% fee), production scorer | ❌ KILL | **The survivorship tail eats it** — rare YES-resolvers (−22.60 geo) erase the entire NO-harvest (+22.32); decay is ≈0/negative, no mispricing. The 80–89% win rate is a mirage | [h9](reports/h9-polymarket-thetadecay-2026-06-25.md) |
| Polymarket INTRADAY over-extension (taker) | 06-25 | Fade a ≥2.5σ intraday over-extension; it reverts *before* resolution | 3,134 trades, keyless windowed hourly CLOB, 3 disconfirmers, spread from 1,345 live books | ❌ KILL (taker) | **Gross edge is REAL and clears the Gate (DSR 1.0)** — but the wide CLOB spread (median 1c/mean 2.9c) is 2–6× the +0.70c edge; net −2.86c. Win rate 44%→9% | [intraday](reports/polymarket-intraday-overextension-2026-06-25.md) |
| Polymarket INTRADAY over-extension (maker) | 06-25 | Earn the half-spread as a resting maker instead of crossing it | Feasibility study: 3,055 events path-classified, fill mix 71/16/13, best/expected/worst band | 🟡 **LIVE-CANDIDATE** | Maker-net **+1.0 to +3.1c/$1 (exp +1.7), positive across the band, geopolitics-only**; no-spread-credit floor still +0.16c (adverse fills enter deeper/better). Fills unknowable offline → needs a small live passive-order test | [maker](reports/polymarket-maker-feasibility-2026-06-25.md) |

---

## 3. Social / credibility — the proven-but-dormant lane

> The one untested *kind* of signal (non-price, segmentation moat). Mechanically proven on real data to separate skill from noise; dormant only because the voice panel is empty. Its real payoff is the agentic-lane **Gate B** substrate, not overnight alpha.

| Experiment | Date | Hypothesis (1 line) | Data / method | Verdict | Why (the one-line finding) | Doc |
|---|---|---|---|---|---|---|
| Credibility pipeline scout | 06-25 | Is the "PageRank-for-credibility" lane buildable? | Read-only audit of `mind.{claims,outcomes,authority}` (42 tests green) | 🛠 INFRA | Pipeline is **far more complete than "built but dark"** — Phases 0→3 typed, PIT-honest, wired to a cron + API. Dormant for 2 trivial reasons: `VOICE_PANEL=()` empty + no schedule slot | [cred-scout](reports/credibility-pipeline-scout-2026-06-25.md) |
| Credibility offline dry-run | 06-25 | Does the scoreboard actually separate skill from noise/echo on real data? | Constructed panel (sniper/spammer/follower) scored vs 13mo real BTC/ETH/SOL/DOGE bars | 🟡 PROVEN-MECHANISM | **Separates decisively** — sniper skill 0.701, spammer 0.000, follower 0.000; lead-lag-symmetry kills the echo (asymmetry −0.694); shuffle-null + PIT both pass. First honest answer will likely be "0/N voices carry skill" — but the mechanism is sound | [cred-dryrun](reports/credibility-dryrun-2026-06-25.md) |

---

## 4. Alt-data / on-chain — the orthogonal-data hunt

> "We need orthogonal data, not more sweeps." Tested deep on-chain, stablecoin flows, liquidation skew, and the retail fear/greed/VIX battery. **Verdict: the daily-level orthogonal axis hits the same regime-depth + fee wall**; the high-IC features are single-cycle co-trending artifacts (proven against the astro non-causal control).

| Experiment | Date | Hypothesis (1 line) | Data / method | Verdict | Why (the one-line killer) | Doc |
|---|---|---|---|---|---|---|
| Deep on-chain capitulation specs | 06-14 | Bounded on-chain / Fear&Greed / VIX features signal capitulation | 27k-point deep BTC on-chain backfill, 3 specs, pooled grid, real holdout | ❌ KILL | 0 promoted; **Fear&Greed contrarian has negative OOS edge net of fees** (buy-the-dip that reversed in the held-out slice); on-chain IC < the astro non-causal control | [orthogonal](reports/orthogonal-data-2026-06-14.md) |
| On-chain IC vs astro control | 06-14 | Do on-chain fundamentals carry information? | correlation_scan round 2, 972 tests, BH-FDR | ❌ KILL | `btc_hashrate` IC −0.35 @ h=20 didn't survive FDR; **`jupiter_longitude` (known-false) IC −0.36 was LARGER** → on-chain at the same magnitude is the same single-cycle artifact | [orthogonal](reports/orthogonal-data-2026-06-14.md) |
| H7 — stablecoin chain-rotation | 06-25 | Stablecoin float-share rotating *onto* a chain pre-positions its native token | 724 events (177 independent), DefiLlama share-CHANGE derivative, TRON/SOL, drift disconfirmer | ❌ KILL | Apparent +115 bps is **per-token beta, not rotation**: Tron lift −11 bps (worse than baseline), whole edge is Solana's reflexive bull-phase confound. Gate independently fails PBO 0.571 | [h7](reports/h7-stablecoin-rotation-2026-06-25.md) |
| H8 — signed liquidation skew snap-back | 06-25 | Fade the side that got wiped (`long_liq≫short_liq` → reversion up) | Pre-registered event-study, 8 small-cap perps; synthetic null-control for plumbing | 🧱 DATA-WALL | **N=0** — no keyless signed-liquidation history reachable (Coinglass key-gated, Binance deprecated/empty). The shipped `liquidation-cascade` feature is *direction-blind* (sums the legs) AND has 0 ingested rows. Untestable, not disconfirmed | [h8](reports/h8-liquidation-skew-2026-06-25.md) |
| Live-honest signals as strategies | 06-15 | Do funding / Fear&Greed / VIX / geomag carry deployable alpha? | Real strategies, deflation, OOS, proper nulls | ❌ KILL | 0 survive deflation; funding-contrarian is *genuinely causal* (asymmetric lead-lag) but too weak standalone → defensive filter only. **Alt-signal alpha is as closed as astro** | [preview](research/RESEARCH_PREVIEW.md) |
| Live-honest composite | 06-15 | Do {funding, F&G, VIX, 60d-mom} *combine* into an edge? | Composite vs momentum-only disconfirmer | ❌ KILL | Composite edge == momentum-only edge → **the 3 live macro signals add nothing**; the combo just rides 60d trend. Train SR 1.14 → OOS −0.42 | [preview](research/RESEARCH_PREVIEW.md) |
| LunarCrush social IC | 06-15 | High-IC social-sentiment features | PIT honesty audit | ❌ KILL | High backtest IC but **backfilled + vendor-revised** → look-ahead mirage; the value at trade-time was NOT what now sits in the DB. Not live-tradeable | [preview](research/RESEARCH_PREVIEW.md) |

---

## 5. Astro & non-causal controls — definitively closed

> 19-experiment, 10-scientific-dimension battery across 32+ real assets, 2009–2026. **0 tradeable edges. A definitive, multiply-confirmed null** — not a strictness artifact. Its enduring value: the honesty pipeline (proper nulls, lead-lag symmetry, train→OOS rank consistency) and a known-false control that exposes cycle-artifacts everywhere else.

| Experiment | Date | Hypothesis (1 line) | Method / null | Verdict | Why (the one-line killer) | Doc |
|---|---|---|---|---|---|---|
| Astro single-signal IC | 06-14 | Planets/aspects/lunar predict returns | Spearman + BH-FDR, 4,092 tests | ❌ KILL | **0/4,092 survive BH-FDR**; astro-only weekly p≈0.72 | [astro](research/astro_vs_markets.md) |
| Deep astro vs real baseline | 06-14 | Astro adds to a real alt-data model | Pooled walk-forward AUC + incremental test (Modal), 32,372 tests | ❌ KILL | 0 survive; astro **DEGRADES** OOS AUC (−0.015 to −0.042). Adding a known-null block dilutes a real model | [astro-deep](research/astro_vs_markets_deep.md) |
| 152k astro strategy lab | 06-15 | Some astro school/segment/config is tradeable | 152,166 trials × Deflated Sharpe | ❌ KILL | Raw best Sharpe 1.85 → **0 survive deflation** (best-of-N noise = √(2·lnN)/√T). More search deflates harder, never finds | [lab](research/astro_strategy_lab.md) |
| Astro composite + natal | 06-15 | A multi-signal/natal composite carries skill | Train/test, group×regime×segment | ❌ KILL | **train→OOS ranking INVERTS** (best-train = worst-OOS) — the fingerprint of noise | [composite](research/astro_composite.md) |
| Lunar realized-vol candidate | 06-15 | Full-moon/eclipse vol effect (3/76 survived a weak null) | **Phase-shuffle null** (preserves autocorrelation) | 🟥 ARTIFACT | The fake-date null manufactured the hit; under the **proper phase-shuffle p=0.33** → artifact. THE lesson: a weak null lies | [event](research/astro_event_study.md) |
| Geomagnetic storms (Krivelyova-Robotti) | 06-15 | Post-storm returns are depressed | Proper nulls + OOS | ❌ KILL | −25 bps (right sign! real mechanism) but **p≈0.10 and decays OOS** (−43→−8 bps). The "least dead" candidate — forward-watch, not capital | [preview](research/RESEARCH_PREVIEW.md) |
| Hierarchical-Bayes pooling | 06-15 | Partial-pooling reveals a pooled astro edge | DerSimonian-Laird meta-analysis | ❌ KILL | jupiter-saturn pooled z=6.6 — but it's the **cross-asset-correlation-inflated pooling artifact** (DL standard error is wrong for correlated crypto returns) | [preview](research/RESEARCH_PREVIEW.md) |
| Named systems (Bradley/Gann/Merriman) | 06-15 | Financial-astro turn-dates beat chance | Vs shifted-curve null | ❌ KILL | Merriman +1.0pp hit-rate on a 97%-saturated base = near-saturation, **statistically marginal, economically meaningless** | [preview](research/RESEARCH_PREVIEW.md) |
| Astro belief channel (Hermes port) | 06-15 | Astrology as a self-fulfilling *belief/attention* proxy | Mercury-retrograde × Wikipedia-pageview belief intensity (PIT-clean) | ❌ KILL | The one channel with a real prior: retro return drop is real (−22bps) BUT the **retail-interaction test fails** (t=−0.32), no Ma-Kou reversal, placebo p=0.094, DSR 0.69. Astro now closed across deterministic AND behavioral channels | [astro-verdict](research/ASTRO_VERDICT.md) |
| _(+ spectral, info-theoretic, tail-clustering, SAD/daylight — all NO_EDGE)_ | 06-15 | Various astro lenses | Lomb-Scargle/IAAFT, MI/transfer-entropy, within-year permutation, HAC | ❌ KILL | All die under the correct null; synthetic slow-control matches the "signal" = trend artifact | [preview](research/RESEARCH_PREVIEW.md) |

---

## 6. Exit-structure & evaluation reform

> Not edge discovery — *how we judge and exit*. The deploy lane was the un-deflated hole (hardened); the exit envelope and B&H-as-killer were re-examined.

| Experiment | Date | Question (1 line) | Finding | Verdict | Doc |
|---|---|---|---|---|---|
| Deploy-lane deflation hardening | 06-16 | Does the un-deflated DEPLOY bar leak noise the cohort Gate would catch? | A no-edge random walk cleared the old sign-check deploy bar **12.5–20%** of the time; hardened with a holdout-DSR floor (0.20/0.30) + a full-stream deflated floor charging the cadence search → **20%→0.12%**, genuine edges kept | 🛠 INFRA (fixed) | [lessons](research/RESEARCH_LESSONS.md) §2b |
| Rejects-watch lane / B&H demotion | 06-16 | Do we discard good strategies just for not beating HODL? | **buy_and_hold is NEVER the sole killer** (0/1887 prod runs); the real over-rejection is 6 OOS-strong books killed by in-sample deflation. Added an OOS-holdout admission path; demoted B&H to a displayed-reason-not-disqualifier | 🛠 INFRA (fixed) | [lessons](research/RESEARCH_LESSONS.md) §2c |
| Exit-spike WIDE firm-up | 06-25 | Which exit toolset survives wide backtesting? | V0 default + V4 keeper survive; hard-drop V2/V3 (384 backtests, 2yr daily) | 🛠 INFRA | _(git: #381; exit-sweep #378)_ |

---

## 7. The ONE survivor — equity TAA (the compounding floor)

> The single ✅ EDGE in the entire body of work. Real prices, published prior, judged on its native multi-asset monthly universe — not a crypto projection. No Gate threshold was changed to admit it.

| Experiment | Date | Hypothesis (1 line) | Method | Verdict | Why it LIVES | Doc |
|---|---|---|---|---|---|---|
| Equity TAA cohort (DAA/VAA/ADM) | 06-14 | Monthly multi-asset-class momentum + canary-breadth crash-avoidance pays a durable premium | 8 ETFs, total-return monthly, real IBKR ~1bp fees, full 0.95 Gate + 49mo purged holdout | ✅ **EDGE** | DAA **DSR 1.000, holdout DSR +0.447, +94% OOS net of fees, ann Sharpe 1.23, maxDD 19.6% vs SPY ~50%, cohort PBO 0.043.** A documented prior (Keller 2018), never mined from our data; the premium persists because benchmark-locked capital structurally can't de-risk monthly | [taa-survivor](reports/equity-taa-honest-gate-survivors.md) |

GEM, sector-rotation, the B&H-SPY null and the random-rotation placebo in the same cohort were all correctly **refused** — the Gate admitted the real prior and rejected the rest at the same bar.

---

## PATTERNS — what we learned

**1. Price-derived crypto signals are exhausted on the liquid-majors universe at our cost tier.** The cross-sectional momentum premium is *real and large gross* (+53–89%), but it's eaten whole by two-leg turnover cost — and lowering turnover starves the thin 12-name signal faster than it saves cost. Carry/basis is arbitraged to *negative* α. Funding doesn't revert. This is measured *twice over* (mkt-neutral + low-turnover) with clean gross-vs-net decompositions, and confirmed by the 2018–26 decay study (real edge, arbitraged out by 2023). **Stop adding momentum/range/carry/turnover variants here.**

**2. Cost is the wall, not the Gate and rarely the signal.** Every kill in the 2026-06-25 sprint died on one of three walls — **cost, data-access, or genuine absence** — *never* on the Gate being too strict. When the signal exists (xsec gross, Polymarket intraday gross), the toll booth is wider than the edge. The honest levers left are *structural* (maker/VIP fee tier, delisted-inclusive universe), not more signal tuning.

**3. Segmentation moats win, never speed.** Every candidate that got close exploits *who can't or won't compete* — KYC-siloed funding arbs, small-cap forced-flow nobody watches, reg-grey Polymarket categories desks ignore, under-covered voices. This is the project's edge thesis confirmed empirically: COSMU wins on weak signals in markets the giants ignore, not on latency (the BTC 5/15m latency idea was already rejected as a loser's game).

**4. The Gate validated itself — repeatedly.** PBO caught H7's overlapping-window over-fit (0.571). β-orthogonality proved H5 wasn't a beta artifact *and still killed it* (negative α). Survivorship killed H9's lottery-ticket mirage. Deflated-Sharpe-at-the-true-trial-count killed the 152k astro lab and every momentum near-miss. The proper phase-shuffle null killed the lunar-vol candidate the weak null had passed. **0 survivors is the machine working — not a calibration failure.** The deploy lane (the one un-deflated hole) was found by Monte-Carlo and hardened, not loosened.

**5. The honesty discipline is the durable asset.** Five reusable tripwires now catch what fooled earlier rounds: (a) **train→OOS rank-consistency** — inversion = noise, the single most diagnostic check; (b) **lead-lag symmetry** — an effect identical at lead and lag is non-causal (killed astro, killed the credibility echo-follower); (c) **a proper autocorrelation-preserving null**, never fake-random dates; (d) **PIT + the live-vs-backtest identity** — a backfilled+revising source (LunarCrush) is a mirage even with high IC; (e) **economic-not-just-statistical** — AUC 0.512 at N=83k is real and dead.

**6. The one live candidate = the Polymarket intraday maker fade.** It is the first and only edge whose gross signal clears the Gate (DSR 1.0) *and* whose honest net stays positive after execution modelling — maker-net +1.0 to +3.1c/$1, geopolitics-only (0% fee), no-spread-credit floor still positive. Everything else either died or is the equity-TAA floor. This is the single thread worth crossing the zero-impact line for: a small live/forward passive-order test.

**7. "Built but dark" ≠ "missing."** Two whole lanes (credibility/voices, Polymarket per-market odds) turned out ~80–95% wired and PIT-honest — dormant for trivial reasons (empty panel, orphaned cron, daily-vs-hourly query, missing resolution join), not absent code. The binding constraint is *hypothesis quality + a wiring line*, not a rebuild.

---

## What's NOT yet tested (the shortlist)

Ranked by leverage. Each crosses the zero-impact line (a live test, a prod wake, or a build) → operator's call.

1. **🥇 Polymarket intraday maker fade — a small live/forward test.** The one candidate with a real gross edge and plausibly-positive honest net. Geopolitics-only, mid-band, small size, with a passive-order fill log + pre-set success/kill criteria. Needs the held hourly-odds ingest (PR #393) + a UMA resolution join. Only live fills can confirm the assumed fill mix.
2. **🥈 Wake credibility/voices observe-only.** Register ~10–15 pre-registered crypto voices + ride the existing `tick` cron + (ideally) a historical backfill + wire the event timeline for lead-lag. Proven mechanism, non-price moat, $0-marginal. Builds the agentic-lane Gate B substrate; first answer will likely be "0/N carry skill" — that's fine.
3. **H1 — recurring-market forecast gap (weather).** A calibrated NOAA/open-meteo ensemble vs retail-eyeballed odds on repeating scheduled Polymarket binaries. Highest edge-fit on the slate, but make-or-break is an unbuilt forecast-archive (`available_at`=issue time) + a live leakage trap. Untested; leak-prone; heavier.
4. **H2 — resolution-lag on niche markets.** Buy a lagging YES once a free truth-feed confirms an outcome slow retail hasn't priced. Real moat but highest build cost + leakage risk; fillable size may be ≈0. Needs a CLOB-depth-replay scoping spike + a placebo-lag null first.
5. **Structural cost levers for the real-but-uneconomic xsec premium.** A maker-rebalance / VIP fee tier and a delisted-inclusive R2 universe (so the no-trade band acts as real hysteresis without starving a 12-name signal). Execution/plumbing questions, not signal ones — only worth it if the premium then clears *some* realistic cost.
6. **True intraday microstructure** (order-flow / book imbalance / volume-profile) — a *different information regime* from the daily levels that hit the regime-depth wall. The standing "where the money might actually be" lever from the orthogonal-data round.
7. **Repair / re-test H8 once a signed-liquidation feed exists.** Either pay for a Coinglass key or stand up a forward-only Binance `@forceOrder` websocket collector; the harness is ready, only the data feed is missing. Independently: surface the signed skew or graveyard the direction-blind, data-starved `liquidation-cascade` feature.

---

## Surfaced prod bugs (captured during experiments, not fixed under no-impact)

- **`KrakenFuturesFundingRateProvider`** — stale URL + wrong field parse → silently returns `[]` (found in H3).
- **`liquidation-cascade-zscore-v1`** — direction-blind (sums long+short legs) **and** data-starved (0 rows ever ingested; cron silently failing) (found in H8).

---

*This ledger is a reflection surface, not a runtime artifact. Every experiment above was docs-only or held; the locked Gate constants were untouched throughout. To extend it, add a row in the right theme + a `research_registry.record(...)` entry — the format is locked.*
