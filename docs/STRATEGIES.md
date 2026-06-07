# COSMU — Strategies: what they are + the campaign memos

## 1. WTF is a "strategy" in COSMU?
A **strategy = a typed `StrategySpec`** = a *falsifiable hypothesis* — "signal X predicts return Y" — encoded as deterministic entry/exit rules on **point-in-time features**, tested on a **universe of assets** through the deterministic **Gate**. Every strategy has:
- a **THESIS** — why it should work (a documented anomaly, or an intuition);
- **FEATURES** — the data it reads (price, funding, social, vol, …);
- a **UNIVERSE** — what it trades (e.g. 30 mid-cap perps, or US equities);
- a **DISCONFIRMER** — the observation that would falsify it (the anti-p-hacking guard);
- a **VERDICT** — the Gate's PASS/FAIL, *net of real fees*, after deflated-Sharpe · CSCV-PBO · BH-FDR · OOS holdout.

The LLM **proposes**; the Gate **disposes**; profit net of fees is the only score. The LLM never touches money.

## 2. "Why not test every strategy × every asset / more combos?"
- A **cross-sectional** strategy (momentum, reversal) already *ranks across the whole universe* — that IS testing many assets at once.
- A full **strategy × asset × timeframe × param matrix** is possible, **but every combo is a TRIAL.** The Gate deflates against the trial count (deflated Sharpe + BH-FDR), so **more combos make the bar HARDER, not the edge easier** — correctly, because brute-forcing everything *manufactures false positives* (p-hacking). That's the exact failure mode the Gate exists to prevent.
- The right "more combos": **hypothesis-driven** (each combo pre-registered with a disconfirmer) + **ML feature-importance** to surface *non-obvious* combos — not brute force. This is the "new search method" worth building (see §6).

## 3. The campaign memos (crypto, 5 waves / ~16 spaces — all honest FAILs)
| Strategy | Thesis (1 line) | Universe | Verdict |
|---|---|---|---|
| Xsec momentum (long-only) | winners keep winning | mid-cap perps | FAIL — inherits bear beta, uneconomic after fees |
| L/S market-neutral momentum | dispersion (not direction) pays | deep mid-cap perps | FAIL — real signal (dSR 0.25) but uneconomic |
| Funding-carry | harvest the crowded-long funding premium | perps | FAIL — funding clamped ~+1e-4 |
| Funding-crowding contrarian | extreme funding = crowded = reverts | mid-cap perps | FAIL — funding carries no info |
| BTC-social risk-on overlay | BTC attention spikes lead alt risk-on | majors → small-caps | FAIL — real on majors (0.85), placebo-falsified on small-caps |
| Polymarket positioning | prediction-market odds lead price | BTC | FAIL — data thin / mis-calibrated |
| Social-dominance leadership | attention *share* leads return | majors+mid | FAIL — momentum in disguise |
| OI / long-short-ratio crowding | positioning extremes revert | mid-cap perps | DATA-BLOCKED — free OI only ~30d |
| Vol-regime gate | cut exposure in turbulence | mid-cap perps | FAIL — vol timing is noise |
| DVOL regime | implied-vol regime filter | BTC/ETH | FAIL — DVOL = noisy rvol proxy |
| Cross-venue funding dispersion | funding spread across venues = carry | Binance/Bybit/OKX | FAIL — artefact, not cross-venue timing |
| Short-term reversal | oversold bounces | mid-cap perps | FAIL — wrong sign (perps *trend* daily) |
| Stat-arb cointegration pairs | cointegrated pairs revert to spread | mid-cap perps | FAIL — de-cointegrate OOS; random pairs win |
| Calendar / seasonality | day/turn-of-month effects | mid-cap perps | FAIL — shuffled-calendar placebo reproduces |

**The structural lesson:** where a directional signal exists (daily momentum) the **retail taker fee eats it**; where retail could trade cheaply (stat-arb/intraday reversion) the **daily data is too coarse**; apparent winners are **beta or placebo-noise**. Not a search-effort problem — a **venue/data/fee** problem. → pivot to equities.

## 4. Equities (running now — the pivot)
| Strategy | Thesis | Universe | Verdict |
|---|---|---|---|
| Overnight-return | equity drift accrues *overnight*, not intraday | ~60-80 US equities/ETFs | (running) |
| 12-1 momentum | the canonical equity factor that *survives* | US equities | (running) |
| Short-term reversal | weekly reversal (the *right* sign in equities) | US equities | (running) |
| Calendar / turn-of-month | documented equity calendar effects | US equities | (running) |
Equities fix the two crypto killers: **deep free data** (decades, Stooq) + **~5-10× lower fees**.

## 5. Forward-testing & live (the Kraken question)
- **Forward-test needs NO exchange account and NO ID.** It paper-marks a strategy's signals against **live free price feeds** for 30 days (the forward-mark clock) — no money, no orders, no KYC. **Already built** (the lifecycle hard-gate). So `kraken-cli` is *not* needed to forward-test.
- **LIVE (real money)** needs a KYC'd account (Kraken/Binance/IBKR). Kraken Futures has a no-KYC **demo** env, and `kraken-cli` could become a live-execution adapter — but that's **post-edge**; we don't touch it until a strategy survives the Gate + forward-test.

## 6. New ways to SEARCH (not new data) — the backlog
- **Strategy × asset × timeframe matrix** (FDR-disciplined) — the core ML feature.
- **ML feature-importance** (gradient-boosted / MDA) → propose non-obvious feature combos → gate them.
- **Idea ingestion** — scrape r/algotrading / quant threads → low-confidence hypotheses → typed specs → the Gate (bias-guarded; the Gate kills the noise). *(Banked 2026-06-07.)*

## 7. Is the DB good / do we store enough?
Architecture: **good** — Supabase Pro (8 GB), an append-only **point-in-time** store, a declarative feature catalog, a registry⊆routable guard. The **reality is DEPTH**, the recurring wall: Binance funding only to 2024-06, free OI ~30d, Polymarket ~13mo. Fix = deepen the free tier-0 sources + **accrue forward** (OI/funding/intraday). For equities, Stooq removes the depth wall entirely.
