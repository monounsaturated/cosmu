# Price-Data Sweep — Is Price Data the Bottleneck? (2026-06-29)

**Scope:** Deep web sweep of cheap/free + cheap-paid + expensive-if-high-ROI **price** data providers
for COSMU (solo quant). Two questions: (1) does buying PRICE data have high ROI, esp. for the new
EQUITIES/COMMODITIES↔Polymarket-event direction and for the **biggest-timeframe** (deep-history)
backtests; (2) **honest verdict — is price data actually the bottleneck**, or is it hypothesis
diversity / non-price data axes (positioning, options, social-authority)?

Web research only. All prices USD, verified against live pages 2026-06-29 unless flagged UNCERTAIN.

---

## TL;DR (read this first)

- **Is price data the bottleneck? NO.** The binding constraint is **hypothesis diversity / NEW non-price
  data axes** (positioning, options flow, social-authority), exactly as the prior round concluded
  (0/96 hypotheses survive the locked Gate — that is a *signal-supply* failure, not a *price-resolution*
  failure). Buying more/better PRICE data does **not** move the Gate for the crypto lane.
- **BUT there is one genuine, cheap price-data gap worth filling** — and it is *enabling*, not
  edge-generating: **deep, survivorship-aware EQUITY + COMMODITY history** for the new Polymarket-event
  correlation plays (Hormuz→oil→equities→crypto). We have free Stooq/Yahoo/FRED daily already, but it is
  **survivorship-biased** (no delisted names) and **shallow on intraday**.
- **Single best cheap buy (only if/when the equity-correlation lane shows a forward-paper survivor):**
  **EODHD "All-In-One" $99.99/mo** (or the leaner **EOD All World $19.99/mo**) — one cheap API that adds
  delisted-inclusive global equities/ETFs + commodities + **1-min intraday back to 2004** + FX/crypto.
  For the *cleanest* survivorship universe at live-sizing time, **Norgate** (US Stocks Platinum $630/yr +
  Futures $270/yr ≈ $900/yr) is the gold standard — but Windows-only and daily-only, so it is a
  **live-gating** purchase, not a discovery purchase.
- **Deep-history situation for big-timeframe backtests: already good and FREE.** Crypto bars paginate
  *years* deep (Binance Vision + Kraken, keyless — not capped). Equity/commodity **daily** goes back
  decades for free (FRED WTI to 1986, Stooq/Yahoo indices to the 1960s–80s). The only deep-history we
  *lack* is (a) **delisted/survivorship-clean** equity universes and (b) **deep intraday** (<1d) on
  non-crypto — neither is a discovery blocker for daily/weekly Polymarket-event strategies.

**Spend now: $0.** Keep free Stooq/Yahoo/FRED for discovery. Trigger a single ~$20–100/mo EODHD buy
**only** when an equity/commodity-correlation strategy clears the Gate and a paper-forward track is alive
and needs clean delisted history before live sizing. Defer Norgate until that track is live-bound.

---

## 1. The provider landscape (cost · coverage · history · PIT)

### Free / near-free (what we already have, plus the rest)

| Source | Cost | Asset classes | Daily depth | Intraday | PIT / survivorship | API | We use it? |
|---|---|---|---|---|---|---|---|
| **Keyless Binance/Kraken** (ccxt) | $0 | crypto spot | **years**, paginates `since`→now (not capped) | full (1m+) | n/a (live exchange data) | ccxt + Binance REST | ✅ `ingest/bars.py` (incl. `BinanceVisionBarBackfiller`) |
| **Stooq** | $0, no key | equities (US/LSE/WSE…), ETFs, **commodity futures-continuous** (`cl.f` WTI, `cb.f` Brent), world indices, FX (~1,900), crypto | **20–30+ yrs** | hourly/5-min for a *limited* set only; treat as EOD | ❌ **no delisted** (survivorship-biased); good-not-audited | CSV (bulk ZIP best) + pandas-datareader | ✅ **primary** non-crypto source (`data/sources/multiasset.py`) |
| **Yahoo (`yfinance`)** | $0, ToS-gray | global equities, ETFs, FX, crypto, futures-continuous (`CL=F`,`GC=F`), commodity ETFs (USO/GLD/UNG) | decades (`max`) | **1m=last 7d**, 5m/15m=60d, 1h=730d — shallow | ❌ active-only, strong survivorship bias; ~2% req-failure + block risk | `yfinance` lib | ✅ drop-in alternate to Stooq |
| **FRED (ALFRED)** | $0, free key | macro + **commodity *spot* price** series (WTI `DCOILWTICO`, Brent `DCOILBRENTEU`, Henry Hub `DHHNGSP`), USD idx, VIX, rates | **deepest free** — WTI to **1986**, many macro to early 1900s | none (daily floor) | ⭐ **best PIT honesty** (ALFRED vintages = value as-known-on-date, no revision look-ahead). *Caveat:* London gold fix series discontinued ~May 2025 | REST + `fredapi` + pandas-datareader | ✅ macro layer (`adapters/data/equity.py`) |
| **Alpha Vantage (free)** | $0, free key | equities, ETFs, FX, crypto, WTI/Brent/gas endpoints | 20+ yrs | 20+ yrs intraday *but* **25 calls/day** wall makes deep multi-symbol pulls impractical | ❌ active-only | REST/JSON | ❌ (no advantage over FRED for our use) |

*Source URLs:* [stooq.com/db](https://stooq.com/db/) · [stooq commodities board](https://stooq.com/t/?i=557) ·
[fred WTI DCOILWTICO](https://fred.stlouisfed.org/series/DCOILWTICO) ·
[fred Brent DCOILBRENTEU](https://fred.stlouisfed.org/series/DCOILBRENTEU) ·
[yfinance price_history](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html) ·
[yfinance intraday-cap issue #2451](https://github.com/ranaroussi/yfinance/issues/2451) ·
[alphavantage premium](https://www.alphavantage.co/premium/)

### Cheap paid (the real candidates for the new equity/commodity lane)

| Provider | Cheapest useful $ | Asset classes | Daily depth | Intraday depth | PIT / survivorship | API | Best for |
|---|---|---|---|---|---|---|---|
| **EODHD** ⭐ | **EOD All World $19.99/mo** ($199/yr); **+Intraday "Extended" $29.99/mo**; **All-In-One $99.99/mo** (+ fundamentals/calendar/bonds) | 150k+ tickers global equities + ETFs + FX + crypto + bonds; commodities via ETFs/indices | **30+ yrs** (Ford 1972; non-US from 2000) | **1-min from 2004** (US NYSE/Nasdaq, incl pre/post-mkt); 5-min/1h from Oct-2020 | ✅ **delisted included** (EOD for pre-2018 delistings; intraday only post-2021). Retail-grade, not audited-PIT index membership | REST + WebSocket + bulk + Python lib | **Cheap broad global EOD+intraday with delisted coverage via one API** — best fit for the new lane |
| **Polygon.io → "Massive"** | Stocks/Options/Futures **Starter $29/mo each** (per asset class); **Futures NEW 2026** (CME/CBOT/COMEX/NYMEX) | US equities+ETFs (US-only), options, indices, FX, crypto, **futures** | floor **2003**; tiered (Starter 5yr, Dev 10yr) | minute aggs Starter+; tick Dev ($79) — **15-min delayed** below Advanced $199 | ⭐ **strongest PIT of the API set** — genuine `date`-as-of universe + `active=false` delisted + splits/divs + Flat Files | REST + bulk S3 Flat Files + official Python (`pip install massive`) + WS | **Best PIT/delisted + futures via API**; but **US-only equities**, per-asset-class stacking |
| **Tiingo** | Power **$30/mo** | US equities, ETFs, mutual funds, CN A-shares, FX, crypto — **NO futures/commodities** | daily to **1962** (deep EOD) | IEX-only from 2017, **rolling 2,000-pt cap** (≈5d) — not a deep store | adjusted-close strong; **delisted/PIT UNDOCUMENTED** (red flag) | REST + WS; **no bulk price download**; community Python SDK | deep daily US EOD only; **wrong tool** (no commodities, shallow intraday) |
| **Twelve Data** | **Grow $79/mo** (the advertised $29 is *student-only*) | global equities, ETFs, FX, crypto, indices, **commodities = spot/metals only, no futures** | often to 1980 | **UNCERTAIN** (2020 vs 2022 start); shallow | **weakest** — `include_delisted` flag exists but no PIT/survivorship-free story | REST + batch + official Python/Node SDK + WS | global breadth, but PIT-thin and pricier entry |

*Source URLs:* [eodhd.com/pricing](https://eodhd.com/pricing) ·
[eodhd intraday-historical-data-api](https://eodhd.com/financial-apis/intraday-historical-data-api) ·
[eodhd delisted data](https://eodhd.com/financial-apis/delisted-stock-companies-data) ·
[massive.com/blog/polygon-is-now-massive](https://massive.com/blog/polygon-is-now-massive) ·
[massive flat-files](https://massive.com/docs/flat-files) ·
[tiingo.com/pricing](https://tiingo.com/pricing) · [twelvedata.com/pricing](https://twelvedata.com/pricing)

### Expensive (only-if-high-ROI) — and why they are NOT high-ROI for us

| Provider | $ | What it is | Verdict for COSMU |
|---|---|---|---|
| **Norgate Data** | US Stocks **Platinum $630/yr** (to 1990, delisted + **PIT index membership**) or **Diamond $787.50/yr** (to 1950); **Futures $270/yr** (~100 mkts to ~1980, settlement-priced, back-adjusted) | ⭐ The **survivorship-free gold standard** for US/AU/CA equities + global futures, daily | **Best clean universe for backtest→live**, but **Windows-only** (needs a Parallels/VM on the M2), **daily-only (no intraday)**, and **discovery doesn't need clean delisted data** — so it's a **live-gating** buy, deferred until a track is live-bound. ~$900/yr for Platinum+Futures. |
| **Databento** | CME futures sub **$199/mo** (Std); US equities/ICE **$2,500–4,500/mo**; pay-as-you-go $/GB (quoted in-app, not static); **$125 free credit** | Institutional **tick / L3 order-book** microstructure | **Wrong category.** Built for HFT-style microstructure research, priced accordingly. Our edge thesis is explicitly **NOT HFT** (weak signals, small markets, daily/sub-daily). The $125 credit is fine to *sample*, but no live commitment warranted. |

*Source URLs:* [norgatedata.com/prices.php](https://norgatedata.com/prices.php) ·
[norgate stock packages](https://norgatedata.com/stockmarketpackages.php) ·
[norgate futures package](https://norgatedata.com/futurespackage.php) ·
[databento.com/pricing](https://databento.com/pricing) ·
[databento Jun-2026 pricing update](https://databento.com/blog/updates-to-subscription-pricing)

---

## 2. What price data do we LACK (and does it matter)?

**What we already have (verified in-repo):**
- **Crypto:** keyless Binance (incl. Binance Vision deep backfill) + Kraken via ccxt, **paginated years deep**,
  full intraday — `apps/engine/cosmu/ingest/bars.py`.
- **Equity/commodity/FX (free):** Stooq primary + Yahoo alternate (gold/silver/WTI continuous, SPX/NDX
  indices, EURUSD/USDJPY) + FRED macro (WTI to 1986, USD idx, VIX, rates) —
  `apps/engine/cosmu/data/sources/multiasset.py`, `apps/engine/cosmu/adapters/data/equity.py`.
  The adapter **already declares `survivorship_complete = False` and names "Norgate at live"** as the intended
  clean-universe upgrade. The buy decision the operator is asking about is *already anticipated in the code*.

**What we LACK, ranked by whether it actually blocks anything:**

| Gap | Blocks discovery? | Blocks the Polymarket-event lane? | Cheapest fix |
|---|---|---|---|
| **Survivorship-clean / delisted equity universe** (free sources are active-only) | No — present universe proves *signal presence* fine | **Only at live-sizing** (a Hormuz→equities backtest looks too clean without delisted blow-ups) | EODHD delisted EOD ($19.99/mo) for discovery-grade; **Norgate** ($630/yr) for live-grade clean universe + PIT index membership |
| **Deep intraday (<1d) on equities/commodities** | No (daily/weekly is the native timeframe of geopolitical-event plays) | No — Polymarket events resolve on daily horizons | EODHD 1-min from 2004 ($29.99/mo) *if* a sub-daily equity edge ever appears |
| **Single-name equity OHLCV breadth** (we have indices/ETFs/continuous-futures, not a broad single-stock cross-section) | Mild — limits cross-sectional equity strategies | Partially (sector baskets reacting to oil shocks) | EODHD 150k tickers ($19.99/mo) — by far the cheapest breadth |
| **Deeper crypto history** | **No — we already paginate years** | n/a | $0 (already solved; Binance Vision goes to listing date) |

**Net:** the only price-data gap that *enables a new strategy family* (not just polishes an existing one) is
**broad + delisted-aware equity/commodity coverage** for the Polymarket-correlation plays — and it is
**cheap** ($20–100/mo, one API) and **not yet needed** until that lane produces a paper survivor.

---

## 3. HONEST bottleneck verdict (straight, not flattering)

**Price data is NOT the bottleneck. The bottleneck is hypothesis diversity / NEW non-price data AXES.**

Reasoning the operator should weigh, not just accept:

1. **The Gate evidence points at signal supply, not price resolution.** 0/96 hypotheses survived. The deaths
   were funding-arb'd-to-zero, crypto-xsec=disguised-beta, calendar/attention exhausted — i.e. the
   *information* in public crypto price+derived features is used up. Higher-resolution or deeper *price*
   history does not add a **new orthogonal signal**; it re-samples the same price-derived information space
   the Gate already rejected. You cannot price-resolution your way past a signal-supply wall.

2. **The prior round's conclusion holds:** the unlock is a **new data AXIS** — paid **positioning**
   (CFTC COT is free; granular exchange positioning is paid), **options flow / IV surface** (dealer
   gamma, skew — genuinely orthogonal to spot price), and **social-authority** indices. These carry
   information that is *not* a transform of OHLCV. That is where ROI-per-dollar is highest.

3. **The one true price-data ROI is *enabling*, not *edge-generating*.** Buying equity/commodity history
   does **not create an edge** — it lets you *test a new hypothesis family* (geopolitical-event correlation
   across oil→equities→crypto) that you currently cannot even backtest cleanly. That is real value, but it
   is "opening a new lane to search," not "buying alpha." The edge, if any, comes from the
   **Polymarket-event signal + the cross-asset linkage**, not from the price data per se.

**So:** the honest move is **(a) prioritize a new non-price AXIS for the crypto lane** (positioning/options),
and **(b) make one cheap price-data buy ONLY to open the equity/commodity-correlation lane, and only once it
shows a forward-paper survivor.** Spending on premium *price* data (Databento, Twelve Data Pro, Polygon
Advanced) before that would be polishing a substrate that is already adequate — low ROI.

---

## 4. Ranked recommendation

1. **$0 — keep the free stack for ALL discovery.** Stooq + Yahoo + FRED (equity/commodity/FX daily, decades
   deep) and keyless Binance/Kraken (crypto, years deep) are sufficient to *prove signal presence* for the
   new Polymarket-correlation lane. Use FRED for the authoritative oil spot (WTI to 1986, PIT-honest via
   ALFRED); use Stooq bulk ZIP (not per-symbol) to dodge its hit-limit; use Yahoo for commodity ETFs
   (USO/GLD/UNG) with retries. Cross-check overlapping series.

2. **Best cheap paid buy IF the equity/commodity lane produces a Gate+paper survivor → EODHD.**
   Start at **EOD All World $19.99/mo** (delisted-inclusive global equities/ETFs + commodities via one REST
   API + Python lib). Step to **All-In-One $99.99/mo** only if fundamentals/calendar add value, or
   **+Intraday $29.99/mo** only if a sub-daily equity edge appears. This is the **single best cheap data buy**
   on the board: one API, delisted coverage, 1-min back to 2004, global breadth — exactly what the new lane
   needs, at <$100/mo. Wire it via the existing `add-data-source` / `manage-data` path (the equity adapter
   already has the `MarketDataProvider` seam).

3. **Live-gating buy (defer) → Norgate** (US Stocks Platinum $630/yr + Futures $270/yr ≈ $900/yr) for the
   *cleanest* survivorship-free + PIT-index-membership universe before sizing an equity strategy with real
   money. Windows-only (Parallels/VM on the M2), daily-only. The code already names this as the
   "Norgate at live" upgrade. Do **not** buy until a track is live-bound.

4. **Skip for now:** Databento (institutional microstructure, off-thesis, $199–4,500/mo), Twelve Data
   (PIT-thin, $79 real entry), Tiingo (no commodities, shallow intraday), Alpha Vantage paid (FRED beats it
   on free oil history). Polygon/Massive Starter ($29/asset-class) is a *reasonable alternative to EODHD*
   **only if** you specifically need US futures via API with strongest PIT — but EODHD's delisted-global
   breadth at $19.99 is the better single-API fit for the correlation lane.

### Deep-history situation for big-timeframe backtests
**Already solved for free on the timeframes that matter.** Crypto paginates to listing date; equity/commodity
**daily** runs decades deep (FRED 1986 WTI, Stooq/Yahoo 1960s–80s indices). The *only* deep-history gaps are
**delisted/survivorship-clean** universes (EODHD discovery-grade / Norgate live-grade) and **deep intraday on
non-crypto** (EODHD 1-min-from-2004) — neither blocks daily/weekly Polymarket-event backtests.

---

## Appendix — pricing flags carried from source research
- **Polygon.io rebranded to "Massive" (massive.com)** on 2025-10-30; `polygon.io` 301-redirects; SDK now
  `pip install massive`; pricing substance unchanged. Pricing tables are JS-rendered — $ figures
  cross-confirmed via search; Currencies-Advanced exact $ UNCERTAIN (~$99 by parity).
- **Twelve Data:** the widely-cited "$29/$99/$329" ladder is **STUDENT pricing**; real individual entry is
  **Grow $79/mo**. Intraday 1-min start date UNCERTAIN (2020 vs 2022).
- **Databento:** subscription prices **raised 2026-06-22**; $/GB pay-as-you-go is quoted in-app, not static;
  $125 free credit expires 6 months after signup.
- **EODHD:** delisted **intraday** only from 2021; pre-2018 delistings are **EOD-only** — fine for daily
  backtests, a limit only for intraday delisted research.
- **FRED:** London gold fix series discontinued ~May 2025 — source gold from Stooq (`gc.f`) / Yahoo
  (`GC=F`/`GLD`) instead.
