# Polymarket × Kalshi structural-arb — SCOUT (price-signal-free edge space)

**Date:** 2026-06-27 · **Mode:** EXPERIMENT / SCOUT, zero prod impact, docs + throwaway script only (no merge to a money path)
**Thesis under test (playbook alt #1, `docs/reports/cross-disciplinary-playbook-2026-06-26.md` §"Alternative paradigms" #1):**
> Markets that exist on BOTH Polymarket and Kalshi with MATCHING resolution language can mis-price against each
> other. If `YES_poly + NO_kalshi` is *persistently* < \$1 net of each venue's fees, that is a market-neutral,
> desk-invisible, tiny-ticket **structural arb** — the moat.

**Script:** `apps/engine/scripts/research/polymarket_kalshi_arb_scout.py` (keyless, read-only, one live snapshot — NOT a sweep).

---

## Verdict: **NO-GO** (as a near-term build) — but the data lane is now mapped, and the door isn't nailed shut

The arb does not survive contact with the actual markets, for two independent reasons, *either* of which kills it:

1. **The matching wall (primary).** Across **600** liquid Polymarket markets × **211** Kalshi markets (93 with live two-sided books), **ZERO pairs share genuinely-equivalent resolution language.** Same *topic* is common (Fed, BTC, recession); same *contract* is essentially never — the two venues resolve on different **triggers, reference sources, thresholds, and dates**. A box built on two non-identical payouts is not market-neutral; it's a punt on the *difference*, which carries the full fat tail. **0 matched markets ⇒ 0 measurable arbs.**
2. **Execution asymmetry (independent kill).** Kalshi **excludes France** (alongside Canada and the UK) — the operator's jurisdiction. The *data* is keyless-reachable, but *trading* the NO-Kalshi leg needs a funded Kalshi account that a France-resident operator cannot open. Even a perfect match would be **un-executable on one leg**.

The scout was still worth running: it **maps the keyless data lane on both venues** (a reusable asset) and **measures, with real numbers, why the obvious version fails** — so we don't re-litigate it on vibes.

---

## How many matched markets, and any persistent sub-\$1 arb (the real numbers)

| metric | value |
|---|---|
| Polymarket active markets pulled (Gamma, keyless) | **600** |
| Kalshi markets pulled (8 candidate series, keyless) | **211** |
| Kalshi markets with a **live two-sided orderbook** (keyless) | **93** |
| **Matched pairs with equivalent resolution language** | **0** |
| **Persistent `YES_poly + NO_kalshi` < \$1 net of fees** | **0** (none found; none possible without a match) |

### The closest topic, worked end-to-end (Fed rates) — and why it's still not a box

The single best-looking topic — both venues clearly trade "the Fed" with deep liquidity — collapses on inspection:

- **Polymarket:** "Will there be **no change** in Fed interest rates **after the July 2026 meeting**?" — YES ≈ **0.805**, liquidity ≈ \$911k. This is a **delta** (no-change / +25 / −25 / +50 …) at a **specific meeting**.
- **Kalshi `KXFED-27APR`:** "Will the **upper bound** of the federal funds rate **be X.XX%** as of **April 2027**?" — a ladder of **level bands** (4.25 / 4.00 / 3.75 …) at a **different, later date**.

Delta-at-July-2026 vs level-at-April-2027 are **not the same payout**. Pricing the nominally-closest legs anyway (illustrative only):

```
poly YES 'no change in Fed rates' ask ~0.805
kalshi KXFED-27APR-T4.25 yes_bid 0.39  ->  NO leg cost 0.627
box total_cost = $1.443   (edge -0.443)   poly_fee $0.011   kalshi_fee $0.017
⚠️ STRUCTURAL MISMATCH — legs resolve on different events; the "box" is VOID, not an arb.
```

The same divergence recurs on every topic we probed (resolution text pulled live):

| topic | Polymarket resolves on | Kalshi resolves on | matchable? |
|---|---|---|---|
| Fed rates | **delta** at the **July 2026** meeting | **level band** as of **April 2027** | ❌ different metric + date |
| Bitcoin | venue/EOY price targets, mixed reference feeds | **CF Benchmarks BRTI** 60-sec avg before **8 AM EDT** on a **specific day** (`KXBTCD`) | ❌ different reference + timestamp |
| Recession | typically **NBER's official declaration** | "**two consecutive quarters of negative GDP** per **BEA**, Q4'26–Q4'27" (`KXRECSSNBER`) | ❌ different authority + trigger + window |

Even where the *headline* is identical, the **resolution source** (BRTI vs Binance/Coinbase; BEA-two-quarter vs NBER-declared), the **threshold/strike**, and the **settlement date/time** differ — so one leg can pay while the "matching" leg does not. That residual is exactly the fat-tail (incl. the UMA-whale resolution risk the playbook flags), now **un-hedged**.

---

## The data / credential gap (especially Kalshi access) — the genuinely useful finding

This is the part worth keeping. **Both venues are keyless-reachable for the data this experiment needs:**

- **Polymarket** — fully keyless, already wired in-repo (`cosmu/data/sources/polymarket.py`): Gamma `/markets` + `/events` for discovery and resolution metadata; CLOB `/prices-history` for odds. No account, no key.
- **Kalshi** — keyless on the **`api.elections.kalshi.com/trade-api/v2`** host (the `trading-api.kalshi.com` host 401s without a key):
  - `/markets`, `/events`, `/series/{s}/markets/{m}/candlesticks`, settled `result` — **all public, no key.**
  - ⚠️ **The summary `yes_bid` / `yes_ask` / `last_price` / `volume` fields are NULL in the bulk listing** — easy to mistake for "no data / no access." The live prices are reachable, just elsewhere:
  - **`/markets/{ticker}/orderbook` returns the full public order book, keyless.** Best YES bid = max resting YES-buy price; **YES ask = 1 − (best resting NO-buy price)**. The scout derives a usable two-sided quote on **93** markets this way (NYC-temp, Fed bands, etc.). **This is the access fact that matters: Kalshi prices ARE keyless — via the orderbook, not the listing summary fields.**

**The credential gap is not data, it's EXECUTION.** Reading Kalshi is free and keyless; *trading* it is not:

- A **Kalshi account + KYC + funding** is required to place the NO leg. Kalshi runs in 143 countries but **explicitly excludes France** (also Canada, UK). A France-resident operator **cannot open/fund a Kalshi account** through the normal path → the hedge leg is **un-executable**, regardless of any pricing edge.
- (Polymarket execution is already wired in-repo: `cosmu/adapters/exec/polymarket.py` + CLOB. The asymmetry is entirely on the Kalshi side.)

So: **data credential gap = none** (both keyless). **Execution credential gap = blocking** (Kalshi account unavailable from FR). That, on its own, is sufficient for NO-GO.

---

## Fat-tail / resolution-risk guard (playbook red-team #12) — applied, and it bites harder here

The playbook's instruction to **exclude thin-UMA / ambiguous-resolution contracts** (a UMA whale once falsely resolved a \$7M market) is not a side note here — it is *load-bearing* against this exact thesis:

- A cross-venue box is only neutral if **both** legs resolve **identically and reliably**. The moment resolution language diverges (which we measured: always), the box inherits **both** venues' resolution risk **plus** the basis between their differing rules — the worst of all worlds. The playbook's "never size as if resolution is risk-free" applies with a multiplier.
- We screened to liquid markets (two-sided books only) and avoided the empty multi-leg parlay tickers (`KXMVE…`, which return empty orderbooks). Even within the liquid set, no pair cleared the matching bar — so there was nothing left to even *price* the resolution haircut against.

---

## What the matching wall + execution wall imply for next steps

**Recommended next step: keep this in the freezer, not the backlog — revisit ONLY on a genuine dual-listed, identically-resolving event with an executable hedge.** Concretely, three conditions must ALL hold before this is worth another hour:

1. **A genuinely identical contract** appears on both venues — same reference source, same threshold, same settlement timestamp (most likely on a *single salient binary*: a named election call, a specific CPI print with matching BLS rule, a specific game). The election cycle is the most plausible window.
2. **An executable Kalshi hedge** — i.e. the operator (or a permitted entity) can actually open/fund a Kalshi account, OR the hedge leg moves to a venue the operator already has (the in-repo set: Polymarket / Binance / Kraken / IBKR / Hyperliquid). Cross-Polymarket multi-outcome `Σ(YES) < $1` (the *intra-venue* version, playbook bridge #6a) needs **no second venue at all** and sidesteps the entire execution wall — **that is the strictly better first experiment** if the prediction-arb lane is pursued.
3. **A resolution-risk haircut** sized for the *basis* between the two rules, not just each venue's UMA risk.

**Strictly-better alternative already in the playbook (bridge #6a):** scan **multi-outcome groups on Polymarket alone** for `Σ(YES) < $1` net fee. It is the same price-signal-free, market-neutral idea, but **single-venue** (no Kalshi account, no FR exclusion, no cross-rule basis) and trades on a venue already wired for execution in-repo. If the operator wants a prediction-market arb, that is the one to build first.

---

## Honesty notes / limitations

- **One live snapshot, not a persistence study.** The thesis demands *persistent* sub-\$1; we did not observe over time (and didn't need to — with 0 matched pairs there is nothing to persist). If a true match is ever found, the next pass must log the box over a window, not once.
- **Fees are modelled, not paid.** Polymarket taker = `feeRate·(1−price)` per the in-repo schedule (`cosmu/spine/asset_fees.py`); Kalshi taker = `0.07·(1−price)` (public general-markets cap). Both are conservative (over-charge). Fees turned out to be a rounding error here (≈\$0.01–0.02 on the worked box) — **the matching wall, not fees, is the binding constraint.**
- **No prod impact.** No DB writes, no engine change, no money path touched. The script is a standalone keyless reader; this report is the only durable artifact.

---

## TL;DR for the operator

- **# matched markets:** 0 (of 600 Polymarket × 211 Kalshi screened; 93 Kalshi had live keyless books).
- **Any arb:** none — and none is *measurable* without a match. Closest topic (Fed) "box" = **\$1.44 (negative edge)**, and it's **void** anyway (delta-vs-level, different dates).
- **Access/data gap:** Kalshi DATA is **keyless** (prices via `/orderbook`, not the null listing fields). Kalshi EXECUTION is **blocked** — account needed, **France excluded**.
- **Verdict:** **NO-GO** now. The *price-signal-free prediction-arb instinct is right*, but the cross-venue form fails on matching + execution. **Build the single-venue Polymarket `Σ(YES) < $1` scanner instead** (playbook #6a) — same idea, no second-venue walls.
