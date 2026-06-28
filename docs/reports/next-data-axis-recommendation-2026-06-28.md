# COSMU Next-Data-Axis Recommendation — 2026-06-28

> Output of a 6-agent deep-research workflow (autonomous run). Web-grounded supplier/source comparison to break the **data wall** (the binding constraint on profit, confirmed again 2026-06-28: public price/calendar/attention exhausted + reachable keyless intraday microstructure killed). Findings-only; the operator decides any spend.

## 1. BLUF

**Pursue Hyperliquid per-account / aggregate on-chain POSITIONING on long-tail (HIP-3) perps. Start TODAY, FREE ($0).** The only candidate that is simultaneously (a) PIT-clean by construction (on-chain settlement = immutable, no COT-style revision trap), (b) free + keyless, and (c) structurally desk-invisible — regulated funds can't casually trade an on-chain perp DEX at size, and per-wallet positioning data doesn't exist on the CEX/PB rails the giants run on. Exactly the "weak signal in a small/niche/desk-invisible market" thesis, and NOT in the exhausted set (single-venue intraday order-flow was killed today; cross-wallet *positioning stress* — who is forced to act — is a different object).

The binding cost is **time, not money**: native history is shallow → hoard-forward, ~2–3 week latency before the Gate can rule. Matches the hoard-forward directive → **today is the right day to stand up the poller.**

**Spend: $0 to start.** Coinalyze (free-key) as a cross-venue cross-check. Escalate to **CoinGlass $29/mo** for a backfill ONLY if the free forward sample shows a whiff. Do NOT pay Nansen (most-crowded desk tool), SpotGamma (no API), or any sentiment vendor up front (PIT-dishonest history).

## 2. Ranked table

| # | Axis | Best source | Free/paid | PIT-honest? | Fit | Cheapest first experiment | Dead-end risk |
|---|------|-------------|-----------|-------------|-----|---------------------------|---------------|
| 1 | **HL per-account/aggregate positioning** (long-tail HIP-3 perps) | HL `/info` API + S3 archive | Free/keyless (S3 ~$/mo if backfill) | Best — on-chain immutable | Highest | Forward-poll OI+funding+top-N positions on 15–25 thin perps, 2wk → Gate one mean-reversion hypothesis | Low-Med |
| 2 | **Aave/on-chain money-market stress** (utilization + large-wallet LTV de-risk, 24–72h vol lead) | Aave subgraph + DefiLlama | Free | Good — block-timestamped, backfillable | High | Backfill LTV/utilization spikes → test 24–72h vol-cascade lead | Med (vol proxy?) |
| 3 | **Prediction-market calibration** (high-prob-underpriced) | Kalshi historical API + Polymarket prices-history | Free/keyless | Strong (Kalshi immutable) | High | Buy 0.85–0.97 contracts N days pre-resolution → settle, per-market BRUT Gate | Med (best-of-N) |
| 4 | Coinalyze aggregated futures positioning (cross-check) | Coinalyze API | Free-key | Medium | Med | Cross-venue L/S confirm layer over axis 1 | Med |
| 5 | LLM voices / social-authority panel | self-captured Reddit/StockTwits/RSS forward | Free ($0); Reddit ToS landmine | Only if captured forward | Med | Forward-hoard 5–10 small-caps 3–4wk → Gate vs shuffle-author + volume nulls | High (retail product) |
| 6 | Token-unlock flow-realization (dumped-vs-HODLed) | DefiLlama Unlocks + on-chain trace | Free | Mixed | Med | Join unlock dates → on-chain tranche→CEX movement | High (lumpy/FDR) |
| 7 | Cross-venue microstructure (lead-lag) | keyless tapes we have | Free | **Broken** (clock-skew) | **Dead for us** | log the disconfirmer, then EXHAUSTED | **Confirmed dead-end** |
| 8 | CFTC COT / aggregate L/S | CFTC public | Free | **PIT trap** (3-day lag) | Low | n/a | High |
| 9 | Nansen smart-money | Nansen API | Paid ~$49–69/mo | Best label PIT | Low (crowded) | n/a | **Very high** |

## 3. The cheapest first experiment (<1 day, $0) — stand up a forward-only HL positioning logger TODAY

- **Data:** poll HL keyless `/info` every 5–15 min for OI + funding + top-N per-account `assetPositions` on **15–25 long-tail / HIP-3 perps** (NOT BTC/ETH/SOL/HYPE — saturated). Append-only, log capture-timestamp, **never re-pull**. Feature per cell: **aggregate net-positioning crowding extreme** + **long-side liquidation density** (notional within X% of liq price / OI).
- **Hypothesis:** a crowding extreme in per-account net positioning on a thin perp predicts a 1–3d mean-reversion, net of maker fees.
- **Hoard ~2–3 weeks**, then BRUT Gate per cell (no pooling).
- **Disconfirmers (pass ALL or KILL):** (1) must FAIL on BTC/ETH (else it's the arbed liquidation-hunt); (2) must NOT survive a shuffled/lagged placebo of itself; (3) must add IC over realized-vol + funding controls; (4) reject if only "copy the biggest winner" works — edge must be the *aggregate* stress feature.

## 4. Adversarial prune (most "new data" is a mirage)

- **Cross-venue microstructure — CONFIRMED DEAD-END.** Lead is 100–700ms (latency play we don't run); dies under frictions (Hou et al. IJF 2023); easiest place to fabricate a fake edge (clock-skew). Close it.
- **Aggregate L/S on BTC/ETH — DEAD** (retail-arbed). **HL whale-hunting on majors — CROWDED** (CoinGlass/HyperTracker/etc. sell it) → axis 1 must be long-tail, aggregate, contrarian.
- **Nansen — likely dead for us** (default desk tool, fastest-decaying). **Sentiment/voices — probably another wall** (LunarCrush CreatorRank is the same product retail; vendor PIT broken; X firehose closed Feb 2026) — worth only the FREE forward test, expect it to fail the nulls.
- **DefiLlama aggregate flows — PIT-compromised** (adapters backfill/recompute; only stablecoin supply is revision-stable). **COT — PIT trap + too slow.** **Token-unlock calendar — arbed** (only the on-chain dumped-vs-HODLed join is novel but lumpy).

## 5. Operator decisions

**Do immediately, $0, no decision:** (1) HL `/info` forward poller on 15–25 long-tail perps; (2) Aave money-market stress backfill probe (fastest to a verdict — backfillable); (3) populate the built-but-inert voices panel via keyless forward-hoard (⚠️ Reddit free tier is non-commercial — keep to research/paper; budget commercial Reddit before scaling if it beats the nulls).

**Paid — only on a proven free whiff, with comparison:** positioning backfill → start Coinalyze (free), pay CoinGlass **$29/mo** only on a whiff (not $299); smart-money → **no Nansen**; options GEX → FlashAlpha free, never SpotGamma; sentiment → no up-front spend (PIT-dishonest), buy realtime only after the free panel beats both nulls.

**Bottom line:** the single highest-leverage move costs **$0** and starts **today** — a forward-only HL long-tail positioning poller — because the only thing between COSMU and a verdict is 2–3 weeks of hoarded forward data, and that clock should already be running. Hold all paid spend behind a proven free-sample whiff.
