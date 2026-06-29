# Authority V1 — @ElonTrades signal score (composite, not Brier-only)

**Date:** 2026-06-29
**Status:** V1 proof-of-concept of the AUTHORITY feature (proprietary DATA, not a strategy).
**One-line goal:** score one X account by whether its asset *calls* corroborate later price moves.

> The AUTHORITY feature scores *accounts*, not strategies. The output is a trust weight on a
> data source — a number we could one day feed into a strategy — **not** a tradeable edge by itself.
> This V1 is deliberately imprecise (operator's call: "get close to truth, not perfect").

---

## Account used

**@ElonTrades** — `x.com/ElonTrades`. The exact handle resolved, so **no substitution** was needed.
It is a real crypto signal account (founder of "Signal Labs HQ", active since ~2017, ~189K followers),
**distinct from Elon Musk**. Confirmed via web search + the live X search that returned its posts.

## How the tweets were pulled (the one paid step)

- xAI **Live Search is deprecated**; the working path is the xAI **Agent Tools API**
  (`POST /v1/responses`, server-side `x_search` tool) with `allowed_x_handles:["ElonTrades"]`.
- **One** Grok call (`grok-4.20-0309-non-reasoning`) ran 7 `x_search` sub-queries and returned
  **8 asset-mention posts** with timestamp + text + URL.
- **xAI spend for this call: ≈ $0.066** (`cost_in_usd_ticks = 657,079,500` → $0.0657; 33.7k tokens,
  7 x_search calls). Earlier failed probes were rejected pre-billing → **$0**.
- ⚠️ **Footgun fixed:** the `.env.local` keys have **inline `# comments`** on the same line.
  Naive `cut -d=` captured the comment into the key → "Incorrect API key". Strip `#…` before use.
  (Same class as the documented `DATABASE_URL` comment footgun.) Both keys are valid once stripped;
  **OpenRouter key is valid but its $5 monthly free cap is exhausted** (`limit_remaining: 0`).

## How each call was scored (all FREE data)

1. **Asset + direction** inferred by Grok per tweet (bullish / bearish / neutral).
2. **Forward price** from **Kraken public OHLC** (keyless): hourly bars for recent tweets,
   **daily** bars for tweets older than Kraken's ~30-day hourly window (2026-05-30 cutoff).
   Windows: **+1h / +1d / +3d**. Binance is geo-blocked from this host; Kraken sufficed.
3. **Echo filter:** if the price already moved >3% in the call's direction in the ~6h *before* the
   tweet, flag it as a late/echo call. (None of the 8 tripped this here.)
4. **Composite** (primary horizon **+1d**), not Brier alone:
   `composite = 50 + 50·(0.40·payoff + 0.35·edge + 0.25·calibration)`, range 0–100, **50 = no edge**.
   - `edge   = 2·(hit_rate − 0.5)`
   - `payoff = clip(avg_EV_per_call / 2, −1, +1)`  (signed % move if you'd traded each call small)
   - `calib  = 1 − 2·Brier`  (Brier on p=0.75 confidence per directional call)

---

## RESULT TABLE

| account | #asset-calls | #directional | hit-rate (1d) | EV/payoff (cum / avg) | avg-move-when-right | Brier | **composite (0–100)** |
|---|---|---|---|---|---|---|---|
| **@ElonTrades** | 8 (5 neutral, 3 directional) | 3 | **0.333** | **−2.19% / −0.73% per call** | +2.38% | **0.396** | **39.5** |

*(50 = coin-flip / no edge. 39.5 = slightly worse than a coin flip on this tiny sample.)*

### Top-3 movers (biggest signed wins, +1d)

| asset | date (UTC) | direction | signed move +1d | echo? | tweet (excerpt) |
|---|---|---|---|---|---|
| ETH | 2026-05-26 | bearish | **+2.38%** ✅ (ETH fell) | no | "…they're down underwater about $7.4B on their $ETH. Not an entity I'd want holding anything I'm in." |
| BTC | 2026-06-02 | bullish | −1.97% ❌ | no | "Buy $BTC when $MSTR goes to zero." |
| BTC | 2026-06-06 | bearish | −2.60% ❌ (BTC rose) | no | "…strategic reserve is just a wallet where they hold confiscated BTC… R/R today sucks." |

> Only **one** directional call (the ETH-bearish one) was right within 1 day. The other two went
> against the call. The "Buy $BTC when $MSTR goes to zero" tweet is almost certainly **sarcasm**
> mis-tagged bullish by the extractor — a concrete example of the V1's labeling noise.

### Full per-call detail

| ts (UTC) | asset | direction | grain | echo | +1h | +1d | +3d |
|---|---|---|---|---|---|---|---|
| 2026-06-20 13:28 | BTC | neutral | hourly | no | +0.86% | +1.13% | −1.49% |
| 2026-06-06 21:48 | ETH | neutral | hourly | no | +0.01% | +4.88% | +5.85% |
| 2026-06-06 08:26 | BTC | bearish | hourly | no | −0.47% | +2.60% | +2.58% |
| 2026-06-05 18:52 | BTC | neutral | hourly | no | +1.52% | +2.11% | +6.89% |
| 2026-06-03 10:44 | BTC | neutral | hourly | no | −0.32% | −7.21% | −9.85% |
| 2026-06-02 16:25 | BTC | bullish | hourly | no | +0.11% | −1.97% | −8.82% |
| 2026-05-26 11:46 | ETH | bearish | daily | no | — | −2.38% | −2.86% |
| 2026-05-24 19:01 | BTC | neutral | daily | no | — | +0.37% | −3.43% |

*(`+1d`/`+3d` are raw asset move from the post bar; "signed" flips sign for bearish calls.)*

---

## Honest methodology / limitations

- **Sample is tiny (N=8 tweets, only 3 directional).** The composite (39.5) is **not statistically
  meaningful** — it's a plumbing demo, not a verdict on the account. With N=3, one tweet flips the
  hit-rate by 33 pts. Treat every number as illustrative.
- **The x_search returned only 8 posts**, not the requested ~30 — the leanest single call capped its
  sub-query limits. A production run would paginate / raise limits (more xAI $).
- **5 of 8 are neutral commentary**, not trade calls. @ElonTrades mostly posts *macro takes*
  ("crypto isn't dead", "R/R sucks"), not "buy X now" signals. The account may simply not be a
  clean *signal* account — which is itself a useful finding for the AUTHORITY feature.
- **Direction labels are LLM-inferred and noisy.** Sarcasm ("Buy $BTC when $MSTR goes to zero")
  was mis-tagged bullish. A v2 needs a stricter "is this an actionable directional call?" gate.
- **Probabilities are assumed (p=0.75)**, since the account emits no explicit confidence — so the
  Brier term is a proxy, not a true calibration measurement.
- **No multiple-testing / no fees / no slippage** in the EV (it's a gross signed-move tally).
- **Echo filter is coarse** (6h pre-move > 3%); it caught nothing here because moves were small.
- **Look-ahead is controlled** by entering at the first bar **at/after** the tweet timestamp (never
  the bar containing it), so no peeking at the move the tweet might already reflect.
- Price source = **Kraken public OHLC** (free, keyless). Binance is geo-blocked from this host.

## Verdict

- **Signal or noise?** On this slice, **noise** — @ElonTrades reads as a *macro-commentary* account,
  not a directional signal feed. Only 3/8 posts were even actionable, and they hit 1/3 at 1d
  (composite 39.5 < 50). No evidence of edge here, but **N is far too small to condemn the account** —
  this is "no signal detected in a thin sample", not "proven worthless".
- **Is the V1 method worth productionizing?** **The pipeline: yes. This scoring run: not yet.**
  The end-to-end loop works and is cheap (~$0.066/account). The valuable next steps are:
  1. an **actionable-call classifier** (drop neutral/sarcastic posts before scoring),
  2. **bigger pull** (30–100 posts/account, paginated) for statistical power,
  3. **score many accounts** and rank — the feature's value is *relative* authority across a roster,
     not one account in isolation,
  4. only then wire the authority weight as a **feature** into the Gate (never as a standalone edge).

### Reproducibility
Artifacts in `docs/research/_authority_elontrades_v1/`: `grok_calls.json` (raw extracted posts +
xAI usage/cost), `score.py` (the scorer), `score_summary.json` (full numeric output).
