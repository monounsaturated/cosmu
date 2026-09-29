# Realtime-Audio → Prediction-Market Trading — Spike (2026-06-30)

**Idea under test:** trade prediction/betting markets off a LIVE AUDIO feed. A realtime model does DUMB fast detection on a broadcast (count word occurrences in a speech, detect tone/events in sports commentary) → pipes a signal to our order-formatting LLM → executes on Polymarket/Kalshi. The claimed engineering edge is minimizing OUR pipeline latency (not beating the broadcast feed).

**Scope of this doc:** GO/NO-GO + minimal architecture + risks. This is a SPIKE — research and store, **build nothing, no keys, no real money.** Source: web research (4 parallel passes, 2026-06-30) + repo inventory. Confidence flags inline; most per-second latency figures across the industry are vendor-CLAIMED, not controlled benchmarks — load-bearing numbers tagged.

---

## TL;DR — Verdict

| Lane | Verdict | One-line reason |
|---|---|---|
| **Sports (in-venue events) off a public feed** | **HARD NO-GO** | A $1B+ official-data moat puts the odds-setters ~1–4 s behind the event; you're ~15–45 s behind via any public feed. You are the prey. |
| **Pure "latency-king HFT" framing on any venue** | **NO-GO** | Every venue that has the right markets has a *deliberate anti-latency delay* (Polymarket 250 ms taker, Betfair 1–12 s, Kalshi filing one now). A millisecond edge is engineered out. |
| **Political-speech word-count markets ("will X say word Y N times")** | **CONDITIONAL-GO — prototype only (paper)** | No in-venue data moat: everyone hears the same public feed. The race is against *slow humans manually counting*, not HFT. Near-zero cost to run (local models, maker fees). But episodic + a real regulatory kill-switch risk. |

**The honest move:** Do **not** build a sports-audio latency bot. **Do** keep a $0, local-only word-counting prototype on the shelf, armed against the *next scheduled speech* (SOTU, FOMC presser, major debate) as a paper-only probe — **conditional on the Kalshi CFTC delay filing not landing.** This is a low-frequency, event-driven, asymmetric-sniper lane, not a continuous strategy.

---

## 1. The latency reality — where the edge dies, and where it survives

The whole thesis rests on one question: **can a solo dev consuming a public feed ever be fast enough?** The answer splits cleanly by market type.

### 1a. Sports: structurally unwinnable off a public feed

The latency ladder from the real-world event (magnitudes independently corroborated):

| Vantage point | Lag vs. event | Tag |
|---|---|---|
| In-stadium / present | ~0 s | — |
| **Official data feed (Sportradar / Genius)** | **~1–3 s** (sometimes sub-second) | CLAIMED |
| Broadcast / cable TV | ~5–10 s (OTA measured 16–21 s) | MIXED |
| Standard streaming (HLS/DASH) | **~15–45 s** | CONFIRMED |
| Worst-case streaming | 60–78 s (Super Bowl LIX, MEASURED by Phenix) | MEASURED |

- **Genius Sports** captures play-by-play on-venue and delivers "in under a second," exclusive for the Premier League/EFL through 2029; its data runs **~3–4 s ahead of video** (vendor-CLAIMED but independently plausible).
- **Sportradar** is the NBA's exclusive real-time distributor — an **8-year, $1B+** cash+equity deal (the league took ~3% equity) — pushing micro-betting data "in milliseconds."
- **Courtsiding** proves the gap is real and monetizable (Dobson, 2014 Australian Open, exploiting TV delays "up to 10 s"; top courtsiders reportedly made six figures). Books defend with **deliberate in-play bet-delays** (Betfair: 1 s racing → up to 8 s football).

Event → official odds ≈ **1–4 s**; event → your public-feed pipeline ≈ **15–45 s + ASR**. You'd trade **10–40+ s behind the price** against a $1B sub-second feed, into markets that auto-suspend. **Dead.** (Polymarket live-sports latency-arb *is* real and practiced — Predik bot "$271k/30 days," an arXiv Polymarket-NBA-arb paper — but the winners run the *official* feed, not a broadcast.)

### 1b. Speeches: no in-venue moat — a fair fight

For "will X say word Y" markets the spoken-word feed **is** the common feed. There is no Sportradar for the words being said — the market-makers process the same public broadcast you do. Polymarket's own resolution rule: *"Only remarks which are broadcast or streamed live will count."*

The concrete, capturable edge: **captions/StreamText lag raw audio by ~3–5 s** (the "4-second" benchmark). Running your **own ASR on the raw audio** beats anyone trading off captions by several seconds. That's a real, defensible few-seconds head-start that a solo dev can hold — against slow human counterparties, not HFT.

These markets are large and live-priced: Trump 2026 SOTU mention markets saw **$10.6M purchased by 10am** on speech day ($8.6M Kalshi); Kalshi's `kxtrumpmention` listed ~45 words/phrases.

**The one moat that does exist for speeches is the document lockup** (pre-released FOMC *statement text*, BLS/CPI press lockups — the 2013 FOMC "7 ms" leak). That moat only touches *pre-written releases*, **not** live spoken-word counting. So: trade the *live word count*, never the *statement release*.

---

## 2. The venue trap — deliberate anti-latency delays are everywhere

This is the finding that reframes the whole idea. **Every venue with the right markets has engineered out the millisecond edge:**

| Venue | Has the markets? | Anti-latency delay | Maker / taker fee |
|---|---|---|---|
| **Polymarket** | YES — strongest (`/mentions` + live sports) | **250 ms taker matching delay** (+ per-market sports delay); order pending & uncancellable during it | **Maker 0%**; taker Mentions ~1.56%, Sports 0.75% |
| **Kalshi** | YES — uniquely lists "what will Trump say" word markets | **None today — but CFTC filing pending (Dec 2025)** for an anti-"courtsiding" execution delay | Taker max 1.75¢/contract @ 50¢; maker max 0.175¢ |
| **Betfair / Smarkets / Matchbook** | YES (deep in-play) | **1 s → ~8–12 s bet-delay** on matching (the sector's anti-courtsiding weapon); exposed as `betDelay` | ~2–5% commission (+ Betfair Premium Charge on winners) |
| **Sportsbooks** (DK/FD/Pinnacle) | Markets exist, throttled | **3–8 s spool**; Pinnacle ~6 s; **no retail placement API**; winners limited in days | 6–13% hold (2–4% Pinnacle) |

Two load-bearing facts:
1. **The clean "faster audio → take the price" HFT play is structurally dead on every venue.** On exchanges the delay is on *bet matching*; the only escape is *passive maker* orders (post liquidity, don't take it) — a different game.
2. **Polymarket execution is fast where it counts but capped:** off-chain order-book round-trip **p50 ~23 ms / p99 ~67 ms** (MEASURED, Dublin VPS; infra is AWS eu-west-2 London), but the **250 ms taker delay sits on top**, so 20 ms vs 80 ms doesn't matter. On-chain Polygon settlement is the slow tail (~2 s block, ~5 s match→settlement gap) with measured "ghost-fill" reverts (arXiv: ~1.95M reverted `matchOrders`, $1.78B failed-to-settle, worst day 8.5%). You act on the off-chain fill.

**Implication for the architecture:** the edge is **NOT** intra-venue speed. It is **(a)** being a few seconds ahead of slow human counterparties *within* the delay window via raw-audio ASR, and **(b)** posting **maker** orders (0% on Polymarket) so you're not paying taker fees into a thin, decaying margin.

---

## 3. The detection stack — local, cheap, the right tool

For "dumb fast detection" you do **not** want a conversational LLM (OpenAI Realtime is overkill: no reliable word-level timestamps in realtime, ~450–900 ms TTF-voice, ~$0.019/min in). The cheapest, lowest-latency stack is **layered and local**, ~$0 marginal cost on the M2:

**(a) Word-counting on a speech — primary pick: `sherpa-onnx` open-vocab KWS**
- Define any custom word as **text, no training, no audio samples**; ~30 ms-class inference on 80 ms frames; **Apache-2.0, free**. It's a *detector*, not a counter — you count by debouncing repeated triggers.
- Cloud fallback if you need the full transcript text *and* boosted words: **Deepgram Nova-3 + Keyterm Prompting** ($0.0048/min + $0.0013/min keyterm; purpose-built for "boost these words"), or **Soniox** ($0.12/hr, cheapest true streaming with boosting).
- Avoid: Porcupine (free cap = 3 users, then $6k+/yr), openWakeWord pretrained models (non-commercial license).

**(b) Event / tone detection on sports audio — primary pick: `YAMNet` (Cheering/Crowd/Applause) + RMS energy-spike, gated by `Silero VAD`**
- All local, trivially realtime on M2 CPU, $0. For speaker excitement: **audeering dimensional wav2vec2** (arousal axis). Avoid **Hume AI** — its Expression Measurement API is sunsetting (~2026-06-14).
- (This branch only matters if the sports lane were viable — per §1a it is NOT off a public feed. Keep for completeness / a future official-feed world.)

**Uncertainty to burn down before any build:** no published Apple-Silicon latency for these models — vendor numbers are RPi/GPU. **Benchmark on the actual M2** before committing. Most sub-300 ms STT latencies are vendor-claimed *interim*; the few independent finals (Deepgram 337–509 ms) run higher.

---

## 4. Minimal architecture + latency budget

The pipeline, for the **one viable lane (speech word-count)**:

```
                          ── all local, on the M2 ──
 [Public-domain raw audio]      [DUMB fast detect]        [Format]        [Execute]
  gov feed / radio / YT  ─────► sherpa-onnx KWS  ─────►  count + ──────► order-fmt ──► Polymarket /
  (raw audio, NOT video,        (target word list)        debounce       LLM (cheap)   Kalshi MAKER
   NOT captions)                 + Silero VAD gate         + threshold    → typed       order (0% fee)
        │                              │                       │           order        │
   feed lag (shared                detect ~30–80 ms        count logic                 250 ms taker
   by everyone): the              + ASR step               ~ms                          delay (floor)
   ~3–5 s saved by raw                                                                  → so POST maker
   audio vs captions IS                                                                   to skip it
   the edge
```

**Latency budget (speech lane):**

| Stage | Budget | Notes |
|---|---|---|
| Real event → raw public feed | 2–45 s, **shared by all** | Not our edge; pick the lowest-latency *raw audio* tier available (WebRTC/ultra-low YT > HLS; radio > TV) |
| **Raw audio vs captions head-start** | **+3–5 s in our favor** | The actual edge. Anyone trading off captions/StreamText is behind us |
| KWS detect + VAD | ~30–80 ms | Local, sherpa-onnx |
| Count/debounce + threshold logic | ~ms | Trivial |
| Order-format LLM | ~100s of ms | Cheap model; or skip LLM entirely for word-count (deterministic) |
| Submit → on book | ~25 ms off-chain (Polymarket) | But 250 ms taker delay → **post maker** to avoid |
| **Our controllable budget** | **< ~1 s** end-to-end | Comfortably inside the 3–5 s caption head-start |

**Key design calls:**
- **Raw audio, never video/captions.** The 3–5 s caption lag is the moat.
- **Maker orders, not taker.** Sidesteps the 250 ms taker delay AND the fee (0% maker on Polymarket). Pre-position resting orders on likely word-count thresholds and let the speech come to them.
- **No LLM in the hot path for pure word-counting** — counting is deterministic. The order-format LLM is for the messier "tone/context" variants, which are lower-confidence; keep the LLM out of the numeric/count path (matches the repo's "LLM out of numeric price-reasoning" rule).
- **Reuses existing repo infra:** the `realtime-data-lane` epic (`docs/epics/realtime-data-lane.md`), the realtime worker/API, and the Polymarket live venue already exist. This lane is a new *detector input*, not new plumbing. Note: this is distinct from the existing **social/authority "voice lane"** (`cosmu/mind/authority.py` et al.) which scores *who said it* from text timelines — that lane is wired-but-data-inert; this spike is about *acoustic* realtime detection, a different input.

---

## 5. Risks (ranked)

1. **Kalshi's pending CFTC execution-delay filing (Dec 2025) — existential to the Kalshi leg.** Aimed squarely at "courtsiding" (the exact hear-it-first edge). If it ships, the Kalshi word-count edge dies the same way the exchanges' bet-delay killed it. **Watch this filing; do not build against Kalshi until it resolves.** Polymarket's mentions markets remain (250 ms delay, beatable via maker).
2. **It's a tooling race with thin, decaying margins.** Other sophisticated players run the same raw-audio + ASR pipeline. The edge is *relative pipeline tightness*, not a structural moat. First movers and the slowest counterparties (manual humans) are the alpha source — both erode.
3. **Episodic, not continuous.** SOTU / FOMC pressers / major debates fire a handful of times a year. This is a low-frequency *event sniper*, incompatible with a "continuous strategy" mental model. Sizing must reflect rare, asymmetric shots.
4. **Resolution-rule risk.** Markets resolve on a *specific* video/official source with specific counting rules (what counts as "saying" a word, contractions, repeats). Misreading the resolution spec loses regardless of detection speed. Read each market's rules before arming.
5. **Liquidity / fill risk on maker orders.** Maker avoids fees + delay, but resting orders may not fill at the size/price you want during a fast-moving speech; and Polymarket on-chain "ghost-fill" reverts (8.5% worst-day) mean an off-chain fill can fail to settle.
6. **ToS, not copyright.** Extracting a *fact* ("the word was said") from a broadcast is lawful (NBA v. Motorola; Feist) — copyright is about redistribution, not private analysis. The real exposure is platform ToS on automated capture (account/IP ban, civil contract risk per hiQ v. LinkedIn). **Mitigation: prefer government/public-domain feeds** (congressional floor feed is explicitly public domain; whitehouse.gov, federalreserve.gov live) and OTA radio over logged-in platform streams. No insider-trading angle (public feed = public info).

---

## 6. Decision & next trigger

**GO/NO-GO:** **NO-GO to build now.** **CONDITIONAL-GO to prototype (paper-only, $0)** the *speech word-count* lane.

- **Build nothing today.** Cost to keep the idea alive = $0 (all local models, no keys).
- **Arming condition (paper twin only):** the next scheduled major speech (SOTU / FOMC presser / debate) **AND** the Kalshi CFTC delay filing has not landed (or use Polymarket-only with maker orders). Then run a **paper** probe: local sherpa-onnx word-counter on the raw gov feed → log a *would-have-traded* ledger vs the live market odds. Measure the realized head-start vs caption-traders and the slippage on maker fills. No real money until that paper ledger shows a real, repeatable edge.
- **Kill condition:** Kalshi delay ships AND Polymarket maker margins prove too thin in the paper ledger → graveyard the lane.

This fits the aggressive-sniper profile (rare, asymmetric, event-driven, near-zero carrying cost) without the fatal flaw the research exposed: it does **not** require beating the latency kings, because on the speech lane there are none.

---

## Appendix — Sources

**Detection models:** OpenAI Realtime pricing/latency — developers.openai.com/api/docs/pricing, latent.space/p/realtime-api · Deepgram Nova-3 keyterm — deepgram.com · Soniox / AssemblyAI / Gladia streaming docs · sherpa-onnx KWS — k2-fsa.github.io/sherpa · Porcupine — picovoice.ai · YAMNet — tfhub.dev / AudioSet · Silero VAD — github.com/snakers4/silero-vad · audeering wav2vec2 — github.com/audeering · Hume sunset — hume.ai docs.

**Feed latency / moat:** Genius "3–4 s ahead" — ably.com/case-studies/genius-sports · Super Bowl LIX MEASURED — blog.phenixrts.com/phenix-superbowl-latency-study-2025 · YouTube latency tiers — support.google.com/youtube/answer/7444635 · Betfair bet-delays — support.developer.betfair.com/hc/en-us/articles/360002825652 · NBA/Sportradar $1B — sportico.com/business/sports-betting/2021/nba-sportradar-data-equity-1234646790 · Courtsiding/Dobson — en.wikipedia.org/wiki/Courtsiding · Caption 4-s lag — alibaba.com/product-insights/ai-powered-captioning-for-live-streams.

**Venues:** Polymarket order-lifecycle / 250 ms delay — docs.polymarket.com · Polymarket on-chain reverts — arXiv (Polymarket settlement study, 2025–2026) · Kalshi `kxtrumpmention` — kalshi.com/markets/kxtrumpmention · Kalshi CFTC delay filing — gambling911.com (Dec 2025) · Pinnacle API closure (2025-07-23) — GitHub Pinnacle API docs.

**Legality:** NBA v. Motorola — bitlaw.com/source/cases/copyright/nba.html · Feist v. Rural — supreme.justia.com/cases/federal/us/499/340 · hiQ v. LinkedIn — en.wikipedia.org/wiki/HiQ_Labs_v._LinkedIn · FOMC 7 ms leak — washingtonpost.com/news/wonk/wp/2013/09/24 · Polymarket SOTU resolution rule — polymarket.com/event/what-will-trump-say-during-the-state-of-the-union-address.

*Tags: CONFIRMED = multi-source agreement · MEASURED = controlled benchmark · CLAIMED = vendor/press, uncorroborated · MIXED = sources disagree. Most per-second latency figures are CLAIMED; treat as magnitudes, not precision.*
