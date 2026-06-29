# Intraday order-flow / book-imbalance feasibility spike — GO/NO-GO

**Date:** 2026-06-28
**Author:** autonomous Claude Code run (Opus 4.8)
**Type:** DOCS-ONLY feasibility spike — no ingest wired, no engine code, no Gate change, no money path.
**Roadmap item:** #12 — the one fundamentally NEW signal regime COSMU has never probed is **intraday
market microstructure** (order-flow / book-imbalance / trade-tape dynamics). Every edge tested so far
is a DAILY price/calendar/attention signal, and all 96 hit the same regime/fee wall (0/96 survive).
Question answered here: **is keyless, point-in-time-honest, historical intraday microstructure data even
REACHABLE before we commit to building an ingest path?**

---

## TL;DR — VERDICT: **GO** on data reachability.

Keyless, historical, PIT-honest intraday microstructure data **is reachable** — and the load-bearing field
the dead liquidation feature lacked (a **signed aggressor flag**) is present in the cheapest source. This is
NOT a repeat of the liquidation-cascade trap.

- **Binance Vision** (`data.binance.vision`, already wired for 1m klines) exposes keyless historical
  **aggTrades** (signed via `isBuyerMaker`, back to **2017-08-17**) and futures **bookDepth** snapshots
  (~10s cadence, depth+notional per price-offset level) — both HTTP 200, with `.CHECKSUM` files = revision-safe.
- **Recommended first kill-experiment:** **H1 — aggressive-trade-imbalance reversal on small-cap perps**,
  on Binance Vision aggTrades only (zero new infra: it reuses the existing `intraday_binance_vision.py` /
  `BinanceVisionBarBackfiller` zip-fetch pattern). Cheapest because it needs ONE keyless bulk source already
  in the codebase, the signed flag is free in the payload, and the disconfirmer (shuffle-null) is mechanical.
- **Tie to edge thesis:** intraday microstructure on **small-cap** perps is exactly the
  sub-capacity / desk-invisible / no-LP corner our thesis bets on — too small for a NY desk to bother,
  weak-signal, many-markets. The binding risk is **turnover × fees**, addressed in the hypotheses below.

**DO NOT BUILD INGEST YET.** This is a reachability GO, not a build order. The next step is ONE
pre-registered offline kill-experiment (H1) on a tiny symbol sample, routed through the locked Gate.

---

## 1. Data reachability inventory

All endpoints below were **lightly probed live on 2026-06-28** (curl HEAD/GET, single-file, no bulk download).
Status codes and schemas are observed, not assumed.

| Venue | Source / endpoint | Keyless? | Historical depth | PIT-honesty | Signed flow? | Granularity | Rate / access |
|---|---|---|---|---|---|---|---|
| **Binance** (spot) | `data.binance.vision/data/spot/daily/aggTrades/{SYM}/...zip` | ✅ yes | back to **2017-08-17** (BTCUSDT verified) | ✅ immutable daily zips + `.CHECKSUM` (revision-safe); each row carries an exchange `timestamp` = event time, `available_at` = trade ts (no revision) | ✅ **`isBuyerMaker`** col (signed aggressor) | per-trade (aggregated); ms ts | S3 bulk, no key, no documented per-IP limit on bulk zips |
| **Binance** (spot) | `.../daily/trades/{SYM}/...zip` | ✅ yes | same archive | ✅ same | ✅ `isBuyerMaker` | per-trade (raw, larger) | S3 bulk |
| **Binance** (futures UM) | `.../futures/um/daily/bookDepth/{SYM}/...zip` | ✅ yes | recent verified (BTCUSDT, ARBUSDT both 200) | ✅ immutable daily zips; snapshot ts = event time | n/a (book, not flow) | **~10s snapshots**, levels at ±%-offsets from mid with `depth` + `notional` | S3 bulk |
| **Binance** (futures UM) | `.../futures/um/daily/bookTicker/...zip` | ✅ yes | **404 on daily** (probed 2026-06-25) & **404 monthly** (2026-05) → NOT reliably archived | — | — | — | unusable for history |
| **Bybit** | `public.bybit.com/trading/{SYM}/{SYM}YYYY-MM-DD.csv.gz` | ✅ yes | daily tape, fresh to **2026-06-27** (probed) | ✅ immutable daily gz, ts = event time | ✅ `side` column | per-trade | static file host, keyless |
| **OKX** | `okx.com/cdn/okex/traderecords/trades/daily/{YYYYMMDD}/{INST}-trades-...zip` | ✅ yes | daily verified (BTC-USDT 2026-06-25 = 200, 6.9 MB); `aggtrades` path 404 → use `trades` | ✅ immutable daily zip | ✅ has side | per-trade | CDN, keyless |
| **Kraken** | `api.kraken.com/0/public/Trades?pair=...&since=0` | ✅ yes | **full tape from 2013** (verified: oldest ts 1381095256 = Oct 2013) via `last` cursor pagination | ✅ REST, ts = event time, immutable history | ✅ side (`b`/`s`) **and** order-type (`m`/`l` market/limit) | per-trade | REST, ~1 req/s public; deep history = many paginated calls |
| **Kraken** | `api.kraken.com/0/public/Depth` | ✅ yes | **LIVE snapshot only** (no archive) | ❌ not historical — would require self-recording | n/a | live book | REST |
| **Coinbase** | `api.exchange.coinbase.com/products/{P}/trades` & `/book?level=2` | ✅ yes | **LIVE only** (`/trades` returns recent window; no historical bulk archive) | ❌ not PIT-backtestable history — self-record only | ✅ `side`, µs ts (live) | per-trade / L2 book (live) | REST |
| **Hyperliquid** | `api.hyperliquid.xyz/info` (`recentTrades`, `l2Book`) | ✅ yes (POST) | **LIVE only** — `recentTrades` = recent window, `l2Book` = live snapshot; no historical archive | ❌ not historical | trades have side; book = levels w/ `n` orders | live | POST REST |

### Reachability conclusions
- **PIT-honest, keyless, HISTORICAL intraday data exists** at three venues for **trade flow**:
  Binance Vision (aggTrades/trades), Bybit (`public.bybit.com`), OKX CDN (`trades`), plus Kraken REST
  (full tape from 2013). All carry a **signed aggressor/side** column — the exact field the dead
  liquidation feature lacked.
- **Book/depth history is thinner.** Only **Binance futures `bookDepth`** offers a keyless *historical*
  book-imbalance series (~10s snapshots). Kraken/Coinbase/Hyperliquid books are **live-snapshot only** — to
  use them for backtest you'd have to self-record forward, which is fine for forward-test but gives **no
  historical depth** and is NOT a cheap first experiment.
- **Why this is not the liquidation trap:** the liquidation feature died because (a) Coinglass history is
  key-gated (30001), (b) Binance `allForceOrders` is deprecated (400), (c) Binance Vision
  `liquidationSnapshot` is empty, and (d) `@forceOrder` is **direction-blind**. Trade-flow is the opposite
  on every axis: keyless, deep history, immutable+checksummed, and **direction-carrying** (`isBuyerMaker` /
  `side`). The signal regime is reachable; the liquidation regime was not.

### Existing codebase leverage (reduces build cost of the GO)
- `apps/engine/cosmu/data/intraday_binance_vision.py` + `apps/engine/cosmu/ingest/bars.py`
  (`BinanceVisionBarBackfiller`) already implement the **exact keyless, PIT-seam, checksum-aware,
  append-merge, never-shrink zip-fetch pattern** for Binance Vision 1m klines. An aggTrades fetcher is the
  same pattern pointed at the `aggTrades/` prefix — minimal new plumbing.
- `apps/engine/cosmu/data/sources/registry.py` already defines the `available_at` / `transform_version` /
  `prior` PIT protocol every source must honor — the new flow source slots into it.

---

## 2. Hypotheses (each: signal · horizon · why it pays where daily fails · fee/turnover reality · NAMED disconfirmer)

### H1 — Aggressive-trade-imbalance REVERSAL on small-cap perps  ⟵ recommended first kill
- **Signal:** over a short rolling window (e.g. 1–5 min), the **net signed aggressor volume**
  (taker-buy − taker-sell from `isBuyerMaker`) z-scored per symbol. Extreme one-sided aggressor pressure
  marks a liquidity-taking overshoot.
- **Horizon:** 1–10 minutes (next 1–3 bars on a 1–5m clock). Fade the side that just aggressed.
- **Why it could pay where daily can't:** this is a pure **microstructure / liquidity-provision** premium —
  invisible to a daily price/calendar signal. On **small-cap** perps the book is thin and one desk's market
  order moves price beyond fair value; the mean-reversion is the comp for providing the other side. That's
  the **sub-capacity, desk-invisible, no-LP** corner of the edge thesis: too small to interest a NY desk,
  weak per-trade, but many symbols.
- **Fee/turnover reality:** intraday = HIGH turnover; at Binance spot **10 bps taker** (`spine/venue.py`
  base; futures lower but still real) plus ~5 bps slippage, a taker round-trip is ~30 bps — fatal at this
  frequency. **Must be maker-only** (post the reversion limit, earn the spread) for the arithmetic to clear,
  and capacity-capped to small notional. The experiment must price maker fills + queue/non-fill realism, not
  assume taker.
- **NAMED disconfirmer:** **shuffle-null on the aggressor flag** — randomly permute the `isBuyerMaker`
  labels within each window and re-run. If the "edge" survives the shuffle, it's price-momentum/autocorr
  noise, not order-flow → KILL. (Secondary: it must beat buy-and-hold AND a same-horizon volatility/return
  z-score that uses NO flow data — if plain price-reversion explains it, the flow adds nothing.)

### H2 — Book depth-imbalance short-horizon DRIFT (Binance futures bookDepth)
- **Signal:** top-of-book / near-touch **depth imbalance** = (bid_notional − ask_notional) / (bid+ask)
  from the ~10s `bookDepth` snapshots; positive imbalance → near-term upward drift (the thicker side
  attracts/absorbs).
- **Horizon:** seconds-to-minutes (next few 10s snapshots / next 1m bar).
- **Why it could pay where daily can't:** classic Cont-style queue-imbalance predictability — a *purely*
  microstructure signal with no daily analogue. Works in thin books (small-caps) where imbalance is
  informative and not instantly arbed by co-located makers; our thesis is precisely the markets the fast
  desks ignore.
- **Fee/turnover reality:** highest turnover of the three, so **maker-only is mandatory**, and the ~10s
  snapshot cadence caps the realistic decision frequency (we are NOT HFT — per the edge thesis we do not
  compete on latency, so this must pay on a 1m-decision clock, not a 100ms one). If the edge only exists
  below the snapshot cadence, it is unreachable for us → that itself is a kill.
- **NAMED disconfirmer:** **cadence-degradation test** — re-sample the imbalance to the SLOWEST clock we
  could actually trade on (e.g. 1m) and require the edge to survive net of maker fees. If the edge collapses
  when slowed to a tradeable cadence, it lives only in the latency lane we explicitly don't play → KILL.
  (Plus the standard shuffle-null on the imbalance sign.)

### H3 — Aggressive-flow EXHAUSTION (trend continuation then snap)
- **Signal:** sustained same-side aggressor dominance whose **marginal price impact decays** (each new unit
  of taker-buy moves price less) = buyers exhausting → fade the move. Combines flow intensity (H1) with an
  impact-decay term.
- **Horizon:** 5–30 min.
- **Why it could pay where daily can't:** detects the *turn* in an intraday push that a daily bar can't see —
  again a thin-book, small-cap phenomenon, sub-capacity by construction.
- **Fee/turnover reality:** lower turnover than H1/H2 (only fires on exhaustion events), so taker entry may
  be survivable; still price maker-preferred and cap notional.
- **NAMED disconfirmer:** **placebo-event control** — define synthetic "exhaustion" events at random
  timestamps with matched flow magnitude but NO impact-decay, and require the real-event forward return to
  beat the placebo set by the Gate's margin. If random matched events pay the same, the impact-decay term is
  cosmetic → KILL.

---

## 3. GO / NO-GO verdict

### Verdict: **GO** — keyless, PIT-honest, historical intraday microstructure data is reachable.

The blocker that killed the liquidation lane (no keyless, direction-carrying, historical source) **does not
apply here**. Signed trade flow is keyless, deep (Binance 2017+, Kraken 2013+), immutable, checksummed, and
**direction-carrying**. Book-imbalance history is reachable for one venue (Binance futures `bookDepth`).

### Cheapest first kill-experiment: **H1 (aggressive-trade-imbalance reversal on small-cap perps)**
Reasons it is the cheapest honest first kill:
1. **One keyless source, already half-built** — reuses the existing `intraday_binance_vision.py` /
   `BinanceVisionBarBackfiller` zip pattern, just pointed at the `aggTrades/` prefix. No book-snapshot
   plumbing (H2 needs the bookDepth parser), no live recorder (Kraken/Coinbase/HL books).
2. **The signed flag is free** in the payload (`isBuyerMaker`) — no derivation, no key.
3. **Mechanical disconfirmer** — the shuffle-null on the aggressor labels is a one-line permutation; it
   directly proves the edge is order-flow, not price autocorr, before any money thought.
4. **Pre-registered, no sweep** — one window, one z-threshold, maker-only fees, BRUT per (symbol×venue) via
   the locked scorer — same discipline as the H8 liquidation harness, run on a real source this time.

**Scope the first kill TINY:** ~5–10 small-cap perps, a few months of aggTrades, offline harness under
`scripts/research/`, zero prod side effects, routed through the existing locked Gate. No ingest wiring until
H1 shows a post-fee, post-shuffle-null signal worth deepening.

### Tie to the edge thesis & cost wall
- **Edge thesis fit:** intraday microstructure on **small-cap** markets is the canonical
  speed-light, sub-capacity, desk-invisible, no-LP corner — weak signals in markets too small for the big
  desks, exactly where "solo + bots" is supposed to win. It is a genuinely **NEW signal axis**, not another
  daily price/calendar feature against the same wall.
- **Cost wall is the real risk, not data:** the binding constraint is **turnover × fees**. Every hypothesis
  is therefore framed **maker-only / capacity-capped**, and each disconfirmer is built to kill the signal if
  it only lives below a cadence we can actually trade (we are **not** HFT — per the thesis we don't compete on
  latency). If H1 cannot clear ~10 bps-class round-trip economics at a 1m-decision cadence net of the
  shuffle-null, that is a clean, cheap KILL — and we'll have spent only a research harness to learn it.

### Honest caveats (not blockers, but pre-build risks to retire in H1)
- **Bulk volume:** one BTC aggTrades day ≈ 22 MB zipped; small-caps are far smaller, and the first kill uses
  only a few symbols × a few months — M2-light. A full-universe deep history would need R2 + Modal (defer
  until H1 justifies it). This spike did **not** bulk-download.
- **Maker-fill realism is the make-or-break modeling choice** — a backtest that assumes maker limits always
  fill will lie. The harness must model queue position / non-fill, or the post-fee result is fiction.
- **bookTicker is unavailable** (daily + monthly 404) — H2 must use `bookDepth`, not bookTicker.
