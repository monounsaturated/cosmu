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
Equities fix the two crypto killers: **deep free data** (decades, **Yahoo v8** — Stooq went paywalled mid-session) + **~5-10× lower fees**.

## 5. Papering & live (the Kraken question)
- **Paper needs NO exchange account and NO ID.** It paper-marks a strategy's signals against **live free price feeds** for 30 days (the forward-mark clock) — no money, no orders, no KYC. **Already built** (the lifecycle hard-gate). So `kraken-cli` is *not* needed to paper.
- **LIVE (real money)** needs a KYC'd account (Kraken/Binance/IBKR). Kraken Futures has a no-KYC **demo** env, and `kraken-cli` could become a live-execution adapter — but that's **post-edge**; we don't touch it until a strategy survives the Gate + paper.
- **Floor now: 11 strategies in SIM paper** (10 deploy-lane TAA arms: GEM/Faber/ADM/Risk-Parity/VAA/TSMOM/Sector-Mom/Dual-Mom-QQQ/PAA/DAA + Donchian as a gate-lane SIM candidate). Daily mark via asset-aware clock (Railway cron 22:10 UTC).
  - **deploy-lane (`arm_fleet.py`):** 10 externally-validated TAA strategies — `--dry-run` lists all 10.
  - **gate-lane SIM candidate:** Donchian has NO `equity_*_arm.py` module and is NOT managed by `arm_fleet`; it runs as a bespoke SIM track and is caveated/short-window (not an honest-Gate survivor).

## 6. New ways to SEARCH (not new data) — the backlog
- **Strategy × asset × timeframe matrix** (FDR-disciplined) — the core ML feature.
- **ML feature-importance** (gradient-boosted / MDA) → propose non-obvious feature combos → gate them.
- **Idea ingestion** — scrape r/algotrading / quant threads → low-confidence hypotheses → typed specs → the Gate (bias-guarded; the Gate kills the noise). *(Banked 2026-06-07.)*

## 7. Is the DB good / do we store enough?
Architecture: **good** — Supabase Pro (8 GB), an append-only **point-in-time** store, a declarative feature catalog, a registry⊆routable guard. The **reality is DEPTH**, the recurring wall: Binance funding only to 2024-06, free OI ~30d, Polymarket ~13mo. Fix = deepen the free tier-0 sources + **accrue forward** (OI/funding/intraday). For equities, **Yahoo v8** removes the *depth* wall — but a **survivorship-free PIT universe** (with delisted names) is the next data need (the 73-name cache is today's survivors).

## 8. The equity floor — arming the whole deploy-lane fleet

The **10 externally-validated equity strategies** (GEM, Faber GTAA, ADM, Risk Parity, VAA, TSMOM,
Dual-Momentum QQQ, Sector Rotation, **PAA, DAA**) each have a `equity_*_arm.py` module.
`arm_fleet.py` is the single entrypoint that arms them all in one command.

PAA (Protective Asset Allocation, Keller & Keuning 2016) and DAA (Defensive Asset Allocation,
Keller & Keuning 2018) were added in the overnight-w2 pass. Both pass the deploy-lane bar:
positive OOS net of real IBKR fees + risk-adjusted beat of B&H SPY. PAA full-cycle Sharpe 1.09
(maxDD 18.9% vs SPY 50.8%); DAA full-cycle Sharpe 1.23 (maxDD 19.6% vs SPY 50.8%). NOT
honest-Gate survivors (0 Gate survivors remain) — deploy-lane only.

**One-command runbook (idempotent, SIM-only, offline-safe):**
```
PYTHONPATH=apps/engine python3 -m cosmu.research.arm_fleet
```
- Already-armed tracks are **skipped** (the forward-clock origin is never reset).
- Offline (Yahoo unreachable): the track registers and the position is deferred to the next mark run.
- No live-mode flags are touched; no real orders; no money moved.

**Dry-run (CI / preflight — no DB writes):**
```
PYTHONPATH=apps/engine python3 -m cosmu.research.arm_fleet --dry-run
```

**Arm a subset:**
```
PYTHONPATH=apps/engine python3 -m cosmu.research.arm_fleet --only faber_gtaa,vaa
```

**Railway / Modal deploy:**
```
PYTHONPATH=apps/engine python3 -m cosmu.research.arm_fleet
```
(no `pnpm` or `node_modules` needed — pure Python)

Exit code 0 = all armed or skipped; exit code 1 = at least one strategy failed its deployment bar.
