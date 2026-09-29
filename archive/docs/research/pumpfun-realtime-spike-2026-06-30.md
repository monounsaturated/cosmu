# pump.fun Realtime-Multimodal Trading — Feasibility Spike

**Date:** 2026-06-30 · **Type:** feasibility spike (research only, NO build, NO real money, NO API keys used) · **Author:** autonomous COSMU agent

---

## ⛔ VERDICT: NO-GO (as specified) — with one ~$0 offline probe worth keeping the lane alive

> **The thesis** — a realtime multimodal model watches a pump.fun launch livestream (video + audio + chat) and snipes the launched memecoin fast on "vibe/tone" — **is structurally dominated and should not be built.**
>
> Three independent walls kill it, any one of which is sufficient:
> 1. **Speed wall.** The launch contest is a **~50 ms** bot + same-block bundle game. The AI's *only* differentiator (semantic hype reading) costs **~1–2 s** end-to-end and **video reaction maxes at ~1 FPS** on every mainstream API. The AI is ~40 Solana slots late. It cannot be a speed play.
> 2. **Exit-liquidity wall.** Livestream hype on these micro-caps **is the manipulation**, not a leading signal. Deployer↔sniper coordination is systematic (**87% sniper success**, retail engineered as the exit). Reacting to broadcast hype = being the exit liquidity by design. ~**60% of pump.fun wallets lose money**; only **0.76%** ever cleared +$1k.
> 3. **Data wall.** There is **no official, stable API for the livestream video/audio/chat.** It's a JWT-gated, reverse-engineered LiveKit/WebRTC path that pump.fun can break at any time. The one axis the whole thesis depends on is the most fragile to obtain.
>
> **Plus:** the core claim "vibe → price (with a tradeable lead)" is **untested and has no cheap point-in-time backtest** — you cannot replay historical livestream video+ticks. You'd be building blind.
>
> **The one thing worth doing instead** (cheap, offline, no money): a **data-collection probe** that records N livestreamed launches + tick data, labels hype moments, and measures lead–lag. ~$0, kills or confirms the lane empirically. See [§8](#8-if-you-keep-the-lane-alive-the-cheapest-next-probe).

---

## 1. The thesis under test

From the operator's aggressive target (asymmetric 2–3×/day sniper in tiny markets Wall St can't touch): pump.fun streams **live video of launches**; a realtime multimodal model (OpenAI Realtime / Gemini Live / DIY) watches **video + audio + chat + crowd vibe**, infers a hype inflection **before** price moves, and trades the launched coin fast.

Two ways this could win, tested separately:
- **(A) Speed play** — react to a hype cue faster than the market. *Tested in §3 + §4.*
- **(B) Selection/judgment play** — slower, but a better read on which hyped coin actually runs. *Tested in §5.*

Both fail as specified. (B) leaves a narrow, unvalidated remnant (§8).

---

## 2. pump.fun mechanics + data access

### Mechanics (high confidence)
- **Token creation: free** (0 SOL / 0 USDC); fixed supply, **800M** sold on a constant-product **bonding curve**, ~200M reserved for the post-graduation pool. ([fees](https://pump.fun/docs/fees), [explainer](https://blockchain.oodles.io/pump-fun/))
- **Graduation** at **~$69k market cap** → migrates to **PumpSwap** (pump.fun's own DEX since Mar 2025; the old 6-SOL Raydium migration fee is gone, now **0.015 SOL**). ([PumpSwap](https://www.blocmates.com/news-posts/pump-fun-introduces-pumpswap-a-new-dex-for-graduated-token-listings), [KuCoin](https://www.kucoin.com/news/articles/pump-fun-debuts-pumpswap-dex-with-0-25-fee-structure-and-zero-sol-migration-fee-to-reclaim-solana-s-memecoin-market))
- **Fees (official, current):** bonding-curve trades **1.25%** (0.95% protocol + 0.30% creator); PumpSwap post-graduation tiered **1.25% → 0.30%** by market cap (the "Project Ascend" dynamic model). ([fees](https://pump.fun/docs/fees), [fee model](https://blockworks.com/news/pumpdotfun-fee-model))

### Livestreams (high confidence on timeline)
- Launched 2024 → drove the boom (pump.fun launch-share peaked ~**75.5%**) → **suspended Nov 2024** after extreme abuse → **reinstated Apr 2025** with a moderation policy + AI flagging. ([wiki](https://en.wikipedia.org/wiki/Pump.fun), [reinstate](https://cryptoslate.com/pumpfun-fully-restores-streaming-feature-with-stricter-moderation-policy/))
- **June 2026: "GO" bounty marketplace** drew fresh backlash for extreme listings — the moderation problem is recurring, reputationally toxic, and a live regulatory/headline risk. ([Chaos 2.0](https://www.tradingview.com/news/newsbtc:cc6ce64ac094b:0-livestream-chaos-2-0-pump-fun-under-fire-over-new-bounty-feature/))
- **Prevalence: small minority.** With ~30k tokens/day, only a fraction stream. **No source quantifies the %** — but it is clearly a promo feature on a minority of launches, not a property of most. *(Gap.)*

### Data access — the split that matters
| Data | Availability | Notes |
|---|---|---|
| New-launch + trade firehose | ✅ **Cheap / well-served** | PumpPortal WS **free** for new-token/migration; Helius LaserStream / Shyft gRPC for ms-latency by decoding on-chain directly. ([PumpPortal](https://pumpportal.fun/data-api/real-time/), [Shyft](https://shyft.to/blog/how-to-stream-new-token-launches-on-pump-fun-in-real-time)) |
| Bonding-curve state / holders / graduation | ✅ Available | Bitquery / Moralis, or computed from on-chain accounts. ([Bitquery](https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-Marketcap-Bonding-Curve-API/)) |
| **Livestream video / audio** | ⚠️ **Fragile / reverse-engineered** | Delivery is **LiveKit (WebRTC)**. Requires a JWT-gated viewer token from pump.fun's **undocumented** frontend API + a LiveKit client. **No official API, no confirmed public HLS URL.** ([stream guide](https://blog.livereacting.com/how-to-stream-on-pump-fun/), [reversed endpoints](https://github.com/BankkRoll/pumpfun-apis)) |
| **Livestream chat** | ⚠️ **Unverified** | No documented public chat feed; only comment/voice-chat *counts* surfaced. Chat likely rides the LiveKit data channel once joined, but unconfirmed. |

**Implication:** the firehose is easy; **the multimodal substrate the thesis needs is the hardest, most breakable piece to obtain** — and it's controlled by an adversarial counterparty (pump.fun) with every incentive to gate bots.

---

## 3. Realtime multimodal models — latency & cost

| Option | Live video | Live audio | React latency | Cost (1 continuous stream) | Status |
|---|---|---|---|---|---|
| **Gemini Live API** (3.1 / 2.5 Flash native-audio) | ✅ but **≤1 FPS** (frames as images) | ✅ native | ~1–2 s to first reaction | ~tens–low-hundreds $/mo (token-billed) | GA-ish, **best fit** ([Live API](https://ai.google.dev/gemini-api/docs/live-api/capabilities)) |
| **OpenAI Realtime** (`gpt-realtime`, GA 2025-08-28) | ❌ no video; static image only | ✅ native speech-to-speech | TTFV <~1 s | **expensive** ($32/$64 per 1M audio in/out) → ~$1.5k–4.5k+/mo | GA ([model](https://developers.openai.com/api/docs/models/gpt-realtime), [pricing](https://developers.openai.com/api/docs/pricing)) |
| **Claude** | ❌ | ❌ no audio input | n/a (request/response) | n/a | Text+image only — usable as the *reasoning* step on sampled frames, **not** live ingestion ([vision](https://platform.claude.com/docs/en/build-with-claude/vision)) |
| **DIY** (Deepgram STT + frames + Flash-Lite) | sample-rate of your choice | ✅ via STT | ~1–3 s stacked | ~$350–500/mo (STT-dominated, 24/7) | controllable fallback ([Deepgram](https://deepgram.com/pricing)) |
| **Self-host Qwen2.5-Omni** | ✅ streaming | ✅ | unbenchmarked | GPU rental | open, no real-world latency data ([repo](https://github.com/qwenlm/qwen2.5-omni)) |

**Latency-budget verdict:** A true realtime API can produce a *signal* **~1–2 s** after a clear spoken hype cue — **not reliably sub-second**, and that's before order submission. **Native fast *video* reaction does not exist** in mainstream APIs (Gemini caps at ~1 FPS), so any visual-trigger snipe carries a ≥~1 s detection floor. Gemini Live is the only option that fuses live audio+frames+text in one cheap model — but it has a **2-minute session cap on audio+video** (reconnection plumbing required for continuous watching).

**This ~1–2 s floor is the whole problem for the speed play.** It is ~40 Solana slots (§4).

---

## 4. Execution path + bot landscape

### How you'd trade (high confidence)
- Wallet = a funded Solana keypair (no KYC). Simplest builder path: **PumpPortal Local API** (0.5%, you keep custody + control RPC) for curve buys → **Jupiter** for graduated tokens. ([PumpPortal API](https://github.com/thetateman/Trading-API), [fees](https://pumpportal.fun/fees/))

### All-in cost, round-trip, $50–500 (synthesized)
- Protocol ~2.5% (1.25%×2) + third-party ~1.0% + priority/Jito **0.5–2%+ at launch** + slippage.
- **Floor ~4% on a clean liquid token; 5–8%+ on a fresh launch; uncapped slippage tail (documented >50%) on the thinnest brand-new tokens.** ([slippage study](https://bitquery.io/blog/analyzing-slippage-pumpfun-trading-dynamics))
- **You need ≥5–8% gross just to break even on a fresh-launch round trip.**

### The speed wall (high confidence)
- Solana slot ~**400 ms**. Production snipers hit **~50 ms** total (co-located nodes, Yellowstone gRPC, pre-signed templates, Jito multi-relay bundles). Amateur public-RPC paths: **430–680 ms**. Major launches draw **200+ bots in the first half-second**. ([bot stack](https://dysnix.com/blog/complete-stack-competitive-solana-sniper-bots))
- The **dev's own block-0 bundle** (up to ~21–25 sub-wallets) buys *before the public sees the token*. ([bundler](https://github.com/cicere/pumpfun-bundler))
- Banana Gun's own writeup: manual/late paths face an **"insurmountable" gap** vs millisecond bots. ([Banana Gun](https://blog.bananagun.io/blog/solana-sniper-bots-how-first-block-token-sniping-actually-works))
- **A ~1–2 s AI loop is not in this contest.** Block 0/1 is owned by the dev bundle + co-located bots.

---

## 5. The edge question: does vibe lead price? (synthesis)

**Speed play (A): dead.** §3 + §4 — the AI is structurally ~40 slots late; it cannot beat bots to the launch.

**Selection/judgment play (B): no validated signal, and the structure is adversarial.**

1. **No information asymmetry.** For these micro-caps, *the people watching the stream are the entire market.* The AI sees exactly what every other viewer + every KOL-copytrade bot sees, at the same instant — minus a 1–2 s reasoning tax. "Tireless viewer" is not an edge when thousands watch live and copytrade bots mirror KOL wallets in <1 s.
2. **The hype IS the manipulation.** Deployer↔sniper coordination is systematic: **>15,000 SOL extracted across >15,000 launches, 87% sniper success rate**, retail engineered as exit liquidity. ([extraction study](https://www.bitget.com/news/detail/12560604803448)) A charismatic stream is frequently the *bait* on top of a bundled-supply setup. An AI trained to "buy when hype spikes" is an exit-liquidity machine.
3. **The thesis is untested and has no cheap backtest.** "Vibe → price with a tradeable lead" has **no PIT dataset** — you cannot replay historical livestream video+audio+chat aligned to ticks. Every other COSMU edge passes the deterministic Gate on replayable data; **this one cannot even be screened** without first *manufacturing* the dataset (§8). Building the live system before that = building blind, against COSMU's core discipline (no edge ships unproven).
4. **Brutal base rates.** ~**69% of tokens die launch-day**, ~**5%** survive 90 days, ~**1%** graduate, **60% of wallets lose money**, only **0.76%** ever cleared +$1k. ([lifespan](https://chainplay.gg/blog/lifespan-pump-fun-memecoins-analysis/), [PnL](https://crypto.news/only-0-76-of-pump-fun-wallets-made-1000-or-more-cn-research/)) The 2026 rise to ~73% profitable is **survivorship** (unprofitable traders left), not the market getting friendlier. ([comeback](https://beincrypto.com/pump-fun-traders-profit-comeback-meme-coin-season/))

**Honest conclusion:** there is **no demonstrated edge** for a non-HFT solo here, and a strong structural argument that the realtime-vibe angle is *negative* EV (you systematically arrive after the informed flow, into engineered sell pressure, paying 5–8%+ round-trip). The only non-falsified remnant is a **slower (minutes-scale) hype-momentum selection** where the 1–2 s latency stops mattering — but that remnant is **unvalidated** and must be measured offline before any spend (§8).

---

## 6. Honest risks

| Risk | Severity | Note |
|---|---|---|
| **You are exit liquidity** | 🔴 Critical | Bots + dev bundle own block 0; you buy into insider sell pressure. The default outcome, not a tail. |
| **Rugs / death** | 🔴 Critical | ~69% die day-1; 92% of tokens with ≥30 swaps show ≥1 dump event. ([study](https://arxiv.org/html/2602.14860v1)) |
| **Slippage tail** | 🔴 Critical | Small fresh-token buys have an *uncapped* slippage tail (>50% documented). |
| **Speed loss to bots** | 🔴 Critical | ~50 ms bots vs ~1–2 s AI loop. Lost contest. |
| **Data fragility** | 🟠 High | Livestream A/V/chat = reverse-engineered, JWT-gated, breakable anytime. |
| **No backtest** | 🟠 High | Thesis cannot pass the Gate without a manufactured dataset; can't be screened like every other COSMU edge. |
| **Reputational / legal** | 🟠 High | pump.fun moderation scandals (suicide/violence bounties), active lawsuit risk; building a bot to trade *on* that content is a brand/legal hazard. |
| **Cost floor** | 🟡 Medium | 5–8%+ round-trip + LLM run-cost ($350–4.5k/mo per continuous stream) before any edge. |
| **MEV / sandwich** | 🟡 Medium | On thin pools, your own order is sandwich-able. |

---

## 7. What a build would take (if pursued anyway)

So the scope is on record — **not a recommendation:**

1. **Livestream ingestion** (hardest): authenticate to pump.fun (JWT), call the undocumented endpoint for a LiveKit viewer token, join the WebRTC room, pull video+audio+data-channel chat — per stream, with reconnect logic, expecting pump.fun to break it. *~1–2 wks, ongoing maintenance, fragile.*
2. **Realtime model loop**: Gemini Live (audio + ≤1 FPS frames + chat) with 2-min session re-establishment; prompt → structured "hype score + trade intent." *~1 wk.*
3. **Execution adapter**: Solana wallet + PumpPortal Local + Jupiter, priority-fee/Jito logic, hard slippage caps, max-loss per trade. *~1 wk (COSMU has venue-adapter patterns).*
4. **Risk harness**: per-token max loss, daily stop, rug heuristics (bundle/holder concentration filters), kill-switch. *~3–5 d.*
5. **The actual blocker — validation**: there is no way to forward-test this in COSMU's paper lane meaningfully without the live data pipeline already built, and no historical backtest at all. You'd be live-money testing an unproven thesis. **This inverts COSMU's "prove before fund" rule.**

**Total ~4–6 weeks of fragile build for a thesis with no prior evidence and a strong negative-EV prior.** Maintenance is perpetual (pump.fun will fight scrapers).

---

## 8. If you keep the lane alive: the cheapest next probe

Respecting "don't kill ideas, store them" + the help-operator-gather-data role — the **only** rational next step is a **$0, offline, no-money data-collection probe** that decides the lane empirically:

1. **Record** ~20–50 livestreamed launches: capture the LiveKit A/V (manual/headless), the on-chain trade stream (PumpPortal free), and bonding-curve price ticks, time-aligned.
2. **Label** hype moments (manually or with one cheap Gemini pass over the recording — *offline*, no realtime cost).
3. **Measure lead–lag**: does a labeled hype spike *precede* a price move by enough to trade after a 1–2 s tax and 5–8% cost? Or does price already reflect it (co-incident / lagging)?
4. **Gate decision**: if no clean, repeatable, cost-surviving lead exists across the sample → **kill the lane for good** with data. If a lead exists → only *then* consider the build in §7.

This costs ~a few dollars of Gemini + a few days, produces the PIT dataset that doesn't otherwise exist, and converts a hunch into a Gate-able answer. **Do this before any code or any money.**

> Strategic note: this mirrors COSMU's settled findings — Polymarket markets are mostly co-incident/underreact (use as nowcast, not arb), and latency lanes belong to bots. The pump.fun livestream is the same shape: a broadcast signal everyone sees at once, in bot turf. The prior is strongly that the "vibe lead" is co-incident, i.e. untradeable after costs. The probe's job is to falsify that prior cheaply.

---

## Sources (primary)

- pump.fun fees: https://pump.fun/docs/fees · livestream moderation: https://pump.fun/docs/livestream-moderation-policy
- PumpPortal data + trade API/fees: https://pumpportal.fun/data-api/real-time/ · https://pumpportal.fun/fees/ · https://github.com/thetateman/Trading-API
- Reversed frontend/livestream endpoints (unofficial): https://github.com/BankkRoll/pumpfun-apis
- Bonding curve / data: https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-Marketcap-Bonding-Curve-API/ · https://shyft.to/blog/how-to-stream-new-token-launches-on-pump-fun-in-real-time
- Slippage study: https://bitquery.io/blog/analyzing-slippage-pumpfun-trading-dynamics
- Bot stack / latency: https://dysnix.com/blog/complete-stack-competitive-solana-sniper-bots · https://blog.bananagun.io/blog/solana-sniper-bots-how-first-block-token-sniping-actually-works
- Bundling: https://github.com/cicere/pumpfun-bundler
- Survival / lifespan: https://chainplay.gg/blog/lifespan-pump-fun-memecoins-analysis/ · academic: https://arxiv.org/html/2602.14860v1
- Retail PnL: https://crypto.news/only-0-76-of-pump-fun-wallets-made-1000-or-more-cn-research/ · https://www.coingecko.com/research/publications/pump-fun-traders-are-making-a-comeback
- Insider/sniper extraction: https://www.bitget.com/news/detail/12560604803448
- Gemini Live API: https://ai.google.dev/gemini-api/docs/live-api/capabilities · OpenAI Realtime: https://developers.openai.com/api/docs/models/gpt-realtime · Claude vision: https://platform.claude.com/docs/en/build-with-claude/vision
- Deepgram pricing: https://deepgram.com/pricing · Qwen2.5-Omni: https://github.com/qwenlm/qwen2.5-omni

*Confidence: HIGH on mechanics, fees, bot-speed, survival stats, model capabilities/latency. MEDIUM on exact $ (LLM run-cost, PumpSwap tier splits — verify live). GAPS: exact % of tokens livestreamed; confirmed viewer-token/chat endpoints; the lead–lag question itself (the probe in §8 exists to answer it).*
