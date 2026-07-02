# Low-Float / New-Listing Sweep — Asymmetric Early-Entry (2026-06-30)

**Scope:** A sweep that hunts **brand-new listings** and **low-float coins** for asymmetric early
entry — the markets WS (Wall Street) structurally *can't* enter because their size moves the price, and
we can. Five questions: (1) how to **detect** new listings + low-float coins early across our usable
venues (Kraken, Binance, Solana DEXs / pump.fun) with free/keyless data where possible; (2) the
**structural edge** (giants can't deploy meaningful size; we can be first with small size) + the evidence;
(3) the **honest risks** (rug/honeypot, slippage, bot competition, exit illiquidity — can we actually
*get out*); (4) a **screening/scoring design** (asymmetric early-entry vs a trap); (5) **venue/execution +
fee/slippage reality at small size**. Then the verdict: **Quant (Gate-able) or LLM (human-armed)** — and
where each half lives in our codebase.

**DESIGN/RESEARCH ONLY. STORE, don't build. No real money, no keys, no money-path code in this PR.**
Web research verified against live pages 2026-06-30 unless flagged UNCERTAIN.

---

## TL;DR (read this first)

- **The pump is real. It is also mostly a trap.** The "new listing pops" prior is *empirically true* but
  the realized distribution is brutal: across 389 CEX listings in 2024 the median sequence was a ~54%
  listing surge then a ~52% decline, **98% of Binance-listed tokens dumped after the pump**, and **37% hit
  their all-time high on listing day and never recovered it.** 2025 is worse: of 652 new CEX listings,
  **only ~12% were ever profitable, median return −82%.** On Solana's pump.fun the base rate is
  apocalyptic: **~98.6% of ~7M launches are rug pulls / manipulative**, **~93% of Raydium pools show
  soft-rug characteristics**, and **only ~1.4% of pump.fun tokens "graduate"** to a real AMM at all. (Sources §App.)
- **So the naive "buy every new listing" rule is −EV after costs.** Do not ship it. But two *non-naive*
  framings survive, and they map cleanly onto our two strategy types:
  - **LANE A — Quant (Gate-able): the listing *population* rule.** The individual day-zero token has no
    history, so it is un-backtestable — but the **rule applied across the full historical population of
    listings** (survivorship-free, *including the dead ones*) **is** backtestable. Candidate hypotheses
    are timing/fade rules ("fade the listing pop", "first-N-minute momentum with a hard stop"), not
    "buy-and-hold the listing." This is the only half that can clear the **LOCKED Gate**
    ([gate.py](apps/engine/cosmu/research/gate.py)) — and only if we feed it a **survivorship-clean
    listing dataset with real per-venue fees and *honest first-minute slippage*.** On today's evidence the
    naive version **fails** the Gate (median −82% net); a *filtered/timed* version is a legitimate
    hypothesis to test, expected survivors few.
  - **LANE B — LLM (human-armed): per-token early-entry snipe.** For pump.fun / day-zero Solana tokens
    with literally zero price history, there is no backtest surface at all. This is a **forward-only,
    selection-driven, capped, human-armed** play that belongs in the existing **snipe lane**
    ([snipe/gate.py](apps/engine/cosmu/snipe/gate.py) ConvictionGate), **not** the Gate. This is where the
    "2–3X in a day" asymmetric sniper from the aggressive-target memory actually lives — sized for a
    fat-tail basket where ~90%+ go to zero and the surviving tail pays for all of them.
- **Our edge is NOT speed.** We will *lose* the latency race to colocated MEV/sniper bots — that is decided
  by custom RPCs and regional servers, not us. Our edge is **selection + asymmetric small sizing + the
  willingness to hold the rare winner** — exactly the [[edge_thesis]] (weak signals, small markets, many
  risky autonomous agents, social data). Reframe the bot-competition risk: we are not an HFT sniper, we are
  a *vetted-basket tail-hunter*.
- **The killer risk is EXIT, not entry.** Entry is cheap and easy. On a fresh thin book the round-trip cost
  (spread + slippage + priority/MEV) is routinely **10–30% at small size**, and on the 98.6% you cannot get
  out at any price (freeze authority / no liquidity / honeypot). **Every design below is exit-first:** if we
  can't model a realistic exit, the candidate is a trap by default.
- **Detection data path is mostly free/keyless and already partially in reach.** CEX = poll
  `exchangeInfo`/`AssetPairs` and **diff for new symbols** (keyless, fires at T+0) + Kraken's public
  **Listings Roadmap** (semi-early). Solana = **DexScreener** (no key, 300 req/min) + **GeckoTerminal "New
  Pools"** (no key, ~1s indexing) + on-chain watch of the pump.fun `create` instruction. Safety = **RugCheck
  / GoPlus / Honeypot.is** + a **buy-then-sell transaction simulation** (the honeypot test).
- **Build verdict: STORE. No new venue, no adapter, no money path in this PR.** We have **no Solana/DEX
  venue** wired today ([venue.py](apps/engine/cosmu/spine/venue.py) is CEX + equity + Polymarket only).
  Lane A needs *one dataset* (survivorship-free listings) before it can even be Gated; Lane B needs the
  Solana venue + RugCheck source + the snipe-lane consumer, all of which are real work gated behind a
  forward-paper survivor. Trigger conditions are in §7.

---

## 1. Detection — how to find new listings & low-float coins early (free/keyless first)

Two very different detection problems, because "new listing" means two different things:

### 1a. CEX listings (Binance / Kraken / Coinbase) — the announcement game

There is **no official listing-announcement API or websocket** on Binance or Kraken (confirmed in the
Binance dev community). Three detection paths, cheapest first:

| Path | How | Latency | Key? | Honest limitation |
|---|---|---|---|---|
| **Symbol-diff (keyless)** ⭐ | Poll `GET /api/v3/exchangeInfo` (Binance) / `GET /0/public/AssetPairs` (Kraken) on a short interval, diff the symbol set, fire on any *new* symbol | **T+0** (fires when the pair goes live, not before) | ❌ none | You learn at listing, not before — you're racing the same bots. No *pre*-announcement signal. |
| **Announcement scrape** | Poll the Binance/Kraken announcement pages / RSS, regex the ticker out of the title | seconds *before* T+0 sometimes (announce → trading gap is often 24–48h, sometimes minutes) | ❌ none (gray-ToS scraping) | Brittle (page format changes), and the 24–48h announce-ahead window is the *tradable* one — but you must buy the token *elsewhere* (a DEX / smaller CEX) because it isn't on the listing venue yet. |
| **Kraken Listings Roadmap** ⭐ | `kraken.com/listings` + `@krakenlistings` — Kraken *publicly pre-announces* tokens that cleared internal approval | **days ahead** (semi-PIT) | ❌ none | Roadmap inclusion ≠ guaranteed/dated listing; no deposit/trading until the official notice. Still the single best *early* CEX signal we have, because it's official and ahead. |
| 3rd-party WS alert (e.g. cryptolisting.ws, cryptocurrencyalerting) | Subscribe to a structured listing-event stream with pre-parsed tickers + µs timestamps | fastest | ✅ paid key | Costs money, not keyless, ToS unknown. Defer — only if a forward-paper Lane-A survivor needs sub-second listing detection. |

**The tradable CEX pattern** (per the "buy before listing" playbooks): when Binance/Kraken *announces*
ahead of trading, the token usually already trades on a DEX or a smaller CEX. The historical "Binance
effect" was an *anticipation* move on that other venue, not a same-venue arb. For us this is mostly a
**Lane-B** discretionary call (is this announcement credible, is the other-venue liquidity real, can we
exit) rather than a Gate rule — *unless* we assemble the survivorship-free announcement→return dataset (§7).

### 1b. Solana / pump.fun — the on-chain new-token firehose

This is a *real-time on-chain* problem, and it is where free/keyless data is strongest:

| Source | Cost / key | What it gives | Latency | Best for |
|---|---|---|---|---|
| **DexScreener API** ⭐ | **free, no key**, ~300 req/min | token profiles, latest/boosted tokens, pairs, price/liq/vol; 9 endpoints, **no history, no WS** | poll | Cheap broad "what's new + liquid right now" scan; the default free firehose |
| **GeckoTerminal API** ⭐ | **free, no key**, ~30 req/min | **"New Pools" endpoint** across 250+ networks, **~1s indexing** of pool creation, OHLCV | ~1s | Catching freshly-created pools *as they're created* — the sniper-grade discovery feed |
| **Bitquery (pump.fun API)** | **free tier** + key | GraphQL/WebSocket/gRPC/Kafka; subscribe to the pump.fun `create`/`create_v2` instruction → metadata, supply, **dev address** at mint; bonding-curve progress; migrated-to-PumpSwap | real-time stream | The most *structured* day-zero feed incl. dev wallet (rug-cluster signal). Key needed but free tier exists |
| **Birdeye** | freemium key | aggregates **50+ Solana DEXs**, real-time price/trades/holders | real-time | Holder/trade analytics once a token is found |
| **Direct RPC (Helius / own node)** | RPC cost | Watch the pump.fun program `create` instruction directly; no middleman | lowest | Only if/when latency matters — we are *not* competing on latency (see §3), so this is deferred |

**Low-float detection** is a *derived* signal, not a separate feed: from the above we compute circulating
vs total/FDV, top-holder concentration, LP size and lock status, and bonding-curve progress. "Low float"
on a CEX listing = small circulating supply / high FDV (the structural-dump setup, §2/§3); "low float" on
Solana = tiny LP + concentrated holders (the rug setup). **Same word, opposite playbooks** — keep them
separate in any spec.

---

## 2. The structural edge — and the evidence

### 2a. The mechanism (why this is genuinely *our* lane)

The edge thesis is a **capacity-constrained first-mover** argument, and it is real in mechanism:

1. **Giants can't deploy meaningful size.** A fund that needs to put $10M+ to work cannot buy a token with
   a $50k LP or a fresh CEX listing with a 5–15% wide first-minute book — their own order *is* the price
   move, and they'd never recover the impact on exit. The opportunity is **literally invisible to them** by
   mandate (liquidity minimums, listing-age minimums, market-cap floors). This is the same structural gap
   as [[edge_thesis]] (small + weak-signal markets WS can't enter).
2. **We can be first with small size.** At $100–$1,000 our order *doesn't* move a thin book materially; we
   eat the *existing* spread but don't widen it further. We can be in the first cohort of a real launch
   where the marginal large buyer literally cannot.
3. **Asymmetry.** A small early position has bounded downside (the stake) and an unbounded-ish upside (the
   2–3X-in-a-day, occasionally 10–100X, tail). A basket sized so the rare winner pays for all the zeros is a
   *positive-skew lottery* — which is exactly the aggressive-target mandate ([[aggressive_target_2026-06-30]]).

### 2b. The evidence (and what it actually says)

The evidence **confirms the pop exists** and **confirms it is mostly uncapturable by buy-and-hold** —
which is *why* the edge has to be a timing/selection rule, not a hold:

| Finding | Number | Source | Implication for us |
|---|---|---|---|
| "Binance effect" (historical) | +41% day-1, +24% day-3, +73% over 30d (26 coins, pre-2023) | CoinDesk / Ren&Heinrich | The pop was real and large *when the effect was young* — alpha decays as it's discovered |
| CEX listing sequence (2024, 389 tokens) | ~+54% pump → ~−52% dump; avg pump 87% | CryptoNinjas × Storible | The *up-move is front-loaded*; a fade/short-the-pop or tight-stop-momentum rule is the only capturable shape |
| Post-pump dump rate (Binance) | **98% dump after pump**; 37% ATH on day 1 | CryptoNinjas | Buy-and-hold is −EV; **exit timing dominates the entire edge** |
| 2025 CEX listings (652) | only **~12% profitable, median −82%** | Delphi | The naive rule has gotten *worse* — survivorship + low-float/high-FDV dilution (§3) |
| pump.fun rug rate | **~98.6%** of ~7M launches rug/manipulative | Solidus Labs 2025 | Per-token selection must clear an astronomically adverse base rate |
| Raydium soft-rug pools | **~93%** (361k pools, median rug $2.8k) | Solidus Labs | Even "graduated" tokens are mostly traps |
| pump.fun graduation rate | **~1.4%** of launches (≈0.7–1.8% range) reach a real AMM | TheBlock / Smithii | The selection funnel is ~1-in-70 *just to be tradable*, before profitability |

**Honest read:** the evidence is **not** "this works, go." It is "the *raw phenomenon* is real and huge,
but the *naive realization* is a wealth-transfer to insiders and bots." That cuts directly to the design:
**the entire edge is in the selection filter and the exit rule**, not in the existence of the pop.

---

## 3. Honest risks (exit-first)

| Risk | Reality at small size | Mitigation in the design |
|---|---|---|
| **Rug pull / soft-rug** | ~98.6% pump.fun, ~93% Raydium pools. Dev pulls LP, mints supply, or abandons. | Hard pre-trade gate: **mint authority revoked + freeze authority revoked + LP burned/locked + dev-wallet not a serial rugger** (RugCheck/Bitquery dev-address). No pass → no trade. |
| **Honeypot (can buy, can't sell)** | `buyable:true, sellable:false` — the purest exit trap. | **Transaction simulation**: simulate a buy *then a sell* before committing real funds; require `sellable:true` with a *small, round-trip* loss. This is non-negotiable and is the literal exit test. |
| **Slippage / thin book** | First-minute CEX books are 5–15% wide; new Solana pools need **5–15% slippage tolerance** just to fill. Round-trip 10–30%. | Model slippage as a *function of LP depth and our size*, not a constant. Reject if our intended size > a small fraction of LP. Size is the lever: stay small enough that *we* aren't the impact. |
| **Bot competition / MEV** | Colocated snipers + sandwich bots dominate discovery, entry, and front-run our orders. We **lose the speed race**. | **Don't compete on speed.** Enter *after* the first-block chaos with a selection edge, use slippage caps + (where available) private/MEV-protected submission, accept we get the 2nd-tier fills. Our edge is the *basket + hold-the-winner*, not the first fill. |
| **Exit illiquidity — can we GET OUT?** ⚠️ | The dominant risk. On the 98.6% there is no bid. Even on survivors, exiting size into a thinning book reverses the pop. | **Exit-first sizing**: position ≤ what the *current* book can absorb at an acceptable slippage; pre-define the exit (time-stop and/or trailing) at entry; treat "no modelable exit" as an automatic reject. Paper-forward must measure *realized exit slippage*, not assume mid. |
| **Low-float / high-FDV dilution** | CEX listings: tiny circulating float pumps, then scheduled unlocks (~27%/yr of float on a 4yr linear) crush price; ~$155B unlocking 2024–30. | This is a *medium-horizon short/avoid* signal, not an early-long. Keep it as a separate disconfirmer: a high-FDV/low-float profile *down-weights* an early long and could seed a Lane-A fade hypothesis. |
| **Survivorship bias in OUR research** | The single most dangerous trap: if we backtest only tokens that *survived*, every rule looks like a winner. | Lane A is **invalid without a survivorship-free listing dataset that includes the dead/delisted/rugged**. This is stated as a hard precondition, not an optimization. The Gate's PBO/holdout don't save you from a biased *input*. |
| **Regulatory / venue** | Solana DEX / pump.fun is non-KYC on-chain; per house rule venues are usable and we never flag jurisdiction ([[venues_all_usable_2026-06-18]]). | N/A as a blocker; noted only that execution is self-custodial (wallet key mgmt is an operator/live concern, out of scope here). |

---

## 4. Screening / scoring design — asymmetric early-entry vs a trap

The scorer is a **funnel of hard gates then a soft score**, exit-first. Thresholds live in code (a
`lowfloat_screen.py` config), **not** in this prose — per house style, no magic numbers in docs.

**Stage 0 — Hard safety gates (binary; any fail ⇒ reject, no score):**
- Mint authority revoked.
- Freeze authority revoked (else honeypot-capable).
- LP burned or time-locked (verifiable LP-token burn address / lock).
- **Buy-then-sell transaction simulation passes** (`sellable:true`, round-trip loss within a small bound).
- Dev wallet not a known serial rugger (Bitquery dev-address / RugCheck history).
- LP depth ≥ a floor *relative to our intended size* (we must be small vs the pool).

**Stage 1 — Exit-feasibility gate (the killer test):**
- Modelable exit: estimated round-trip cost (spread + slippage-at-our-size + priority/MEV) below a ceiling.
- A pre-defined exit rule exists (time-stop and/or trailing) — if none is definable, reject.

**Stage 2 — Soft asymmetry score (rank survivors of 0+1):**
- **Liquidity trajectory** (LP growing, real two-sided volume vs wash) — up-weight.
- **Holder distribution** (dispersing, not 3 wallets holding 90%) — up-weight; high concentration down-weights.
- **Social/authority signal** (genuine attention vs bot echo) — ties into [[authority_feature_design_2026-06-29]];
  *down-weight* obvious manufactured hype.
- **Float / FDV profile**: for CEX, low-float/high-FDV *down-weights* an early long (unlock overhang, §3).
- **Momentum/freshness window**: capturable shape is *first-N-minute* with a hard stop, or *fade the pop* —
  never naive hold.

**Output:** a ranked, *capped*, exit-feasible candidate list. In Lane B this becomes a `ConvictionProposal`;
in Lane A this becomes a per-listing entry/exit signal evaluated across the historical population.

**Trap signature (the inverse) — any of:** authority not revoked, LP not locked, sell-sim fails, holders
ultra-concentrated, LP too thin for our size, no definable exit, low-float/high-FDV with imminent unlock,
social signal is pure bot echo. The whole point is that **most candidates are traps** — the scorer's job is
to *reject aggressively* and let almost everything through to the bin.

---

## 5. Venue / execution + fee & slippage reality at small size

| Venue | Trade fee | Real cost at small size | Notes |
|---|---|---|---|
| **Binance spot** | ~10 bps taker | **fee is trivial; the *first-minute spread* is the cost** (5–15%) | Deep later, but day-zero book is thin. Not US-legal live ([[venue.py]]); data venue for us. |
| **Kraken spot** | ~25–40 bps retail | same — spread dominates fee at T+0 | US/EU-legal, has the public Listings Roadmap (best early CEX signal). |
| **Solana DEX (Raydium/PumpSwap via Jupiter)** | exchange fee ~0; **pump.fun ~1% trade fee** | **priority fees (spike in congestion) + 5–15% slippage + MEV sandwich** ⇒ round-trip **10–30%** | This is the real arena for day-zero. No CEX fee, but the *implicit* cost dwarfs any CEX. |

**The small-size duality:** small size is *both the edge and the tax*. It is the **edge** because we don't
move the book further (a giant can't say that). It is the **tax** because we *still eat the existing
spread/slippage* — being small doesn't make a 12% spread cheaper, it just stops us from making it 20%. So
the cost model must be **per-fill realistic** (spread + slippage-at-depth + priority/MEV + the pump.fun 1%),
not the flat venue taker bps used elsewhere. Our existing per-venue fee plumbing
([venue.py `cost_inputs`](apps/engine/cosmu/spine/venue.py), [asset_fees.py](apps/engine/cosmu/spine/asset_fees.py))
is the right home, but **needs a thin-book slippage model added** before any Lane-A backtest is honest.
This matches our standing rule that **backtest fees = today's schedule on every bar**
([[fees_always_today_2026-06-18]]) — extended here to *slippage = realistic-at-small-size on every fill*.

---

## 6. Verdict — Quant (Gate-able) or LLM (human-armed)?

**Both, split cleanly — and that split is the whole insight.**

### Lane A — Quant, routes through the LOCKED Gate (IF data exists)
- **What's Gate-able:** the **listing-*population* rule**, not the individual token. A mechanical
  entry/exit rule ("fade the listing pop", "first-N-min momentum + hard stop", "avoid high-FDV/low-float")
  evaluated across the *complete historical population of listings including the dead ones*.
- **How it ties to the Gate** ([gate.py](apps/engine/cosmu/research/gate.py),
  [cohort.py](apps/engine/cosmu/master/cohort.py), [scorer.py](apps/engine/cosmu/master/scorer.py),
  [fdr.py](apps/engine/cosmu/master/fdr.py), [holdout.py](apps/engine/cosmu/master/holdout.py)): it must
  clear **every** floor — ≥ enough filled trades, deflated-Sharpe significance, CSCV-PBO below the overfit
  cap, ≥ N positive regimes, drawdown cap, **beat buy-and-hold**, within a pre-announced trial budget — all
  **net of realistic first-minute slippage**, not just exchange fees.
- **Honest expectation:** on current evidence (median −82%, 98% dump) the **naive** version *fails* the
  Gate — which is the Gate working. A *filtered/timed* version is a legitimate hypothesis; survivors, if
  any, will be few. As a `StrategySpec` this is `kind="quant"`
  ([spec.py](apps/engine/cosmu/strategy/spec.py)).
- **Hard precondition:** a **survivorship-free listing dataset** (every listing incl. delisted/rugged, with
  T+0 timestamps and thin-book quotes). **Without it, Lane A is uncomputable** — and a biased input defeats
  PBO/holdout. This is the one purchase/build that unlocks the lane (§7).

### Lane B — LLM, human-armed, lives in the snipe lane (NOT the Gate)
- **Why it can't be the Gate:** a day-zero pump.fun token has **zero price history** — there is no
  parameter surface to search, no OOS to hold out, no 30 trades to require. The Gate is categorically the
  wrong instrument.
- **Where it lives:** the existing **snipe lane** — an LLM agent
  ([snipe/agent.py](apps/engine/cosmu/snipe/agent.py)) scores each candidate via §4, emits a typed
  `ConvictionProposal` ([snipe/proposal.py](apps/engine/cosmu/snipe/proposal.py)), and the
  **ConvictionGate** ([snipe/gate.py](apps/engine/cosmu/snipe/gate.py)) enforces **hard money caps**
  (per-bet max, per-day max, min edge, min confidence) before anything is **human-armed**. As a
  `StrategySpec` axis this is `kind="llm"`; as a money path it is *proposal-only + human click*, never
  auto-funded. Tie-in: Gate B / agentic-lane design ([docs/epics/agentic-lane.md](docs/epics/agentic-lane.md),
  [[agentic_lane_design]]).
- **This is the "2–3X in a day" sniper** from [[aggressive_target_2026-06-30]] — but encoded honestly as a
  **capped positive-skew basket** (most go to zero, the tail pays), with the §3 exit-first guards as the
  agent's non-negotiable pre-checks. It is a *selection* engine, not a *speed* engine.

| | Lane A (Quant) | Lane B (LLM) |
|---|---|---|
| Object | The listing *population* rule | The individual day-zero token |
| Backtestable? | ✅ (needs survivorship-free data) | ❌ (no history exists) |
| Gate | LOCKED Gate (deterministic) | ConvictionGate caps + human arm |
| Money path | Gate survivor → paper → live (interlocks) | Proposal-only → human click, hard caps |
| Spec `kind` | `quant` | `llm` |
| Expected survivors | Few (naive fails) | A capped fat-tail basket |
| Primary risk | Survivorship bias in the input | Rug/honeypot/exit on each bet |

---

## 7. Build path — STORE now; trigger conditions to act later

**No code, no new venue, no money path in this PR.** What it would take, gated:

1. **Lane A unlock — the dataset (do this first if anything):** assemble or buy a **survivorship-free
   listing return dataset** (all CEX listings incl. delisted, T+0 quotes, thin-book bid/ask). Until this
   exists, Lane A is uncomputable. *Trigger:* operator wants to test the population fade/momentum rule.
   *Then:* add a thin-book slippage model to [asset_fees.py](apps/engine/cosmu/spine/asset_fees.py) and run
   the rule through the Gate via the `create-strategy` / `run-gate` skills. Expect few/no survivors —
   report honestly either way ([[feedback_surface_all_compute]]).
2. **Lane B unlock — the Solana venue + safety source:** we have **no DEX venue** today. Wiring it = the
   `add-venue` skill (Solana/Jupiter/pump.fun, real per-fill cost incl. ~1% + priority/MEV) + the
   `add-data-source` / `profile-source` skills for the **DexScreener + GeckoTerminal "New Pools" + RugCheck**
   feeds (free/keyless first). *Trigger:* operator wants a live forward-paper snipe basket. *Then:* the
   §4 scorer feeds the existing snipe-lane ConvictionGate; **human arms every bet**, hard caps on.
3. **Honest gate before either:** this whole lane only earns real money if a **forward-paper basket beats
   its costs incl. realized exit slippage**. Paper-forward (= our forward test, [[project_lifecycle_model]])
   must measure *realized exit*, not assume mid — the §3 exit risk is the make-or-break and must be proven
   on paper before a cent of real money.

**Spend now: $0.** All detection feeds above are free/keyless. The only money items (survivorship-free
listing data; a paid sub-second listing-alert WS) are deferred behind a forward-paper survivor.

---

## Appendix — Sources (verified 2026-06-30)

**Detection / data APIs (free-first):**
- DexScreener API ref — [docs.dexscreener.com/api/reference](https://docs.dexscreener.com/api/reference) ·
  free-DEX-API comparison — [coinpaprika](https://coinpaprika.com/education/best-free-dex-api-2025-dexpaprika-vs-dextools-vs-geckoterminal-vs-dexscreener-vs-birdeye/)
- GeckoTerminal DEX API / New Pools — [geckoterminal.com/dex-api](https://www.geckoterminal.com/dex-api) ·
  [api.geckoterminal.com/docs](https://api.geckoterminal.com/docs/index.html)
- Bitquery pump.fun API (create instruction, dev address) — [docs.bitquery.io · Pump-Fun-API](https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-API/) ·
  [bitquery.io/products/pumpfun-api](https://bitquery.io/products/pumpfun-api)
- Free multi-source memecoin REST aggregator — [github.com/gv211432/memecoin-data](https://github.com/gv211432/memecoin-data)
- Binance no-official-listing-API — [dev.binance.vision · coin-listing-announcement](https://dev.binance.vision/t/coin-listing-announcement-information/15081) ·
  symbol-diff bot example — [github.com/eyupbarlas/New-Coin-Listing-Detection-Bot](https://github.com/eyupbarlas/New-Coin-Listing-Detection-Bot)
- Kraken Listings Roadmap — [kraken.com/listings](https://www.kraken.com/listings) ·
  Kraken API announcements — [announcements.kraken.tech](https://announcements.kraken.tech/)
- 3rd-party listing WS alerts (paid) — [cryptolisting.ws/binance-listing-alert](https://cryptolisting.ws/binance-listing-alert/) ·
  [cryptocurrencyalerting.com/binance-new-listings](https://cryptocurrencyalerting.com/binance-new-listings.html)

**Structural edge & evidence:**
- "Binance effect" +41% — [CoinDesk 2023](https://www.coindesk.com/markets/2023/01/06/binance-effect-means-41-price-spike-for-newly-listed-tokens)
- CEX listing pump-then-dump (389 tokens, 98% dump) — [CryptoNinjas/Storible](https://www.cryptoninjas.net/exchange/study-cex-listing-effects/) ·
  [BitPinas](https://bitpinas.com/cryptocurrency/binance-token-listing-dump/) · effect-reversal — [OurCryptoTalk](https://web.ourcryptotalk.com/blog/binance-effect-reversal-token-listing-performance)
- 2025 listings −82% median, 12% profitable — [CryptoRank/Delphi](https://cryptorank.io/news/feed/e1b0f-new-crypto-listings-losses-2025-report)
- Cross-listing returns (academic) — [ScienceDirect S0929119920302972](https://www.sciencedirect.com/science/article/pii/S0929119920302972)
- Low-float/high-FDV structural dump & unlocks — [HEXN](https://hexn.io/local-updates/low-float--high-fdv-why-new-altcoins-almost-always-dump--and-what-the-cycle-data-shows-e90d0af8ebc93b8ax3brzayr) ·
  [Gate Learn — token unlocks](https://www.gate.com/learn/articles/time-scheduled-token-unlocks-an-elephant-in-the-room/4895) ·
  [Unchained](https://unchainedcrypto.com/whos-to-blame-for-the-underperformance-of-low-float-high-fdv-tokens/)

**Risks — rug / honeypot / bots / exit:**
- pump.fun ~98.6% rug, Raydium ~93% soft-rug — [Solidus Labs 2025 Rug Pull Report](https://www.soliduslabs.com/reports/solana-rug-pulls-pump-dumps-crypto-compliance) ·
  [Bitget summary](https://www.bitget.com/news/detail/12560604746174) · [CoinDesk](https://www.coindesk.com/business/2025/05/07/98-of-tokens-on-pump-fun-have-been-rug-pulls-or-an-act-of-fraud-new-report-says)
- pump.fun graduation ~1.4% — [TheBlock data](https://www.theblock.co/data/on-chain-metrics/solana/pump-fun-percent-graduated-tokens-daily) ·
  [Smithii](https://smithii.io/en/graduate-token-pump-fun/)
- Safety checkers (RugCheck / GoPlus / Honeypot.is / Solsniffer; mint/freeze authority, LP burn, sell-sim) —
  [RugCheck](https://rugcheck.xyz/) · [Solsniffer](https://www.solsniffer.com/) ·
  [honeypot-detection how-to](https://dev.to/mrwizardlyloaf/how-to-detect-a-solana-honeypot-token-before-your-bot-buys-2cdf)
- Bot competition / MEV / slippage 5–15% on launches — [Dysnix sniper comparison](https://dysnix.com/blog/top-solana-sniper-bot) ·
  [slippage settings](https://solanasniperbot.net/solana-slippage-settings/)
- Pre-listing / buy-before-listing playbook — [Coinmonks (CyberPunkMetalHead)](https://medium.com/coinmonks/how-i-buy-coins-before-they-get-listed-on-binance-ff5e9f6fa867) ·
  [Bitget — track Binance listings](https://www.bitget.com/academy/binance-listing-trac)

---

*Status: DESIGN/RESEARCH — stored, not built. No money-path code. Verdict: split Quant (Lane A, Gate-able
behind a survivorship-free dataset) / LLM (Lane B, snipe-lane, human-armed, capped). Next action is gated
on operator intent per §7.*
