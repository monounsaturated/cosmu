# H8 — Liquidation Asymmetry Snap-Back · Offline Event Study

**Date:** 2026-06-25 · **Rank:** #2 on the hypothesis slate · **Mode:** EXPERIMENT ONLY
**Production impact:** ZERO — offline event-study, nothing persisted to prod, no Gate constant touched, docs-only.
**Verdict:** **KILL (today).** The code finding is **CONFIRMED and real**; the edge itself is **untestable today** because no signed-liquidation history is reachable through any keyless path. Re-open only when a signed-liquidation feed is wired.

Artifacts:
- Harness: `apps/engine/scripts/research/h8_liquidation_skew_study.py` (runnable: `python3 … --mode {validate,synthetic,live,all}`)
- Self-contained table: `docs/reports/h8-liquidation-skew-2026-06-25.html`
- Raw results: `apps/engine/scripts/research/h8_liquidation_skew_results.json`

---

## 1. Thesis

Fade the side that got **wiped**. When `long_liq >> short_liq`, forced selling has overshot **down** and one side of a small-cap perp book is exhausted → directional reversion **up** (and symmetrically for `short_liq >> long_liq` → reversion down). The tradeable quantity is the **signed** liquidation skew:

```
liq_skew = (long_liq − short_liq) / (long_liq + short_liq)   ∈ [−1, +1]
```

z-scored causally; on `|skew-z| > 2.0` open the **fade** trade (against the wiped side) at the first bar at/after the PIT-floor `available_at`, hold 1–2 bars, charge real round-trip fees+slippage.

**Pre-registered (locked, no sweep):** `z_threshold=2.0`, `z_window=30`, `fwd_bars=2`, `interval=4h`, `min_n_per_cell=30`, basket = 8 small-cap perps (CRV, LDO, DYDX, GMT, AR, ENS, 1INCH, SUSHI), venue = Hyperliquid (round-trip cost = 2×(4.5 taker + 6.0 slip) = **21.0 bps**).

---

## 2. Code finding — the shipped feature is direction-BLIND (runnable today, CONFIRMED)

The H8 brief claimed the shipped `liquidation-cascade-zscore-v1` feature **sums** the two legs and is blind to direction, while both legs sit in the same keyless payload. **Both claims verified by reading the code:**

- **Parser sums the legs.** `cosmu/data/providers/onchain.py:_points_from_coinglass` line 25:
  ```python
  value = float(row.get("longLiquidationUsd", 0) or 0) + float(row.get("shortLiquidationUsd", 0) or 0)
  ```
  The two legs **are both present in the same row** (line 24 keys on either), and they are collapsed into one scalar stored under `liquidation_cascade`. The feature's own prior literally reads *"A spike in total long+short liquidations…"* (`cosmu/config/feature_registry.py:66`) — direction is discarded by design.
- **Signed split is a surfacing edit, not new data.** Because both legs arrive in the same keyless Coinglass payload, recovering `liq_skew` needs **no new source** — only a different transform.
- **PIT is honest.** `available_at = bucket_close + bucket_seconds` (line 28) — a bucket is only actionable one bucket later. The harness measures forward returns from the first bar at/after `available_at`, never from the bucket-close bar.

**Mechanical proof of blindness** (real fixture `tests/test_free_alt_providers.py:18-19`, plus a matched-total demo):

| bucket | long_liq $ | short_liq $ | shipped SUM (stored) | signed skew | thesis action |
|---|---:|---:|---:|---:|---|
| fixture row 1 | 1,000,000 | 500,000 | 1,500,000 | **+0.333** | FADE UP (longs wiped) |
| fixture row 2 | 250,000 | 750,000 | 1,000,000 | **−0.500** | FADE DOWN (shorts wiped) |
| demo A (longs wiped) | 900,000 | 100,000 | **1,000,000** | **+0.80** | FADE UP |
| demo B (shorts wiped) | 100,000 | 900,000 | **1,000,000** | **−0.80** | FADE DOWN |

Demo A and B carry the **identical** shipped feature value (1,000,000) yet are **opposite trades**. The production feature provably cannot tell them apart. This is a genuine, fixable signal-engineering gap.

---

## 3. Live event study — BLOCKED (no reachable signed-liquidation history)

The edge cannot be measured today. Every keyless historical source for the signal is dead:

| source | status (checked 2026-06-25) |
|---|---|
| Coinglass public history (the wired source) | **Key-gated** — returns `{"code":"30001","msg":"API key missing."}` at both 4h and 1d |
| Coinglass key in `.env.local` | **Absent** (no `COINGLASS_*`) |
| Prod `alt_data` store | **0** `liquidation_cascade` rows ever ingested — the Coinglass cron has been silently failing the whole time (the shipped feature has been getting **no data in prod**) |
| Binance `allForceOrders` REST | **Deprecated** → HTTP 400 |
| Binance `forceOrders` (authed, 7-day) | `BINANCE_API_KEY` in `.env.local` is **invalid format** (`-2014`); and only a 7-day lookback regardless |
| Binance Vision `liquidationSnapshot` dumps | **Directory empty** (dataset discontinued) |

This is the same shape as the #389 Polymarket-odds finding: *PIT-honest mechanism, the data acquisition is the wall.* There is no honest way to build a multi-month signed-liquidation event study from any free source available right now. Fabricating liquidation data and calling it an edge would violate the project's no-synthetic-data rule, so the live study is **not run**.

**N = 0 real events** (data unreachable). **Snap-back sign: untestable.** **Edge-vs-fee: untestable.**

---

## 4. Harness correctness — synthetic null-control (NOT evidence of an edge)

To prove the event-study + Gate plumbing is correct end-to-end before real data arrives, the harness ships a **labelled synthetic control**. These numbers are from FAKE data and are NOT an edge claim — they exist only to show the machinery measures, ranks, costs, and gates honestly.

**Null control** (no embedded signal): pooled N = 936, hit-rates cluster at ~50%, every cell's net edge sits at roughly **−cost** (−21 bps), pooled `sharpe/obs = −0.114`, **DSR = 0.0003**, fails the 0.95 gate. Correct — a pure null cannot pass.

**Micro-edge control** (tiny embedded snap-back, 8e-4·skew): pooled N = 1004, pooled `sharpe/obs = −0.120`, **DSR = 0.0001**, also fails. Honest result — an effect that small is **swamped by the 21 bps round-trip cost**, exactly the lesson a real run would teach if the signal is weak. The plumbing recovers, ranks-by-outlier, and gates real numbers; it does not manufacture a winner.

(Full per-cell tables in the HTML artifact.)

---

## 5. Verdict — KILL (today), with one cheap follow-up

- **As an edge experiment: KILL now.** N = 0; snap-back sign and edge-vs-fee are untestable because no signed-liquidation history is reachable. Per the kill-fast rule, H8 is dropped as a runnable experiment until the data exists. It is *not* disconfirmed — it is *unmeasurable* today.
- **The code finding stands on its own and is the real value here.** The shipped `liquidation-cascade-zscore-v1` is (a) direction-blind and (b) **receiving zero data in prod** (0 ingested rows). That is a latent dead feature, not a working one.

**To unblock H8 (cheap, sequenced):**
1. Confirm whether to pay for a Coinglass key OR stand up a self-aggregated Binance `@forceOrder` websocket collector that buckets signed long/short liquidations going forward (forward-only, but PIT-clean).
2. Once a signed history exists, run `python3 h8_liquidation_skew_study.py --mode live` — the harness is ready; only the data feed is missing.
3. **Independently of H8**, the prod feature should be repaired: either surface the signed skew or graveyard the direction-blind, data-starved `liquidation_cascade` feature so it stops masquerading as live.

---

*Offline experiment. No Gate constant changed, nothing persisted to prod, no engine behaviour altered. Docs-only.*
