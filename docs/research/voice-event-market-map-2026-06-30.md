# Voice / speech-resolvable event-market map — COSMU realtime-voice lane — 2026-06-30

**Question:** COSMU wants to trade prediction-market contracts that resolve by *watching/listening to a live
event* — "will [person] say [word] N times", "will [team] score before [time]", debate/presser outcomes. Map
(1) the market TYPES, (2) live data sources + access/latency/legality, (3) size/vig/resolution speed + whether a
tradable window exists for a non-HFT solo, (4) the per-type edge thesis + bot-saturation honesty, (5) a shortlist
of the highest-fit event-types to START with.

---

## TL;DR — bottom line up front

- **The lane is real and the markets exist today.** Polymarket ran a "What will Trump say during the State of
  the Union" market that did **$3.4M volume** (launched Jan 5 2026, 44 outcomes); Kalshi runs **`KXFEDMENTION`**
  (Powell-presser mention markets, 44 terms in Jan 2026). Word-count, mention, first-word and live-sports
  contracts are all live.
- **There are three different "edges" here, and two of them are dead-on-arrival for us:**
  1. **Resolution-snipe** (be first to hit the oracle when the event ends) — **DEAD.** Already killed in our own
     UMA deep-dive ([[session_checkpoint_2026-06-29]]): median winner sits at **0.9995 at ProposePrice**, the
     window only exists in fast-crypto, sub-100ms bot turf.
  2. **Broadcast-latency front-run** (see the utterance and reprice before others) — **mostly bot turf.**
     Polymarket's live feed is ~13–15ms, warm round-trips ~21–23ms; **73% of arb profit goes to sub-100ms bots**.
     Everyone — us and the bots — watches the SAME 6–30s-delayed broadcast, so the race from "feed shows it" →
     "book reprices" is a millisecond race we lose.
  3. **Comprehension / interpretation edge** (be *more accurate* about the live conditional probability than the
     marginal trader — count words exactly, know the speaker's patterns, read what's coming) — **this is the only
     edge a solo+LLM can actually hold.** It is a *seconds-to-minutes* human-scale repricing window, not a
     millisecond race.
- **Highest-fit to START (ranked):** ① **speech word-count / frequency-threshold markets** ("say X N+ times")
  on a real-time ASR+counter, trading the *ambiguous middle thresholds* early in the event; ② **long-tail
  mention binaries** (improbable words, pre-modeled base rates + live catch). **AVOID for core:** live-sports
  win-probability and "hawkish/dovish tone" markets — those are sportsbook + macro-desk + bot turf with a data
  feed we can't match.
- **What this lane IS:** an **opportunistic, episodic sniper lane** (SOTU is annual, Fed pressers ~8/yr, debates
  election-cycle) — it fits the **[[aggressive_target_2026-06-30]]** "asymmetric sniper, 2–3X-in-a-day probe"
  framing precisely. It is **NOT** a steady compounding throughput engine, and it does **NOT** fit the
  statistical Gate (each event is N≈1, unique) — it is an **LLM-lane / human-armed Conviction** strategy
  ([[strategy_types_quant_llm_2026-06-29]]), not a Quant-Gate strategy.

---

## 0. How this fits COSMU (read before the map)

| Frame | Where it lands |
|---|---|
| Strategy type | **LLM** (not Quant). Created by chatting with Claude, guardrailed, **human-armed**, **propose-only** — not the statistical Gate. Each event is unique → no FDR/CSCV cohort applies. |
| Lifecycle | Can't paper-forward in the usual sense (events are one-shot). Validation = **dry-run on past recorded events** (replay the broadcast, run the counter, check it would have been right *before* the cross) + tiny live probes. |
| Cadence | **Episodic.** ~1–2 high-value events/month at best. A sniper probe, not a money pump. |
| Target fit | Matches the **2–3X-in-a-day asymmetric** goal: a $200 stake on a mispriced 0.30→0.90 threshold *is* a 3× day. The "spike" doctrine (short probe + store result) is the right posture. |
| Capital path | Polymarket (USDC, on-chain — we already have verified access) and Kalshi (USD, regulated). Both **usable** per [[venues_all_usable_2026-06-18]]; never a jurisdiction blocker. |

---

## 1. Market TYPES (what's resolvable by watching/listening)

| # | Type | Example | Resolution source | Resolves | Our fit |
|---|---|---|---|---|---|
| **A** | **Mention binary** — "will [person] say [word] *at all*" | Polymarket SOTU 44-outcome board; Kalshi `KXFEDMENTION` ("shutdown", "layoff", "yield curve") | Official transcript / video, watched by resolver | At end of event (~2h UMA liveness / ~3h Kalshi) but **price ratchets live** | **GOOD (long-tail)** |
| **B** | **Word-count / frequency threshold** — "say [word] **N+ times**" | Polymarket SOTU "America/American **50+** / **25+** times" | Count from transcript | At end; **live path is a counting race** | **BEST** |
| **C** | **First-mention / ordering** — "what will [person] say **FIRST**" | Polymarket "What will Trump say first" (8 outcomes) | First sentence/paragraph | **Very early** in event, high variance | **NICHE / sniper** |
| **D** | **Tone / policy-signal** — "will Powell signal a cut", hawkish/dovish, "will [candidate] apologize" | Fed-decision adjacent, debate-outcome | Human judgment of *meaning*, often + later official action | Slow / interpretive | **LOW (desk+bot turf)** |
| **E** | **Live sports in-game** — win-prob, spread, total, props | Kalshi NFL/NBA/soccer; props (soccer BTTS, NBA player points), "score before [time]" | Official scoreboard/data feed | Fast, ~3h settle; **continuous live reprice** | **AVOID core** (data-feed gap) |
| **F** | **Behavioral / visual event** — "will the mic be cut", "handshake", walk-out | Debate/ceremony spectacle markets | Video (often *vision*, not voice) | During event | **Out of scope** (vision lane, not voice) |

> The honest grouping: **B and A are mechanical and verifiable** (a word was said / counted — checkable, low
> dispute) → tractable for an LLM. **D and E require either subjective judgment (D) or a licensed low-latency data
> feed (E)** → not our edge. **F is a different (vision) lane.**

---

## 2. The three edges — decomposed (the analytical spine)

Every "voice market" play is secretly one of three bets. Naming them is the whole point, because two are traps.

### 2.1 Resolution-snipe — ❌ DEAD (do not chase)
Be the wallet that proposes/takes the final price the instant the event ends and the outcome is certain.
**We already killed this.** [[session_checkpoint_2026-06-29]]: on Polymarket the **median winning trade is
0.9995 at ProposePrice** — by the time resolution is mechanical, the price is already ~1.0; the only exploitable
window is in fast-crypto markets and it is **sub-100ms bot turf**. UMA undisputed liveness is ~2h, disputed 4–6
days — none of that is a trade for us. **Verdict: closed.**

### 2.2 Broadcast-latency front-run — ⚠️ mostly bot turf
See the utterance on the feed and reprice before the rest of the book.
- **The crippling fact: the broadcast is delayed for EVERYONE.** Live TV / official streams run **6–30s** behind
  real-time (high-latency linear up to 30–45s+). C-SPAN, White House YouTube, network feeds, Fed webcast — all
  buffered. You and the bots watch the *same delayed picture*.
- So the race is *not* "real event → me", it's "delayed feed shows it → book reprices". **Bots win that race**
  (13–15ms feed, 21–23ms round-trips; 73% of arb to <100ms actors).
- **The only way this edge is real for us:** a *lower-latency feed than the delayed broadcast* — physically
  on-site, a press-pool/raw stream, or a faster CDN edge — giving a few-second lead over delayed-broadcast
  watchers. Hard, fragile, and the high-value events (SOTU, Fed) are exactly where pro feeds already exist.
  **Verdict: don't build the lane around this. Treat any latency lead as a bonus, not the thesis.**

### 2.3 Comprehension / interpretation — ✅ OURS (the only durable one)
Be *more accurate about the live conditional probability* than the marginal trader.
- The market question forces **interpretation**: is the running count going to cross the threshold? did that
  ambiguous utterance count under the resolution rule? given the speaker's known patterns and the section coming
  up, what's P(remaining outcomes)?
- A **solo + real-time ASR + LLM** can hold an exact running count and a context-aware forecast while the crowd
  (on a delayed feed, eyeballing it) is genuinely uncertain. The mispricing on an *ambiguous-middle* threshold
  persists for **seconds to minutes** — a human-scale window wide enough for a non-HFT solo to enter and exit.
- This is the **edge_thesis** in its purest form ([[edge_thesis]]): weak signals + small markets + cheap social/
  media data + speed-of-comprehension, *not* speed-of-wire. **Verdict: build here.**

> **One-line doctrine:** *We are not racing the wire (we lose) and not sniping the oracle (it's dead). We are
> out-comprehending the marginal human on thin, mechanical, verifiable sub-questions during the live event.*

---

## 3. Live data sources + access / latency / legality

| Source | For types | Access | Latency | Cost | Legal |
|---|---|---|---|---|---|
| **Official video/audio** (White House live, C-SPAN, Fed webcast, network sims) | A,B,C,D,F | Public, free | **6–30s+ delayed** (shared by all) | Free | Watching a public broadcast — fine |
| **On-site / press-pool / raw stream** | A,B,C | Hard for a solo; some raw CDN edges marginally faster | Seconds faster than linear TV | — | Gray; not worth chasing |
| **Real-time ASR (speech→text)** — local Whisper, or Deepgram/AssemblyAI streaming, or realtime GPT/Gemini audio | A,B,C | API or local model | Streaming, ~0.5–2s after audio | Local Whisper ≈ compute-only; streaming APIs ≈ cents/min | Fine |
| **LLM comprehension layer** (count, context, "coming-up" forecast) | A,B,C | Claude Code flat sub for design; cheap inference for live count | Real-time | Flat sub for build; lean live inference ([[env_keys_and_llm_cost_2026-06-29]]) | Fine |
| **Official transcripts** (WH, Fed) | A,B (post-hoc check) | Public, but **lag the live event** | Minutes–hours late | Free | Fine |
| **Licensed sports data** (Sportradar/Genius low-latency) | E | Expensive, licensed | Sub-second (bots have it) | $$$$ — we don't have it | Licensed |
| **Polymarket CLOB API / WS** (book + place orders) | all | We have verified on-chain access | ~13–15ms feed | Gas/USDC | Usable |
| **Kalshi API** | A,D,E | Account + API key (regulated, KYC) | Exchange-grade | Fees apply | Usable |

**Data takeaways:** (a) the *broadcast* feed is free, legal, and the great equalizer (everyone is equally
delayed → kills the pure-latency edge); (b) the *comprehension* stack (ASR + counter + context LLM) is cheap and
the only place we add value; (c) **sports is where we have a hard data-feed disadvantage** (no licensed
low-latency feed) — another reason to avoid E for core.

---

## 4. Size / vig / resolution speed / tradable window

| Dimension | Reality | Implication for a solo |
|---|---|---|
| **Market size** | Headline boards decent: SOTU "what will Trump say" **$3.4M**. Individual *sub*-markets much thinner (~$10k–$200k). Fed-mention smaller. Kalshi sports far bigger (but bot-dense). | Thin sub-markets = **room to be right before the crowd**, but **wide spreads** and **shallow books** cap size. Sniper sizing ($100s–low-$1000s), not size. |
| **Vig / cost** | Polymarket: historically **0 explicit trading fee**; the real cost is the **bid/ask spread** (thin = wide) + gas. Kalshi: explicit per-contract fees. We always charge **today's** fee schedule in backtests ([[fees_always_today_2026-06-18]]). | On thin threshold markets the **spread is the tax** — only trade when your edge clears it. |
| **Resolution speed** | UMA undisputed **~2h liveness**; disputed **4–6 days**. Kalshi **~3h** after outcome known. | Irrelevant to our play — **we exit during/at end of the event, not at resolution.** Disputed-resolution risk is a *tail*, not the trade. |
| **Tradable window** | **The window is the live event itself** (minutes–~1h). On an ambiguous-middle threshold the mispricing persists **seconds-to-minutes** while the outcome is genuinely uncertain. | **YES — a real window exists for a non-HFT solo**, but ONLY on the comprehension edge (§2.3), and ONLY while the outcome is uncertain. Once it's near-certain it snaps to 0.99 and the window is gone. |

### Worked example (concrete, honest)
> Market: **"Trump says 'tariff' 15+ times"** during a major address. Pre-event ≈ **0.45** (uncertain).
> - Minute 20, speech ~40% done, running count = **11**, and a known trade-policy section is coming. Your
>   real-time estimate ≈ **0.80**. Book sits at **0.55** (humans on delayed feed, eyeballing).
> - You buy YES at 0.55. Count climbs through the trade section; book reprices to 0.90. You sell (or hold to ~1.0).
> - **Window:** the minutes while P was genuinely between 0.5 and 0.9. **Edge source:** exact count + knowing the
>   section was coming — *comprehension*, not wire speed.
> - **Why a dumb counting-bot doesn't fully eat this:** on a thin sub-threshold it may not be watching THIS market,
>   and it has the count but not the *"a tariff section is next"* forecast. That forecast is the alpha.

Contrast — the **"America 50+ times"** market is **un-tradable**: it's ~1.0 before he opens his mouth. The
headline markets carry no edge; **the ambiguous mid-thresholds and long-tail words do.**

---

## 5. Edge thesis per type + bot-saturation honesty

| Type | Edge thesis | Bot saturation | Verdict |
|---|---|---|---|
| **B — word-count threshold** | Exact real-time count + context forecast beats the crowd's eyeball; trade ambiguous mid-thresholds before the cross | **Moderate.** Counting bots exist, but the long tail of thresholds + **resolution-rule edge cases** (does "America's"/a quoted use count? — pluralization counts, AI-audio doesn't) leave gaps | **START HERE** |
| **A — mention binary** | Pre-event base-rate model of *improbable* words + live catch the instant it's said | **Moderate–high** on obvious words (bid to ~1 instantly); **low** on the long-tail improbable terms | **SECOND (long-tail only)** |
| **C — first-mention** | Speech-preview/leak knowledge, or fastest comprehension of the opening lines | Low liquidity, **high variance** | **Sniper side-bet, paper first** |
| **D — tone / policy-signal** | "Tone/pauses/sentiment" read of meaning | **High** — macro desks + sentiment bots; subjective resolution = dispute risk | **AVOID** (interpretive, slow, contested) |
| **E — live sports** | Faster/better live win-prob | **Saturated** — sportsbooks + quant bots with **licensed sub-second feeds we don't have** | **AVOID core**; maybe obscure props later |
| **F — behavioral/visual** | Watch for the spectacle moment | Vision lane, not voice | **Out of scope** |

**The honest tone/sentiment verdict:** the romantic version of this lane — "our LLM reads the *tone*, the
*pauses*, the *sentiment*, and front-runs the room" — is the **weakest, most contested** play. Tone is subjective
(→ resolution disputes), slow-resolving, and exactly what macro desks already model. **Mechanical, verifiable
word-counting beats subjective tone-reading** on every axis that matters: dispute risk, edge measurability, and
bot-gap. Lead with counting, not vibes.

---

## 6. Shortlist — what to START with (ranked)

1. **★ Speech word-count / frequency-threshold markets (Type B).** Build a real-time **ASR → counter →
   context-forecast** loop. Trade the **ambiguous-middle thresholds early** in marquee events (SOTU, major
   addresses, Fed pressers where count markets exist). Highest fit: mechanical, verifiable, comprehension-edged,
   only moderately bot-saturated on the long tail.
2. **Long-tail mention binaries (Type A).** Pre-event model of *improbable* words (base rate from past
   transcripts) + live catch. Second because the obvious words carry no edge and the long tail is thin.
3. **(Paper-only) First-mention sniper (Type C).** Keep as a high-variance probe when there's a structural read
   (leaked themes, predictable opener). Don't size it until a track record exists.

**Explicitly AVOID for core:** live-sports win-prob (Type E — licensed-feed disadvantage + saturation),
tone/policy-signal (Type D — subjective, contested, desk turf), visual/behavioral (Type F — wrong lane).

**And never chase:** resolution-snipe (§2.1, already dead) and the pure millisecond latency race (§2.2, bot turf).

---

## 7. Honest risks & failure modes

- **The resolution rule IS the alpha *and* the trap.** Polymarket SOTU rules: *pluralization/possessive counts,
  AI-generated audio/video does NOT, anything outside the named scheduled event does NOT.* Misjudge an edge case
  and a "win" becomes a loss. Read the rule before every trade; it's where careless traders donate.
- **Headline markets are pre-priced to ~1.0** — no edge. The entire opportunity is the **uncertain middle**.
- **Thin sub-markets** → wide spreads, shallow books, low capacity. This is a $100s–low-$1000s sniper, not a
  scalable engine.
- **Episodic** → can't compound; a few events/month. Don't let it masquerade as throughput.
- **A counting-bot can still front-run you** on a market it's actively watching. Our defense is the *context
  forecast* + targeting sub-markets bots ignore — both erode as the lane gets more competitive.
- **Disputed-resolution tail** (4–6 day UMA path, even a $60M+ dispute precedent exists) — rare but real; size
  so a frozen position can't hurt.
- **Not a Gate strategy** — N≈1 per event. Validation is replay-on-recordings + tiny live probes, and it stays
  **human-armed, propose-only.** Resist the urge to "let it run."

---

## 8. Minimal build to test (propose-only, no money path)

A 1–2 day spike to prove or kill the comprehension edge **before** any capital:
1. **Record + replay harness:** grab the recording of a *past* SOTU/Fed presser + the historical Polymarket/Kalshi
   tick data for its threshold markets.
2. **ASR + counter:** local Whisper (free) → running per-word counts, timestamped.
3. **Backtest the comprehension edge offline:** at each tick, compare *our running-count-implied P* vs the
   *market price*. Measure: **did our estimate cross the eventual outcome before the market did, by enough to
   clear the spread?** Per-threshold, ranked by the outlier (never a pooled mean — [[feedback_surface_all_compute]]).
4. **If ≥ a few thresholds show a persistent seconds-to-minutes lead → tiny live probe** on the next live event
   ($100s), human-armed. **If not → kill the lane and store the result** (spike doctrine).

No keys, no money path in this doc. The replay harness is the honest gate: if we wouldn't have beaten the book
on *recorded* events, we won't on live ones.

---

## Sources
- [Polymarket — What will Trump say during the State of the Union address (2026, $3.4M, 44 outcomes)](https://polymarket.com/event/what-will-trump-say-during-the-state-of-the-union-address)
- [Polymarket — What will Trump say first during the 2026 SOTU (8 outcomes)](https://polymarket.com/event/what-will-trump-say-first-during-the-2026-state-of-the-union-address)
- [Polymarket — What nicknames will Trump say during the 2026 SOTU (21 outcomes)](https://polymarket.com/event/what-nicknames-will-trump-say-during-the-2026-state-of-the-union-address)
- [Crowdfund Insider — Polymarket lets you bet on what Trump will say at the SOTU](https://www.crowdfundinsider.com/2026/02/263862-what-will-trump-say-during-the-state-of-the-union-address-polymarket-lets-you-bet/)
- [Kalshi — What will the Fed Chair say at the press conference (KXFEDMENTION mention markets)](https://kalshi.com/markets/kxfedmention/fed-mention)
- [OddsAssist — Mentions prediction markets: how they work & strategies](https://oddsassist.com/prediction-markets/mentions/)
- [Kalshi — Trade on live events (in-game sports)](https://kalshi.com/sports)
- [SI — Kalshi review: best sports trading platform 2026 (live in-game, exchange model, ~3h settle)](https://www.si.com/prediction-markets/reviews/kalshi)
- [Yahoo Finance — Arbitrage bots dominate Polymarket with millions in profits](https://finance.yahoo.com/news/arbitrage-bots-dominate-polymarket-millions-100000888.html)
- [Laika Labs — Polymarket bots vs humans 2026 (>30% wallet activity, 37% vs 7–13% profitable, 13–15ms feed, <100ms arb capture)](https://laikalabs.ai/prediction-markets/polymarket-bots-vs-humans)
- [Polymarket docs — Resolution (UMA optimistic oracle, ~2h liveness, disputed 4–6d)](https://docs.polymarket.com/concepts/resolution)
- [Start Polymarket — How markets resolve: the 2-hour rule](https://startpolymarket.com/learn/how-markets-resolve/)
- [BoxCast — Live-stream latency primer (6–30s typical, 30–45s+ high)](https://www.boxcast.com/blog/live-stream-video-latency)
- [The Defiant — $60M+ Polymarket dispute puts UMA token-voting oracle on trial (disputed-resolution tail risk)](https://thedefiant.io/news/markets/usd85m-polymarket-dispute-over-strategy-s-may-bitcoin-sale-puts-uma-s-token-voting-oracle-on)
