# LLM-bridge / hidden-market edge backlog — 2026-06-14

The genuinely-novel "better-than-a-hedge-fund" plays surfaced by the hidden-edge campaign
(`scripts/_strategy_campaign.js`, 33 web-grounded hypotheses, 6 themes). These are **not testable today**
because the PIT feed doesn't exist yet — but each is blocked only by data an agent/LLM can bridge cheaply,
on markets too small or signals too un-automated for a fund to bother with. Ranked by value ÷ unblock-cost.

> Discipline: every one still goes through the same honest Gate (deflated-Sharpe + BH-FDR + purged
> holdout, net of fees). This is a list of edges to *test*, not edges we believe.

## 1. Pre-FOMC drift (calendar-armed equity long) — CHEAPEST, highest-confidence
**Thesis:** one of the most robust documented anomalies — NY Fed: ~3.89%/yr excess return in the 24h
before scheduled FOMC vs 0.89% other days; >80% of the post-1994 equity premium earned in that window.
An event-timed regime that arms a SPY/QQQ long around a known date.
**Unblock (trivial, ~1-2h):** wire a **PIT scheduled-FOMC-date calendar** (8 dates/yr, knowable ~1yr
ahead → no look-ahead) as a binary feature (`days_to_fomc` / `is_fomc_eve`). The macro/vix/putcall
conditioners already exist. → immediately gate-testable.

## 2. Fix `vix_term_slope` (VERIFIED BUG) → VIX backwardation→contango recovery — high value
**Bug:** `catalog.py:42` maps `vix_term_slope → "VIXCLS"`, identical to `vix_level` (line 37). The feature
is the VIX *spot level mislabeled as a slope* — every spec/correlation using it has silently traded VIX
twice (no `transform_version` in the registry confirms it's not computed).
**Thesis once fixed:** the backwardation→contango *flip* (not the level) is a documented post-capitulation
buy (backwardation preceded ~100% of major drawdowns 1990-2025; the contango re-flip is the historical
recovery trigger). Orthogonal — it's the 2nd derivative of the vol surface.
**Unblock (~half day):** wire a 2nd FRED tenor (`VXVCLS`=VIX3M or `VXDCLS`=VIX9D), compute
`slope = VIX3M − VIX` (contango>0/backwardation<0) with a real `vix-term-slope-v2` transform + PIT
next-day availability; backfill. Fixes a data-integrity lie AND unlocks the signal.

## 3. Crypto variance-risk-premium (DVOL − realized vol) long filter — medium
**Thesis:** VRP (implied≫realized) predicts forward returns (Bollerslev-Tauchen-Zhou); crypto analog =
DVOL − trailing realized vol. A bounded, mean-reverting gap; over-paid fear → contrarian long on BTC/ETH.
Funds harvest VRP by *selling* variance (options desk, capacity-heavy); using the gap as a spot *long
filter* is the un-automated bridge.
**Unblock:** deep **Deribit DVOL history (≥3yr, through the 2021 vol cycle)** — currently 128 rows / 2mo.
+ realized-vol on a matched 30d window.

## 4. Prediction-market velocity / cross-venue disagreement (Polymarket × Kalshi) — novel hidden market
**Thesis:** (a) Polymarket macro-risk repricing *velocity* as a leading risk-off tag for crypto; (b) when
**Polymarket and Kalshi disagree** on a macro outcome, the cross-venue spread is a clean un-quantified
uncertainty signal (disagreement = unresolved macro risk = elevated crypto vol around resolution). The
genuine hedge-fund blindspot — markets too small / history too short for them to allocate to.
**Unblock:** backfill `pm_risk_on`/`pm_implied_prob` to ≥18-24mo (currently ~390 rows, 1 market, 13mo);
**ingest Kalshi macro contracts** (KXFED / KXRECSSNBER / KXCPI) with PIT history; match same-question
markets to compute the spread.

## 5. Composite crowd-belief gate (pm_risk_on + fear_greed + putcall) — medium
**Thesis:** single sentiment signals are exhausted; require **forward belief (pm) + spot retail (F&G) +
options positioning (putcall) to ALL agree** on capitulation before arming a SPY/QQQ dip buy.
**Unblock:** `fear_greed` (3yr) ready; **backfill `pm_risk_on` to ≥2yr** and **ingest `putcall_ratio`**
(cboe, currently 0 rows). Then immediately gate-testable.

## 6. Weather degree-day forecast-anomaly → energy/utility tilt — the LLM-bridge classic
**Thesis:** gas-weighted heating/cooling degree-day *forecast anomalies vs the 30yr normal* drive nat-gas
demand → energy/utility equities (XLE/XLU). The tradable, un-quantified part is the *forecast* anomaly
(warm winter = gas headwind; heat wave = power demand). An LLM converts seasonal forecasts → a numeric
demand-surprise the quant feeds don't carry.
**Unblock:** a PIT gas-weighted degree-day **forecast-anomaly** feed (Open-Meteo forecast archive + NOAA
CPC degree-day products, free), stamped at forecast-issue time (no look-ahead). The scrape/LLM seam
(`scrape_stub.py`) is the path.

---

**Why this is the real output of the campaign:** the 25 specs we could gate today live on the
already-mapped wall (one-cycle depth + spot fees). The *edge* is in these data-bridges — small markets
(Kalshi/Polymarket), un-automated signals (weather forecast anomaly, FOMC calendar, VIX term structure) —
exactly where an LLM+agent can cheaply quantify what a fund won't. Cheapest-first: **#1 FOMC calendar**
and **#2 vix_term_slope fix** are each <1 day and immediately produce a new honest Gate test.
