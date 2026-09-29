# Polymarket → correlated-asset live opportunities

**Dispatched:** 2026-06-29 · **Live run:** 2026-06-30 07:13 UTC · **Lane:** LLM / Conviction (propose-only, human-armed) · **Money path:** none

This is the flagship LLM lane made concrete: scan live Polymarket for the highest-attention macro/geo/commodity/rates
event markets, find the correlated tradeable asset for each, and **measure on free clock-aligned price data whether the
Polymarket move historically LED the asset or just moved with it.** Propose-only — nothing here arms a trade.

Reusable, tested code: [`cosmu/research/polymarket_correlation.py`](../../apps/engine/cosmu/research/polymarket_correlation.py)
· runner [`scripts/research/polymarket_live_opportunities_2026_06_30.py`](../../apps/engine/scripts/research/polymarket_live_opportunities_2026_06_30.py)
· tests [`tests/test_polymarket_correlation.py`](../../apps/engine/tests/test_polymarket_correlation.py)
· raw results `scripts/research/polymarket_live_opportunities_2026_06_30_results.json`.

---

## TL;DR — the RETURN

**Top-3 live event → asset plays right now:**

| # | Live Polymarket event | Correlated asset | Direction (YES↑ ⇒) | Lead/lag verdict | Worth a conviction bet now? |
|---|---|---|---|---|---|
| 1 | **Strait of Hormuz traffic returns to normal** (Jul 31) + the US–Iran de-escalation cluster | **WTI / Brent crude** | oil **DOWN** | Correlation REAL & right-signed (\|ρ\|≈0.20–0.53 at lag 0–1); apparent 1-day "lead" is a **timestamp artifact** → **COINCIDENT nowcast, lead UNCONFIRMED** | **No.** Oil is the faster venue; already priced. Use as a monitoring nowcast. |
| 2 | **Fed July 2026 decision** — "no change" 0.805 / "hike 25bps" 0.176 (a real *hike* tail, zero cuts) | **Front-end rates** (^IRX 13-wk T-bill) | yield up on "hike", down on "no change" | **COINCIDENT** (lag-0 dominant, \|ρ\|≈0.31–0.41) | **No.** The T-bill and the PM reprice on the same FOMC/data. |
| 3 | **BTC price-threshold markets** ("BTC > $56k on Jun 30" = 0.9985, etc.) | **Bitcoin spot** | n/a | **Mechanically coincident** — a digital option on spot; the asset cannot follow the market | **No.** Canonical "already priced" exclusion. |

**Is any worth a small conviction bet now? → No latency/lead edge is confirmed.** Every measurable relationship is
coincident or unconfirmed-on-daily-data. This *re-confirms* the standing project thesis (Polymarket is mostly
coincident / underreacts → use it as a **nowcast, not an arb**; the latency lane was already killed). The genuinely
useful output is **Play #1 as a real-time risk-premium nowcast** + one discretionary divergence to watch (below). A
propose-only Conviction template is included at the end with a hard **DO-NOT-ARM** and the experiment that *would*
change the verdict (an hourly re-run).

---

## 1 · Method & data

**Discovery (keyless).** [`LiveEventScanner`](../../apps/engine/cosmu/research/polymarket_correlation.py) pages the
Polymarket Gamma API (`/markets`, by `volume24hr` / `liquidity` / `volume1wk`), keeps OPEN + order-book markets, routes
each question to a curated theme (oil-geopolitics / rates / macro / broad-geopolitics / crypto / regulatory) and ranks by
a **transparent leverage score**:

```
leverage = attention(log vol) × room_to_move(4·p·(1−p)) × proximity(3–90d window) × mappable
```

with **hard exclusions** (leverage→0, reason kept): thin (<$20k liquidity), no order-book, off-theme (sports etc.), or a
"no-lead" theme (price-threshold markets). This is the "EXCLUDE thin-UMA / ambiguous-resolution" filter in practice —
a deep book is the cheapest proxy for a market the venue and bettors take seriously. (Semantic resolution-ambiguity
remains a manual review step; the scanner flags but cannot fully judge it.)

**Probability history (keyless).** Per-market daily YES-odds via the existing
[`PerMarketOddsSource`](../../apps/engine/cosmu/data/sources/polymarket.py) (CLOB `/prices-history`, `fidelity=1440`).

**Price data — the clock-alignment finding.** ⚠️ In this environment the data clock is **2026** and *the source must be
on the same clock*. Gamma, FRED and Yahoo all return 2026 data; **Yahoo `CL=F` tracks the FRED WTI 2026 series
shape-for-shape** (same $96→$76 crash, ~$3 spot-vs-futures basis), so Yahoo is clock-aligned and reliable. FRED
`fredgraph.csv` is equally aligned but hard-throttles burst requests from one IP. We therefore measure against Yahoo
futures/yields directly: **WTI `CL=F`, Brent `BZ=F`, 13-week T-bill `^IRX`, 10Y `^TNX`**. (My first cut mistakenly passed
*2025* unix timestamps to Yahoo and got a year-shifted series — a reminder that the join is only honest when both legs
share a calendar.)

**Lead/lag measurement.** [`lead_lag_profile`](../../apps/engine/cosmu/research/polymarket_correlation.py) aligns the two
daily series on common dates, forms Δprob_t and asset log-return_t, and computes corr(Δprob_t, return_{t+lag}) for
lag ∈ [−2, +2]:

- **lag 0** → COINCIDENT (move together same-day — no latency-free edge)
- **lag > 0** → PM **LEADS** the asset (the tradeable case)
- **lag < 0** → asset leads PM (PM is the follower)

A LEADS verdict demands the best positive-lag \|ρ\| to clear the ≈2/√n noise floor **and** beat lag-0 by a margin.

> **⚠️ Daily timestamp caveat (decisive here).** The CLOB daily bucket is stamped **00:00 UTC** (verified empirically);
> the oil close lands **~20:00 UTC** (`CL=F` bar ts 04:00 EDT). A naive calendar-date join therefore *already* hands the
> PM series a ~1-day head start, so a lag+1 "LEADS" hit can be that artifact rather than real predictive power. On daily
> data, **read LEADS as "correlation present, direction-consistent, lead UNCONFIRMED."** Only an hourly re-run can settle
> it.

---

## 2 · Live watchlist (ranked by leverage, 2026-06-30)

The board is dominated by **one event complex: the Iran / Strait-of-Hormuz de-escalation**, plus the **Fed July meeting**.

| Lev | Theme | YES | Days→ | Liquidity | Vol 24h | Market |
|----:|-------|----:|------:|----------:|--------:|--------|
| 6.82 | oil-geopol | 0.465 | 10 | $43k | $156k | US × Iran diplomatic meeting by July 10 |
| 6.72 | oil-geopol | 0.375 | 31 | $495k | $167k | **Strait of Hormuz traffic returns to normal by July 31** |
| 6.60 | oil-geopol | 0.595 | 92 | $46k | $172k | Next US–Iran meeting in Qatar by Sept 30 |
| 6.52 | oil-geopol | 0.365 | 3 | $48k | $599k | US × Iran diplomatic meeting by July 3 |
| 6.43 | geopol-broad | 0.575 | 92 | $206k | $79k | United Russia wins most seats next election |
| 5.67 | oil-geopol | 0.680 | 31 | $65k | $82k | US × Iran diplomatic meeting by July 31 |
| 4.61 | rates | 0.805 | 29 | $780k | $293k | **No change in Fed rates after July meeting** |
| 4.59 | oil-geopol | 0.235 | 62 | $536k | $33k | US–Iran final nuclear deal by Aug 31 |
| 4.05 | rates | 0.176 | 29 | $582k | $140k | **Fed +25bps after July meeting** |
| 3.67 | oil-geopol | 0.145 | 15 | $370k | $291k | Strait of Hormuz traffic returns to normal by July 15 |

(Full 12-row board + every excluded market with its reason is in the results JSON.)

---

## 3 · Play #1 — Iran / Strait of Hormuz de-escalation → crude oil

**Why it's the Pareto winner.** Hormuz carries **~20% of global petroleum liquids** (≈20 Mb/d) — *"the world's most
important oil transit chokepoint"* (U.S. EIA, 2023). A live shooting-war-then-ceasefire around that chokepoint is the
single highest-attention, deepest-liquidity, cleanest-mechanism event on the board: de-escalation odds ↑ ⇒ the
supply-disruption risk premium bleeds out ⇒ crude ↓.

**The timeline (PM odds + oil, same 2026 clock):**

| Date | Hormuz-normalize-Jul31 | "Ceasefire over" | WTI `CL=F` | Read |
|------|----:|----:|----:|------|
| May 18 | 0.43 | — | $108.7 | war-risk premium peak |
| Jun 3 | 0.38 | — | $96.0 | premium elevated |
| Jun 11 | 0.26 | **0.31** | $87.7 | escalation fear tops |
| Jun 12–16 | 0.47 → **0.63** | 0.30 → **0.05** | $84.9 → **$76.0** | **ceasefire → ~20% oil crash in a week** |
| Jun 30 | **0.375** | 0.006 | **$70.1** | ceasefire holds; premium gone |

**Lead/lag (Δprob vs oil log-return, lag in days; YES↑ should be NEGATIVE on oil):**

| Pair | N | lag −2 | lag −1 | **lag 0** | **lag +1** | lag +2 | noise floor | naive verdict |
|------|--:|--:|--:|--:|--:|--:|--:|---|
| Hormuz-Jul31 → **WTI** | 33 | −0.07 | −0.23 | **−0.20** | **−0.47** | +0.04 | 0.35 | LEADS* |
| Hormuz-Jul31 → **Brent** | 33 | −0.07 | −0.21 | **−0.23** | **−0.53** | +0.02 | 0.35 | LEADS* |
| Hormuz-Jul15 → WTI | 10 | −0.41 | −0.19 | +0.42 | −0.38 | +0.45 | 0.63 | NONE (underpowered) |

**Honest verdict — COINCIDENT nowcast, lead `*`UNCONFIRMED.** The correlation is **real and correctly signed** (every
lag-0/−1/+1 cell is negative, as the mechanism demands), and it's economically large for Brent (the seaborne benchmark
most exposed to Gulf transit). **But the headline lag+1 ≈ −0.5 is not a tradeable lead:**

1. **Timestamp artifact (decisive).** CLOB odds are stamped 00:00 UTC, oil closes ~20:00 UTC — the calendar join already
   front-runs oil by ~a day, so lag+1 double-counts that offset. The genuinely-aligned cell is lag-0 (≈ −0.20), which
   barely clears the 0.35 noise floor at N=33.
2. **Structural prior.** Crude futures are among the deepest, fastest markets on earth; they reprice on an Iran/Hormuz
   headline in *seconds*. A Polymarket binary that partly tracks **lagging physical shipping-traffic data** cannot
   plausibly lead them. If anything, oil leads the PM.
3. **N = one event.** This is a single crisis window, not a population of events — no out-of-sample.

→ **Do not trade this as a latency edge.** Its legitimate use is a **clean, real-time nowcast of the oil geopolitical
risk premium** for a discretionary/monitoring overlay.

**The one discretionary thing worth watching — a divergence.** Late June: Hormuz-normalize-Jul31 odds *fell* 0.63 → 0.375
(the chokepoint is **not** normalizing as fast as hoped) **while oil kept falling to $70**. The market bled the
geopolitical premium out of crude *faster than the physical situation actually normalized*. Two readings: (a) oil
de-risked on demand/OPEC/macro independent of Hormuz, or (b) crude is complacent and a re-disruption isn't priced. This
is a low-conviction, discretionary "fade-the-complacency" watch — **not** a quantifiable edge.

---

## 4 · Play #2 — Fed July 2026 decision → front-end rates

Context worth flagging: the July market prices **zero cuts and a real ~18% *hike* tail** (+25bps 0.176, +50bps ~0.005),
with "no change" at 0.805 — a hawkish regime, and "no change" *cracked on June 18* (0.925 → 0.79) when "hike 25bps"
jumped 0.024 → 0.246, almost certainly a hawkish June-FOMC repricing.

**Lead/lag (Δprob vs ^IRX 13-week T-bill yield — the most policy-sensitive single-meeting proxy):**

| Pair | N | lag −2 | lag −1 | **lag 0** | lag +1 | lag +2 | floor | verdict |
|------|--:|--:|--:|--:|--:|--:|--:|---|
| Fed "no change" → ^IRX | 46 | −0.24 | −0.33 | **−0.41** | −0.32 | −0.10 | 0.29 | **COINCIDENT** |
| Fed "+25bps" → ^IRX | 61 | +0.20 | +0.27 | **+0.31** | +0.22 | +0.06 | 0.26 | **COINCIDENT** |

Signs are exactly right ("no change" ↑ ⇒ less tightening ⇒ front yield ↓; "hike" ↑ ⇒ yield ↑) and **lag-0 dominates** in
both — the T-bill and the prediction market reprice on the *same* FOMC statements and data prints. **No lead, no edge.**
(10Y `^TNX` shows nothing above the noise floor — a single-meeting question barely moves the long end.)

---

## 5 · Excluded / no-edge (kept for honesty)

- **Crypto price-threshold markets** ("BTC > $56k on Jun 30" = 0.9985; "BTC dip to $57.5k" etc.). These are **digital
  options on spot** — the probability is a deterministic function of the BTC price, so the asset *mechanically cannot
  follow the market*. The scanner labels the theme `crypto_price` and drops it with reason *"no-lead theme."* This is the
  canonical "already priced" case.
- **Thin / non-order-book / off-theme** markets (sports, low-liquidity politics) — excluded by the leverage gate.
- **Newly-created US–Iran *meeting* markets** (≤7 days of odds history) — too short to measure; INSUFFICIENT_DATA. They
  rank high on attention but can't yet be tested.

---

## 6 · Conviction proposal (PROPOSE-ONLY · **DO NOT ARM**)

Per the lane contract, here is what the single best candidate *would* look like as a Conviction trade — and why it
**fails its own gate** today.

```
PROPOSAL  (status: DO-NOT-ARM — for the human to read, not click)
  Thesis        : Polymarket Iran/Hormuz de-escalation odds rising ⇒ oil risk-premium
                  bleeds out ⇒ SHORT crude (Brent BZ=F, the most Gulf-exposed benchmark).
  Asset / dir   : Brent crude — SHORT
  Size          : small, capped (≤ 1% NAV notional), hard max-loss = 0.5% NAV stop
  Evidence for  : mechanism = EIA chokepoint (~20% of global oil); measured Δprob↔Brent
                  correlation correctly signed, |ρ| up to 0.53 over the June-2026 crisis.
  Named disconfirmer : "Was the oil move caused by THIS event, or a confound?"
    → CONFOUND IS LIVE. Late-June oil kept falling even as Hormuz-normalization odds FELL —
      i.e. the crude move detached from the chokepoint and likely reflects demand/OPEC/macro.
      The premium is already OUT of the price ($108 → $70). Shorting now is shorting a
      de-risking that already happened.
  Lead test     : COINCIDENT (lag-0), lead UNCONFIRMED (daily timestamp artifact). No
                  latency-free entry; oil is the faster venue.
  VERDICT       : ALREADY PRICED + confound live + no confirmed lead → DO NOT ARM.
```

**What would change the verdict:** an **hourly** re-run. The machinery already exists —
`PerMarketOddsSource.fetch_odds(cid, fidelity=60)` returns true hourly odds (windowed CLOB), and intraday `CL=F` is
available. If, at hourly granularity with reconciled stamps, a PM odds move in hour *H* still predicts the oil move in
hour *H+1…k* after charging the (wide) CLOB spread, *then* there's something to size. Until that test runs, the honest
answer is **nowcast, not trade.**

---

## 7 · Bottom line

- **3 live plays surfaced; 0 are armable as a price-leading edge.** All measurable relationships are coincident or
  unconfirmed-on-daily-data — which is the *expected, honest* result for deep/fast assets (oil, rates) and re-confirms
  the project's standing read: **Polymarket is a nowcast, not a latency arb.**
- **Highest-value takeaway:** the Iran/Hormuz complex is a high-quality, real-time **risk-premium monitor** for crude —
  worth a dashboard tile/alert, not an automated order.
- **One disciplined next experiment** (hourly Hormuz-odds vs intraday Brent, spread-charged) is the only thing that could
  upgrade this from nowcast to trade. The reusable scanner + lead-lag code (with the timestamp caveat baked in) is the
  deliverable that makes that experiment a one-command re-run.

*Generated by the Cosmu LLM/Conviction lane. Propose-only; the Gate funds nothing here and no human has armed anything.*
