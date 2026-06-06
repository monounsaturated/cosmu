# COSMU — Fastest Path to the POC — 2026-06-06 (data-strategy research)

POC = ONE strategy survives the honest Gate AND a 30-day forward-test. Full transcript: workflow `wdr56q8xt`.
**Reframe: the "0 edges" verdict is suspect — the backtest infra is starved/broken (see grounding).**

## Grounding (verified against the tree)
- **PRICE-BAR CACHE IS EMPTY** — `apps/engine/.cosmu/market_data/` doesn't exist → every Gate run is starved/clipped.
- **Fill model is fantasy** — hardcoded `slippage=0.0005` (`master/execution.py:286`, `spine/engine.py:235`); flat
  5bps on small-caps = textbook SIM→live killer.
- **As-of READ is sound** (`altdata.py:238` filters `available_at <= as_of`) → leak risk is at the WRITE (synthetic lag).
- **xsec-neutral was only run on 3–5 assets** (DSR 0.035); the carry report says re-run on 20–50 names before
  declaring it dead → "pivot off spot-directional" was never honestly tested.

## TOP-5 highest-leverage moves (ranked)
1. **Price-bar backbone — Binance Vision bulk OHLCV** (spot+perp, 2017→now, full universe) via a
   `BinanceVisionBarBackfiller` on the existing `fetch_history`→`write_bars_cache` seam; REST owns the current month.
   *The literal precondition — nothing else is trustworthy until this lands.* Free, ~½ day.
2. **Re-frame btc-social-contagion as a LOW-TURNOVER risk-on OVERLAY** (scale a held position by social-accel z).
   It's the ONLY non-overfit signal (CSCV-PBO 0.000, +ve all 3 regimes, 3.7% maxDD, 0.85 cost_ratio) — it fails
   ONLY because daily-rebalance turnover drags DSR to 0.596; the harness can't express its low-cost form. Edge
   killed by harness, not absence. Pair with the LunarCrush PIT-revision pre-req. Free, engineering-only.
3. **Forward-collected `available_at = ingested_at`** in the SIM path (+ a `forward_collected` flag the SIM Gate
   reads) — kills the guessed synthetic lag → makes the Simulation stage honest. Free, code-only.
4. **Realistic paper-fill** (half-spread from recent H-L + size-vs-ADV impact + maker/taker), replacing flat 5bps.
   Free (Binance book), medium effort. Costs lie most on the small-caps where the social/xsec edge supposedly lives.
5. **Dynamic universe builder + PIT survivorship calendar** (`instruments(symbol, listed_at, delisted_at)`) so xsec
   gets a real 20–50-name test without survivorship bias. (`PERP_UNIVERSE` is a hardcoded 30-tuple today.) Free, ~1 day.

## FREE data to backfill FIRST (strict order; all keyless, multi-year, PIT-clean)
1. **Binance Vision OHLCV** dumps (the backbone — move #1).
2. **Binance Vision `metrics/` archive** (multi-year OI + long/short ratios) — REST caps `openInterestHist` at 30
   days; the archive is the ONLY free path to deep OI. Unblocks the funding/OI-gated momentum (edge-plan TOP-1).
3. **Binance Vision `fundingRate/` archive** (contract-launch→now) — deep funding in one pull.
4. **`fundingInfo` interval ingest + annualization fix** — `carry_ablation.py:100` / `altdata.py:374` sum raw rates
   × hardcoded 3×/day, but many perps moved to 4h/1h settlement → carry understated **2–8×**. Any funding edge is a
   phantom until per-symbol interval is correct.
5. **DefiLlama stablecoin supply + DEX volume** (reuse `DefiLlamaTvlProvider` next-day-PIT pattern) — macro-liquidity gate.
6. **Deribit DVOL deep backfill** (BTC/ETH, 2021→now) — vol-regime meta-label for the social overlay.

## Honesty fixes (free, trivial, de-noise the Gate)
- **`exchange_netflow` is MISLABELED** (`altdata.py:727`) — it's actually `globalLongShortAccountRatio` with a
  fabricated "net inflows" prior + only 30 days. **A fake feature manufacturing false positives — rename/disable it.**
- **FRED point-in-time vintage** — use the ALFRED vintage endpoint so macro series are as-of-correct, not revised.

## Honest bottom line
The fastest path is **NOT more strategies** — it's **fix the harness + data so the Gate is trustworthy, then re-run**:
empty bar cache → deep Binance Vision backfill; P0 risk_on bug → fix; fake netflow + funding annualization → fix;
flat-5bps → real fills; 3-name xsec → real 20–50 universe. THEN re-run the cohort. Only after that is "spot-directional
is dead" an honest conclusion. Most-likely first survivor: the btc-social risk-on overlay (move #2).
