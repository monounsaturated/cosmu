# TradingView FREE-tier mining — how to hoard community Pine indicators, and the upgrade trigger

**Date:** 2026-06-30
**Decision context:** COSMU wants to HOARD public community Pine Script indicators from TradingView and run them through our own backtest **Gate** to find needle-in-haystack edges. This is our edge vs Wall St — they don't mine retail scripts. **Decision already made: stay on the FREE tier for now (no paid sub).**
**This doc answers:** (1) what FREE allows, (2) how to collect public Pine at scale + the ToS/legal limits, (3) Pine→portable (re-implement the math on our own compute), (4) webhook alerts, (5) why people pay = the FLIP trigger, (6) competitor scan.

> ⚠️ Not legal advice. The idea/expression and MPL interpretations below are flagged as INTERPRETATION; get counsel before relying on the math-reimplementation line for a money-path product. Sources are dated 2025–2026 and cited inline.

---

## TL;DR — the operating decision

1. **Mining engine = re-implement the MATH, not run Pine.** Pine is closed and runs only on TradingView's servers. "Portable" means we port the *algorithm* into our own Python compute. We already have the machinery: `import-pine` skill + [`pine.py`](apps/engine/cosmu/strategy/pine.py) (Pine→`StrategySpec`) and [`pine_indicators/`](apps/engine/cosmu/research/pine_indicators/) (Pine→correlatable numeric series). **No TradingView account is even on the critical path for the math.**

2. **Do NOT bulk-scrape tradingview.com.** Their Terms of Use flatly prohibit scripts/APIs/scraping/robots "regardless of intended purposes" (enforced by Cloudflare + account/IP bans), and off-platform use of script code is a *separate* copyright violation. The legal, low-risk corpus is **pre-existing openly-licensed GitHub collections** (`awesome-pinescript`, etc.) + **manual human reading** of open scripts to extract the *idea*. See §2.

3. **FREE tier is plenty for a prototype.** Free gives the **full Pine Editor** (write/save/run/backtest), **server-side alerts**, and **free real-time CRYPTO data**. The walls are: **2 indicators/chart, 3 alerts, 1 chart/layout, no webhooks, no CSV export.** See §1.

4. **The FLIP trigger to a paid sub = webhooks for a LIVE signal pipe.** The single thing FREE cannot do that we'd actually want is **POST a live Pine signal to our own endpoint** (webhook). Cheapest tier that unlocks it = **Essential ~$14.95/mo** (confirm in-app: one source says Plus). For crypto this needs **no extra data fee**. We only flip when we have a *validated, gate-passed* ported indicator whose live signal we want to consume in real time — not before. See §5.

5. **Better mining sources also exist** and should run in parallel: **QuantConnect/LEAN** (already Python + OSS, 300k+ shared algos — zero transpilation) and the **MQL5 Code Base** (~4k free readable EAs/indicators, easier to port than Pine). See §6.

---

## 1) What the FREE ("Basic") tier allows

Authoritative source: the official [TradingView pricing page](https://www.tradingview.com/pricing/) (fetched 2026-06-30). Numbers below are from it unless flagged.

| Capability (Basic / Free) | Allowance | Notes |
|---|---|---|
| **Indicators per chart** | **2** | A custom Pine script counts as one slot. This is the main day-to-day wall. |
| **Charts per tab (layout)** | **1** | No multi-chart layouts. |
| **Saved chart layouts** | **1** | |
| **Active price alerts** | **3** | Server-side (fire with browser closed). Expire after ~2 months on Free. |
| **Active technical alerts** | **0** | Indicator-condition alerts are paid. |
| **Historical bars** | **5,000** | Intraday "by minute" history capped ~180 days. Caps backtest depth. |
| **Second/tick intervals** | **No** | Essential+ for seconds, Plus+ for ticks. |
| **Pine Editor** | **YES — full** | Write, save (to TV cloud, private), run custom indicators/strategies, use Strategy Tester / backtester, attach alert logic. ([pineify free-plan guide](https://pineify.app/resources/blog/tradingview-free-plan-features-what-you-get-and-how-to-make-the-most-of-it), [chartwise Pine editor guide](https://chartwisehub.com/tradingview-pine-editor-tutorial/)) |
| **CSV export of chart/indicator data** | **No** | "Export chart data" is **Plus & Premium only** ([official: how to export chart data](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/)). No native CSV of Pine outputs on Free. |
| **Webhooks** | **No** | Paid only — see §4. |
| **Ads** | **Yes** | Removed on any paid tier. |

**Data on Free is plan-independent and exchange-by-exchange:**
- **Crypto: real-time, free for everyone** (streamed direct from exchanges). ([financialtechwiz 2026](https://www.financialtechwiz.com/post/tradingview-real-time-data/)) — this is the important one for us.
- **US equities: ~15-min delayed** on NASDAQ/NYSE/Arca for free users; **exception: CBOE BZX US-equity quotes stream real-time free.**
- **Futures (CME): ~10-min delayed** on free. **Forex: real-time** via TV's LP feed.

**UNVERIFIED on Free:** exact saved-Pine-script count limit (no official stated cap found); any hard session/idle-timeout (none found). Non-blocking.

**Free-tier verdict for mining:** the math/idea extraction doesn't need TradingView at all (§3). If we *do* use a Free account to eyeball scripts and prototype Pine, the only friction is the 2-indicator / 3-alert / no-export walls — none of which block reading open source or building our own port.

---

## 2) Collecting public community Pine at scale + the ToS/legal limits

### How scripts are published
Three modes ([Pine Script: Publishing docs](https://www.tradingview.com/pine-script-docs/writing/publishing/), [Script publishing rules](https://www.tradingview.com/support/solutions/43000590599-script-publishing-rules/)):

| Mode | Source code visible? | Usable by others | Account |
|---|---|---|---|
| **Open-source ("Open")** | **YES** — full source in an expandable window on the page, copyable | Yes, free | Any (incl. Free) |
| **Protected** | No (add-to-chart only) | Yes, free | Paid |
| **Invite-only** | No | Invited only | Premium+ |

- **Default license for open scripts = Mozilla Public License 2.0 (MPL-2.0)**; authors may pick another, but TradingView's House Rules on reuse *preempt* the license on-platform.
- **Reputation incentive biases toward open:** "the only way to gain reputation points is to publish open-source scripts" ([Changes to Script Publishing](https://www.tradingview.com/blog/en/changes-to-script-publishing-on-tradingview-13462/)) → a large share of the public library is open. (Exact open-vs-protected fraction is **undisclosed**; TV only cites "tens of thousands of open-source and free scripts.")
- **Browsable index exists** at [`/scripts/`](https://www.tradingview.com/scripts/): "Popular", [Editors' Picks](https://www.tradingview.com/scripts/editors-picks/), an "Open-source only" filter, sort by recent/popular. Script page URL pattern: `tradingview.com/script/<8-char-id>-<Slug>/`. Pages are **server-rendered** (source is in the HTML, parseable without JS).
- **No official API** to list/fetch scripts (the ToU explicitly names "APIs" among prohibited collection methods).

### The legal line — read this before writing any collector
**Automated access is flatly prohibited.** Verbatim, [account-ban policy](https://www.tradingview.com/support/solutions/43000674726-why-is-my-account-banned-due-to-suspicious-activity/):
> "users are strictly prohibited from employing any automated data collection methods, including but not limited to scripts, APIs, screen scraping, data mining, robots, or other data gathering and extraction tools, **regardless of their intended purposes**."

Enforcement ladder: temporary → permanent **account + IP ban** (Cloudflare-gated site; TLS fingerprinting, JS challenges, Turnstile). No public lawsuit found specifically about script scraping — primary enforcement is bans, not litigation (absence of evidence ≠ evidence of absence).

**Two separate prohibitions stack on bulk-scraping-to-run-off-platform:**
1. **The access method** (automated scraping) violates the ToU — *regardless of purpose*.
2. **Off-platform use** of script content: "Do not, at any time, utilize content … from a product which you do not have license to use" ([Copyright & fair-use rules](https://www.tradingview.com/support/solutions/43000591349-copyright-and-fair-use-rules/)).

The MPL grant on an *individual* open script does **not** cure the *automated bulk-collection* breach — the violation attaches to *how* you obtained it.

**What IS permitted:** a human reading an open script and reusing it within TradingView's intended flow (add to chart, fork in Pine Editor, reuse with credit + "significant improvement" per [House Rules](https://www.tradingview.com/house-rules/)).

**Re-implementing the MATH in another language (INTERPRETATION, not legal advice):** copyright protects *expression* (the specific code), not the *idea / algorithm / mathematical method*. Re-implementing an indicator's formula in Python from scratch is generally outside copyright; copying the literal Pine text is not. If we ever reuse literal MPL-licensed text off-platform, MPL's attribution/license-notice obligations still apply — so prefer clean-room re-implementation of the idea.

### COSMU collection policy (decision)
- ❌ **No automated scraping of tradingview.com.** Not worth a ban + copyright exposure.
- ✅ **Mine pre-existing openly-licensed corpora** off-platform — e.g. [`pAulseperformance/awesome-pinescript`](https://github.com/pAulseperformance/awesome-pinescript), [`ArunKBhaskar/PineScript`](https://github.com/ArunKBhaskar/PineScript) (curated, hand-collected Pine code, openly licensed). This sidesteps the ToU access-method breach entirely.
- ✅ **Mine the IDEA, not the code:** read open scripts manually, extract the *hypothesis/algorithm*, re-implement in our engine. Matches our existing `import-pine` flow (Pine → `StrategySpec`, magic numbers lifted to a fitted `param_space`) and our "the *idea* is the asset, not the source text" model.
- Existing scrapers ([`mnwato/tradingview-scraper`](https://github.com/mnwato/tradingview-scraper), [`imxeno/tradingview-scraper`](https://github.com/imxeno/tradingview-scraper)) target **price/idea data, not Pine source** — none harvest script code. The absence of a bulk-Pine-source scraper is consistent with the off-platform-use prohibition.

---

## 3) Pine → portable: re-implement the math on our OWN compute

**There is no official off-platform Pine runtime.** Pine runs *exclusively* on TradingView servers; the language is a front-end to TV's proprietary engine, not downloadable. "Portable" = re-implement.

### Pine language essentials (what we're porting)
- **Current version: v6** (released Nov 2024, monthly updates through 2025–26). ([v6 docs](https://www.tradingview.com/pine-script-docs/welcome/))
- **Series model:** every variable is a time-series; `close[1]` = prior bar.
- **`ta.*` built-ins:** `ta.sma/ema/rsi/atr/macd/bb/obv/mfi/supertrend`, etc.
- **`request.security()`** for higher-timeframe / other-symbol data (the bare `security()` was removed in v6).
- **Inputs/outputs:** `input.*`, `plot`, `plotshape`.

### The divergence gotchas (why a naive port silently disagrees with TradingView)
1. **RMA / Wilder smoothing.** `ta.rsi/atr/adx` use Wilder's RMA (= SMMA), **not** a plain EMA. A naive pandas EMA diverges. Parity is achievable when RMA is matched.
2. **Warmup / unstable period.** TA-Lib's EMA has a ~50-bar unstable period; TradingView seeds from bar 1. Steady-state matches; **first ~50 bars differ.** Most common silent divergence.
3. **`na` / `nz()` handling** — no 1:1 pandas equivalent; map deliberately to fillna/ffill per function. ([Pineify guide](https://pineify.app/resources/blog/converting-pine-script-to-python-a-comprehensive-guide))
4. **Off-by-one shift bugs.** `close[1]` → `.shift(1)`; a single misplaced `.shift()` silently shifts the whole signal by a bar.
5. **Repainting via `request.security` + `barmerge.lookahead`.** `lookahead_on` without offset returns **future data on historical bars** (look-ahead leakage). HTF values repaint as the higher-TF bar forms. ([TradingView Repainting docs](https://www.tradingview.com/pine-script-docs/concepts/repainting/), [PineCoders FAQ](https://www.tradingview.com/script/cyPWY96u-How-to-avoid-repainting-when-using-security-PineCoders-FAQ/))
6. **Confirmed-bar vs realtime / `calc_on_every_tick`.** On realtime bars `close` flickers intra-bar; a Python port on closed OHLCV only ever sees *confirmed* values (matches TV's historical plot, not the live flicker).
7. **`var` / `varip` persistent state** — initialize-once / persist-across-ticks; no vectorized equivalent, forces a stateful bar-by-bar loop.

> **⚠️ Load-bearing for our build:** items 5–7 are exactly the **leakage / repaint** class that our memory flags as the #1 blow-up risk (a leakage bug *upstream* of the Gate). A vectorized pandas port of an HTF or stateful indicator can silently introduce look-ahead the author's chart never showed. **Every ported indicator MUST pass our feature-side PIT/shuffle tripwire before it becomes a correlatable series.**

### Tooling (what actually exists)
| Tool | Kind | Target | Maturity (2026) | License | Verdict |
|---|---|---|---|---|---|
| **PyneCore** ([PyneSys/pynecore](https://github.com/PyneSys/pynecore)) | Runtime that makes Python behave like Pine (series/`na`/RMA, AST transforms) | **Python** | 159★, v6.5.2 (active, ~daily) | Apache-2.0 | **Best Python option — SPIKE if volume grows** |
| **PineTS** ([LuxAlgo/PineTS](https://github.com/LuxAlgo/PineTS)) | Transpiler + runtime, "1:1 syntax" | **JS/TS only** | 417★, very active | AGPL-3.0 / commercial | Most mature overall, **wrong stack** |
| **PyneSys** compiler | Hosted Pine v6 → PyneCore Python | Python | commercial ($8–45/mo) | paid | Avoid — paid dependency |
| **pynescript** ([elbakramer](https://github.com/elbakramer/pynescript)) | AST **parser only** (no codegen) | Python | 92★ | LGPL-3.0 | Useful as a parser to feed an LLM |
| **pandas-ta / TA-Lib** | Parity TA libraries | Python | mature | OSS | **Use for standard indicators** (RMA-aware: pandas-ta defaults `mamode="RMA"` for ADX/ATR). TV-parity confirmed for RSI/ATR/ADX; **UNVERIFIED beyond those.** |

### Recommended COSMU porting workflow
1. **Map first, transpile second.** Standard indicators → map directly to pandas-ta/TA-Lib (RMA-aware). Don't transpile what's already a parity library call.
2. **Bespoke logic → LLM-assisted manual translation** on the **flat Claude Code sub** (our $0 compute), optionally feeding `pynescript`'s AST. Beats toy transpilers and avoids the paid PyneSys.
3. **PyneCore is the one worth a SPIKE** if we accumulate real volume — Python, Apache-2.0, actively maintained, gives Pine semantics (series/`na`/RMA) for free → shrinks the divergence surface.
4. **Validation gate (mandatory):** export TV-plotted values for the same window, compare the ported series **bar-by-bar**; tolerate tiny float diffs but treat the first ~50 bars and any HTF/`var`/`varip` path as suspect. Then run through our **PIT/shuffle tripwire**. This turns a ported Pine indicator into a *correlatable numeric series* — matches our two-mode model below.

### How this plugs into our existing machinery (verified file refs)
- **`import-pine` skill** ([`.claude/skills/import-pine/SKILL.md`](.claude/skills/import-pine/SKILL.md)) — two modes:
  - **Strategy mode:** Pine with entry/exit → typed `StrategySpec` via [`translate_pine()`](apps/engine/cosmu/strategy/pine.py) (`pine.py:53`). `PINE_FEATURE_MAP` (`pine.py:24`) maps `ta.*` → registry features (`rsi`→`rsi`, `sma/ema`→`ret_Nd`, `stdev/bb`→`bb_z`). **Magic numbers are lifted into a fitted `ParamSpace`** (`_threshold_space` `pine.py:279`, `_lookback_space` `pine.py:294`) — never baked in. API: `POST /strategy/pine`.
  - **Indicator mode:** Pine whose *output* is the signal → a `compute(bars, **params) → IndicatorResult` port in [`pine_indicators/`](apps/engine/cosmu/research/pine_indicators/) (registry in `__init__.py`; base types in `base.py:22`; reference port `ml_liquidity_zone.py`). `IndicatorResult.as_altdata()` (`base.py:37`) converts a series into point-in-time `AltDataPoint`s; `correlate()` (`base.py:93`) measures predictive content (research only, never a money decision).
- **Validation:** [`validate_spec()`](apps/engine/cosmu/strategy/static_check.py) (`static_check.py:14`) rejects any literal threshold (must be a `ParamRef`) and any unknown feature → forces clean specs before execution.
- **Gate / pipeline:** inbox drop `apps/engine/strategies/inbox/*.pine` → [`scan_inbox()`](apps/engine/cosmu/lab/inbox.py) (content-hash idempotent) → [`gate.py`](apps/engine/cosmu/research/gate.py) (pre-registered pass bar, real slippage/impact cost model) → `GateVerdict` PASS/STOP.

**Net:** the hard part isn't infrastructure (we have it) — it's **hypothesis quality + leakage discipline** on the ported math.

---

## 4) Webhook alerts (the live-signal pipe)

- **Minimum tier: a paid plan — Essential and up. NOT on Free.** Free supports only email/mobile-push/on-screen notifications. (One 2026 source says "Plus" using legacy "Pro+" naming; the weight of 2026 sources + TV's rename history put webhooks at **Essential**. **Confirm in-app before committing — this is the build-critical fact.**)
- **What it does (verbatim, [official webhook config](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)):** on trigger, TradingView sends an **HTTP POST** to a URL you supply, **alert message as the body** — JSON → `application/json`, else `text/plain`. So we can POST arbitrary JSON to our own endpoint.
- **Hard constraints (official):** ports **80/443 only**; **3-second** processing budget per request (endpoint must respond fast); **no IPv6**; ~4 fixed TV source IPs to allowlist; **2FA required** to use webhooks at all.
- **Placeholders** (MEDIUM confidence — community-documented, verify against official Pine alerts doc before hardcoding): `{{close}} {{open}} {{high}} {{low}} {{volume}} {{time}} {{ticker}} {{exchange}} {{interval}}`, and for strategies `{{strategy.order.action}} {{strategy.order.contracts}} {{strategy.position_size}} {{strategy.order.price}}`.
- **Frequency:** Only Once / Once Per Bar / **Once Per Bar Close** (leak-safe — confirmed bars only) / Once Per Minute.
- **Latency:** typically low single-digit seconds end-to-end, bounded by the 3s window. **Not HFT-grade, no SLA.**

**Use for COSMU:** a webhook is the cheapest way to pipe a *live* Pine signal (computed on TV's servers, fires with browser closed) into our own ingest endpoint. But note: **we don't need this to mine or backtest** — only if we want TV to be the live *runtime* for a signal. Since we re-implement the math anyway (§3), webhooks are a convenience for a live cross-check / shadow signal, not a dependency.

---

## 5) Why people pay = the FLIP trigger

Price ladder (USD/mo, [pricing page](https://www.tradingview.com/pricing/) 2026-06-30; annual ≈ 16% cheaper; top tier is **Ultimate**, no "Expert"):

| Tier | $/mo | Indicators/chart | Price alerts | Tech alerts | Charts/layout | Hist. bars | Notable unlocks |
|---|---|---|---|---|---|---|---|
| **Basic (Free)** | $0 | 2 | 3 | 0 | 1 | 5K | Pine Editor, server alerts, free crypto RT, **ads** |
| **Essential** | $14.95 | 5 | 20 | 20 | 2 | 10K | **webhooks**, second intervals, no ads |
| **Plus** | $29.95 | 10 | 100 | 100 | 4 | 10K | tick intervals, **CSV export** |
| **Premium** | $59.95 | 25 | 400 | 400 | 8 | 20K | **non-expiring alerts** |
| **Ultimate** | $199.95 | 50 | 1,000 | 1,000 | 16 | 40K | max everything |

**Top reasons people upgrade (the levers):** (1) **more alerts** + **webhook unlock at Essential** (biggest automation driver); (2) more indicators/chart (escape the 2-cap); (3) **non-expiring alerts** (Premium+ only — Essential/Plus alerts expire ~2 months); (4) no ads; (5) multi-chart layouts; (6) second/tick intervals; (7) deeper history (5K→40K bars); (8) CSV export (Plus+).

**Real-time data is a SEPARATE, plan-independent purchase** (critical): your plan tier does **not** include primary-exchange real-time. Crypto / CBOE BZX equities / forex are RT-free; genuine RT for **NASDAQ/NYSE primary, CME, Eurex** is a **per-exchange subscription (~$2/mo each, non-pro)** on top of any plan. ([how to purchase additional market data](https://www.tradingview.com/support/solutions/43000471705-how-to-purchase-additional-market-data/))

### COSMU FLIP trigger (decision)
We stay on **FREE** until **one specific thing becomes true**:

> **FLIP to Essential (~$15/mo) when we have a *gate-passed, paper-validated* ported indicator whose LIVE signal we want to consume in real time, and a webhook from TV's server-side runtime is the cheapest/most-reliable way to get that live signal** (vs us computing it live ourselves).

Do **not** flip for: more indicators per chart (we re-implement off-platform), more history (we have our own deep cache in R2 + can fetch), CSV export (we don't read data out of TV), or alerts count (we alert from our own engine). For crypto, the flip costs **$0 extra** in data fees. If we ever need RT US-equity/futures for a TradFi lane, budget the **per-exchange ~$2/mo add-on separately** — that's orthogonal to the plan tier.

---

## 6) Competitor / additional-source scan

| Platform | Script ecosystem? | Language | Free tier | Export/API/webhook | Mining value |
|---|---|---|---|---|---|
| **QuantConnect / LEAN** | **300k+ shared algos**, OSS engine | **Python**/C#/F# | Free unlimited backtests; paid from $20/mo | Full API, OSS | ⭐ **Highest for our stack — already Python, no transpilation.** Natural fit for "mine community quant logic into our compute." |
| **MQL5 Code Base** | **~3,980+ free, readable** EAs/indicators ([code/mt5](https://www.mql5.com/en/code/mt5)) | **MQL5** (C-like) | Free download | Download | ⭐ **Richest after TV; easier to port than Pine** (imperative loops, no proprietary repaint/`request.security` semantics). ⚠️ per-item license unclear — verify before redistributing. Separate paid MQL5 *Market* is compiled/closed (not minable). |
| **TrendSpider** | First-party JS examples; no large community marketplace | **JavaScript** (+ visual + "Human Language Scripting", AI assist) | Limited free RT | **Webhooks → bots/brokers** ([developers](https://trendspider.com/developers/)) | Low as a *mining* source; the webhook→bot path is the interesting bit. |
| **Koyfin** | None (100+ pre-built indicators + formula builder) | None | Yes (fundamentals-first) | Excel/PNG; API on Enterprise ($59/mo) | ❌ Not a script-mining source. Only a possible fundamentals feed (we have cheaper lanes). |
| **NinjaTrader (NinjaScript)** | Community shares | C# | — | — | Mineable, C#→Python effort. |
| **thinkorswim (thinkScript)** | Community studies, platform-locked | thinkScript | — | No off-platform runtime | Low. |
| **cTrader (cAlgo)** | First-party C# samples | C# | — | — | Moderate. |

**Takeaway:** TradingView is the largest Pine corpus but the most legally/technically friction-laden to harvest. **Run QuantConnect/LEAN (Python, OSS, no transpile) and the MQL5 Code Base (huge, readable, easier port) as parallel mining lanes** — they may give more edge-per-effort than fighting Pine.

---

## Open items / to verify before any spend
1. **Webhook minimum tier = Essential vs Plus** — strong lean Essential; confirm in-app at flip time (build-critical).
2. **pandas-ta TV-parity beyond RSI/ATR/ADX** — validate per-indicator against TV-exported values; don't assume.
3. **MQL5 Code Base per-item license** — check before any redistribution.
4. **Exact saved-Pine-script count limit & Free session timeout** — undocumented; non-blocking.

## Sources (primary)
[TradingView pricing](https://www.tradingview.com/pricing/) · [Script publishing rules](https://www.tradingview.com/support/solutions/43000590599-script-publishing-rules/) · [Pine: Publishing docs](https://www.tradingview.com/pine-script-docs/writing/publishing/) · [Account-ban policy (ToU)](https://www.tradingview.com/support/solutions/43000674726-why-is-my-account-banned-due-to-suspicious-activity/) · [Copyright & fair-use rules](https://www.tradingview.com/support/solutions/43000591349-copyright-and-fair-use-rules/) · [House Rules](https://www.tradingview.com/house-rules/) · [Webhook config (official)](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/) · [Alerts intro](https://www.tradingview.com/support/solutions/43000520149-introduction-to-tradingview-alerts/) · [Export chart data](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/) · [Additional market data](https://www.tradingview.com/support/solutions/43000471705-how-to-purchase-additional-market-data/) · [Pine Repainting docs](https://www.tradingview.com/pine-script-docs/concepts/repainting/) · [PyneCore](https://github.com/PyneSys/pynecore) · [PineTS](https://github.com/LuxAlgo/PineTS) · [pynescript](https://github.com/elbakramer/pynescript) · [awesome-pinescript](https://github.com/pAulseperformance/awesome-pinescript) · [MQL5 Code Base](https://www.mql5.com/en/code/mt5) · [Pineify Pine→Python guide](https://pineify.app/resources/blog/converting-pine-script-to-python-a-comprehensive-guide)
