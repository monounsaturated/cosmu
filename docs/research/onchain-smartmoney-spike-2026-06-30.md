# On-chain "smart money" wallet tracking — SPIKE — 2026-06-30

**Question:** Can we build the on-chain analog of our social-authority lane — score/track the few-but-huge
WALLETS that consistently buy coins early *before* they pump, then follow/copy them? This is a SPIKE:
short probe, store the finding, **no build, no keys, no real money.**

**Bottom line (GO/NO-GO):**
- 🔴 **NO-GO on the naive lane** — *mechanically mirror a smart wallet's swaps fast.* The evidence is
  consistent and damning: the edge **evaporates in the copy step itself**. The cleanest direct measurement
  (90-day, 100,236 outcomes) shows leaders are green on their own book **97.0%** of the time but produce
  **positive follower PnL only 43.6%** of the time.[¹](#refs) You buy the bump the leader caused, sell into
  worse liquidity, and the space is maximally crowded by co-located sniper/MEV bots (>$1B cumulative bot
  revenue; 200+ bots per launch).[²](#refs) The only version with a pulse is *becoming a same-slot competing
  sniper* — a latency/fee HFT race that **directly contradicts our edge thesis** (weak signals, small markets,
  NOT HFT).
- 🟡 **CONDITIONAL-GO on the lane reframed as a SIGNAL, not an execution.** Treat wallet flow exactly like
  the [[authority_feature_design_2026-06-29]] lane: a **proprietary point-in-time DATA source** — "early-entry
  concentration by historically-OOS-validated wallets" — fed into the existing Gate as one anonymized,
  propose-only nowcast. This is the honest on-chain analog of social-authority, and the **free Solana data
  path makes it ~$0 to prototype.** It is NOT a money-path; it never mirrors a trade.
- **Free-data path EXISTS and is cheap** (Helius free tier webhooks + Dune free tier discovery + DexScreener
  prices, all keyless-or-free-keyed on Solana). The blocker was never the data — it is that the *obvious use*
  of the data (copy-execution) is a negative-EV trap.

This re-confirms the project pattern: an on-chain "authority" of wallets is a **data axis**, not a strategy.
Same verdict shape as [[polymarket_correlation_lane_2026-06-29]] and [[authority_consumer_2026-06-29]] —
use the flow as a NOWCAST feeding a gated, human-armed proposal; never as a mirror.

---

## 1. Data sources + tooling — what's FREE/keyless vs PAID (Solana + EVM)

The good news: **on Solana the free path is fully viable** for tracking a *watchlist* of wallets in
near-real-time. EVM is harder (real-time mempool is effectively paid).

### Free / keyless (the path we'd actually use)

| Layer | Tool | Free capability | Limit / caveat |
|---|---|---|---|
| **Live wallet swaps** | **Helius free tier** | $0: **1M credits/mo, free webhooks, Enhanced/parsed tx (raw → `SWAP`)**. Register a watchlist → swap events pushed to your URL, no polling. | gRPC/LaserStream is devnet-only on free; WebSocket included. *This is the keystone of the free path.*[³](#refs) |
| **Live (keyless fallback)** | Public Solana RPC `logsSubscribe { mentions:[wallet] }` | Pushes every tx-log mentioning an address. Decode via `getTransaction(jsonParsed)`. | Public node **100 req/10s/IP**, "not for production"; flaky for many wallets — stabilize with a free keyed RPC.[⁴](#refs) |
| **Discovery / wallet ranking (batch)** | **Dune free tier** | 2,500 credits/mo, API included; SQL the curated `dex.trades` spellbook (all DEXs incl. Solana) for full per-wallet trade history & PnL. | Batch/analytical, **not real-time**. ~dozens of API executions/mo. Good for offline watchlist building only.[⁵](#refs) |
| **Per-wallet PnL / win-rate (frontend)** | **GMGN.ai** website | Strongest free frontend: total PnL, win-rate, avg hold, "smart money" + KOL tags. | Programmatic access is **Cloudflare-protected**; scraping blocked. Official keyed OpenAPI exists but is rate-limited.[⁶](#refs) |
| **Prices / liquidity** | **DexScreener** REST | Fully free, no key, documented — pairs/tokens/price/liquidity. | Token-level, no per-wallet PnL. Best free price layer.[⁷](#refs) |
| **EVM confirmed flow** | Etherscan-V2 free key | 5 cps / 100k calls/day, one key all chains: `tokentx`, tx-by-address, balances. | **No mempool.** Post-confirmation only. Some endpoints moved to paid in 2025.[⁸](#refs) |

### Paid — what the money actually buys

| Provider | Rough price (2025-26) | What you're buying |
|---|---|---|
| **Nansen** | Std **$99/mo**, VIP $1,899 | The **"Smart Money" labels** (curation) across EVM+Solana. You pay for *which wallets*, not speed.[⁹](#refs) |
| **Arkham** | Free tier + paid | Entity/identity labels (who owns a wallet), crowdsourced; cheaper Nansen alt.[⁹](#refs) |
| **Helius paid** | Dev $49 / Business **$499** / Pro $999 | **Production Yellowstone gRPC (LaserStream)**, 50–500 RPS, `sendBundle`, Jito staked connections — i.e. low-latency + tx-landing.[³](#refs) |
| **Birdeye** | Std **$99/mo** | Token + **wallet-PnL APIs**, 400+ DEXs. Wallet endpoints still beta/rate-capped (5 RPS).[¹⁰](#refs) |
| **Bitquery** | Free trial; paid points (sales-quoted) | GraphQL `DEXTrades` by wallet + **real-time subscriptions** across every DEX.[¹¹](#refs) |
| **Dune Plus/Premium** | 25k / 100k credits | More executions, bigger rows. Still batch.[⁵](#refs) |

**Takeaway:** for a watchlist we *already have*, paid mostly buys **latency + tx-landing** (Helius Business
gRPC + Jito) — which §3 shows is a losing race for a follower. For *discovering* the watchlist, paid buys
**labels** (Nansen/Arkham). Given §4's crowdedness evidence, **spend on selection quality before latency** —
but per the SIGNAL reframe, we likely never spend at all.

### Real-time streaming mechanics (how copy-bots detect a swap)
- **Solana:** the industry standard is **Yellowstone gRPC / Geyser (Dragon's Mouth / LaserStream)** — taps the
  validator bank, typed Protobufs, **sub-50ms**. Free path uses `logsSubscribe` (higher latency, keyless) or
  Helius webhooks (hundreds-of-ms to seconds — fine for *positioning*, not sniping).[³](#refs)
- **EVM:** mempool/pending-tx is `newPendingTransactions` / Alchemy `alchemy_pendingTransactions` (ETH/Polygon,
  **not Base**), and only what passed through that provider's nodes. **Reliable low-latency mempool = paid.**[¹²](#refs)

---

## 2. Honest "smart money" identification (no look-ahead / survivorship)

How the labels actually work: Nansen/GMGN use undisclosed rule-based heuristics over realized PnL, hold time,
trade count, early-adoption.[¹³](#refs) The thresholds are proprietary — **could not obtain Nansen's actual
PnL cutoffs or windows** (evidence gap).

**Why rank-by-past-PnL-then-follow is biased — three compounding traps:**

1. **Survivorship.** Leaderboards show survivors; the population that ran the same play and blew up is hidden.
   Nansen itself ships a **"Former Smart Trader"** label (qualified before, not now) and an **"Exit Liquidity"**
   label — *direct vendor admission that the label does not persist.*[¹⁴](#refs)
2. **Fat tails = past PnL is mostly luck.** Memecoin returns are power-law (crypto tail exponents *fatter* than
   equities); a wallet's window PnL is dominated by one or two lottery hits → **not predictive** of the next
   window.[¹⁵](#refs)
3. **Direct proof the alpha doesn't transfer.** The pump.fun study found the single highest-profit wallet had
   **1,793 sells and ZERO buys** — not a trader at all, an aggregation/exit address. A PnL ranker would crown it
   "smartest money."[¹⁶](#refs)

**The honest method (the only one we'd allow into the Gate):**
- **Point-in-time wallet scoring** — score a wallet using only data available *at* T, then measure hit-rate on
  movers that pumped *after* T. Never evaluate on the ranking window.
- **Out-of-sample forward validation** — fix the wallet set *before* an unseen period.
- **Full-denominator hit-rate** — all picks including the dead ones, never just the winners.
- This is identical to how [[authority_feature_design_2026-06-29]] scores callers (Brier + EV + magnitude,
  echo-discard) and how the Gate already demands PIT + OOS. The wallet score is just another anonymized series.

**Persistence — does top-wallet alpha survive OOS?** Evidence is **weak and mostly against.** No clean
peer-reviewed study demonstrates persistent *copyable* wallet alpha; high-turnover/bot wallets systematically
underperform on sustained outcomes;[¹⁶](#refs) industry concedes "most retail copy-traders don't capture the
edge even when they identify the right wallet" — i.e. **identification is not the binding constraint, execution
is.** The clean decay-rate number (top-decile this month → next month) is a **genuine missing measurement** —
if we prototype the SIGNAL lane, *that is the first thing to compute ourselves.*

---

## 3. Copy-execution path + latency — can we follow before the pump?

**This is where the naive thesis dies.**

- **The window is minutes-to-seconds.** pump.fun graduations: **median 4.4 min**, ~457 trades; coordinated
  buys cluster within seconds; bundlers buy in the **same block** as launch.[¹⁶](#refs) By the time a copy
  signal is even visible, the early price is gone.
- **Fees buy inclusion, not speed.** Measured: priority-fee and Jito-tip size have **no statistically
  significant effect on time-to-inclusion**.[¹⁷](#refs)
- **Real landing is seconds, not ms.** Solana slot ~400ms, but the measured inclusion distribution is trimodal
  at **5s (bots) / 17s (users) / 63s (slow)**. "Millisecond copy" marketing conflates *reaction time* with
  *settled-fill time.*[¹⁷](#refs)
- **Public RPC = already late** — "getting filtered, rate-limited, de-prioritized." To compete you need
  **ShredStream** (50–200ms earlier), colocation, multi-relay routing.[¹⁸](#refs)
- **Slippage punishes the follower.** The leader's buy *moves the bonding curve*; the follower's identical buy
  lands higher and thinner. Selling *before* graduation yields **15–20% better proceeds** — a structural reason
  the leader exits before the follower can.[¹⁶](#refs)

**Verdict:** a follower can only get a comparable price by being a co-located, ShredStream-fed bot landing in
the **same slot** — at which point it has stopped being a follower and become a competing sniper (capital- and
infra-heavy HFT vs professionals). Same-slot-copy claims trace to **bot-vendor repos, not measured fills** —
weak evidence. For anyone landing ≥1 slot later, you buy the bump. ⚠️ Did not find an EVM-specific copy-latency
study, but EVM's slower base layer + public mempool make followers *more* exposed, not less.

---

## 4. Structural edge + is it already crowded?

**Why Wall Street doesn't track degen wallets (real & durable reasons):**
- **AML/KYC + reputation** — memecoins are a regulatory grey zone "synonymous with rug pulls"; institutions
  can't touch anonymous pump.fun tokens.[¹⁹](#refs) The SEC's 2025 "most memecoins aren't securities" removed
  the *securities* barrier but not the AML/reputation one.
- **Capacity** — median graduation in 4.4 min on sub-$1M pools is far too small/illiquid for institutional size.

**But "no big players" is NOT a durable edge — it's already arbitraged, just not by Wall Street.** The space is
saturated by professional **sniper/MEV/bundler bots** with co-located infra (≈70% of non-vote Solana tx run
through Jito bundles). Retail copy-bots sit at the *bottom* of that food chain. Scale of the bot ecosystem:
- Solana bots: **>$1B cumulative revenue** (Photon $386M, BullX $188M, Trojan $177M ≈ 75%).[²](#refs)
- Trojan alone ~$24B lifetime volume, ~2M users, 0.9%/side fee. By Q1-2026 major launches draw **200+ competing
  bots in the first half-second.**[²](#refs)
- Wallet copying is a **commodity consumer feature** (GMGN/Trojan/Photon/Maestro/Banana Gun all ship it). It is
  not an edge — it is the thing everyone already does.
- The **"imitation penalty"** + **reflexive death spiral**: many copy one wallet → buy within seconds → price
  spikes → the *original wallet sells into the spike copiers created.* Smart wallets know they're copied and
  exploit it; arXiv 2026 documents **manipulative wallets that bait copy-bots.**[²⁰](#refs)

---

## 5. Honest risks

1. **Wash trading / fake PnL / sybil.** Up to **$2.57B** suspected wash trading (Chainalysis, *2024* data).[²¹](#refs)
   Self-funded clusters manufacture both volume *and* apparent PnL — a leaderboard can't tell a real edge from a
   sybil cluster recycling its own SOL.
2. **Honeypots / rugs / can-buy-can't-sell.** Chainalysis 2024: **74,037 tokens (3.6%)** showed pump-and-dump
   patterns; **~94% of suspected P&D pools rugged by the creator**; avg scheme life **6.2 days**.[²¹](#refs)
   pump.fun graduation rate **0.63%** (>99% fail); **92%** of traded tokens show ≥1 dump event.[¹⁶](#refs)
   Solana honeypots use **freeze authority** (buy on, sell frozen) — detection needs our own mint/freeze-authority
   + LP-lock + holder-concentration checks.[²²](#refs)
3. **Being exit liquidity / coordinated bait.** The "1,793 sells / 0 buys" top wallet *is* designed exit
   liquidity.[¹⁶](#refs) The decisive number again: **97.0% leader-green vs 43.6% follower-green**; MEXC
   followers net **−210,040 USDT** despite a 57.8% raw win-rate.[¹](#refs) ⚠️ that study is **CEX copy-trading**;
   on-chain the latency/slippage gap is *worse*, so it bounds the optimistic case.
4. **MEV / sandwiching.** Copy txs are predictable *by construction* (same target, mechanical follow) — exactly
   what sandwich bots want. Bots market "Anti-MEV" precisely because the mempool is adversarial.[²³](#refs)

---

## Decision & the cheapest next probe (if any)

**Naive copy-trade lane → 🔴 NO-GO / trap.** Negative-EV, maximally crowded, contradicts the edge thesis.
Do **not** build a wallet-mirror execution path. File alongside the [[polymarket_wedge_triage_2026-06-27]] and
[[deribit_options_substrate_2026-06-29]] KILLs — chased, measured, closed.

**Wallet-flow-as-a-SIGNAL → 🟡 CONDITIONAL-GO, propose-only, ~$0 to prototype.** *If* we want the on-chain
authority axis, build it like [[authority_feature_design_2026-06-29]]:
1. **Free data:** Dune free tier to rank candidate wallets (PIT) → Helius free-tier webhook on the watchlist →
   DexScreener for price context. Keyless or free-keyed; no spend.
2. **Honest score:** point-in-time, OOS-forward, full-denominator hit-rate on FUTURE movers. **First deliverable
   = the missing decay-rate number** (top-decile wallet → next-period performance). If it's noise, kill the lane.
3. **Consume like a nowcast:** feed the anonymized wallet-flow series into the **existing Gate** as one signal /
   a propose-only [[conviction_consumer_2026-06-29]]-style proposal — human-armed, NOT a mirror, NOT the Gate.

This keeps the aggressive degen ambition ([[aggressive_target_2026-06-30]]) honest: the *upside* lives in the
SIGNAL feeding our own gated sniper logic, not in mechanically chasing wallets into their own exit liquidity.

⚠️ **Reconciling with the 2-3X-in-a-day target:** the sniper *itself* (our own gated low-float entry) may still
be a degen lane worth probing — but "copy a smart wallet" is **not** the way in. If we pursue on-chain sniping,
it's our own signal + own execution, with the wallet score as *one weak input*, not the trigger.

### Evidence gaps (be honest)
- Nansen/GMGN exact PnL thresholds & windows (proprietary).
- A clean public **decay-rate** of top-PnL wallets OOS — *genuinely missing; would be our first computation.*
- **Measured** (not vendor-claimed) same-slot copy-fill rate and realized leader→follower price gap (bps) on Solana.
- EVM-specific copy-latency/slippage figures.
- Source vintage: Chainalysis figures are **2024**; the 90-day copy study is **Oct–Nov 2025, CEX-only**; the
  pump.fun paper (Sept-2025) is the strongest on-chain academic anchor. Flagged inline, not blended as uniform "2026".

---

## <a name="refs"></a>References

1. 90-day multi-exchange copy study (100,236 outcomes; 97.0% leader-green vs 43.6% follower-green; MEXC −210,040 USDT) — yieldfund.com/is-copy-trading-profitable-a-90-day-multi-exchange-study
2. Solana bot revenue >$1B; Photon/BullX/Trojan; 200+ bots/launch — kucoin.com/news (Solana bots >$1B), solanatools.io/blog/solana-trading-bot-fees-compared, solanatradingbots.com
3. Helius pricing/free tier, webhooks, Yellowstone gRPC — helius.dev/pricing, helius.dev/docs/grpc, helius.dev/solana-webhooks-websockets
4. Solana public RPC limits + `logsSubscribe` — solana.com/docs/references/clusters, solana.com/docs/rpc/websocket/logssubscribe
5. Dune free tier + `dex.trades` — dune.com/pricing, dune.com/blog/new-paid-experience, dune.com/chains/dex-trades
6. GMGN wallet stats + Cloudflare + OpenAPI — docs.gmgn.ai/index/gmgn-agent-api, github.com/GMGNAI/gmgn-skills
7. DexScreener free REST API — docs.dexscreener.com
8. Etherscan V2 free tier limits — docs.etherscan.io/support/rate-limits, info.etherscan.com (free-tier changes)
9. Nansen pricing + Smart Money labels; Arkham — nftevening.com/nansen-review, nansen.ai/post (who counts as smart money), walletfinder.ai/blog/nansen-alternatives
10. Birdeye pricing + wallet APIs — docs.birdeye.so/docs/pricing
11. Bitquery DEXTrades + streams — bitquery.io/pricing, bitquery.io/products/dex
12. Alchemy pending-transactions (mempool) — alchemy.com/docs/reference/alchemy-pendingtransactions
13. Nansen smart-money criteria (qualitative) — nansen.ai/post/who-counts-as-smart-money-in-crypto
14. Nansen "Former Smart Trader" / "Exit Liquidity" labels — academy.nansen.ai/articles (labels-and-watchlists-101)
15. Crypto fat-tail / power-law returns — arxiv.org/pdf/1803.08405, arxiv.org/pdf/2302.12319
16. pump.fun study (4.4-min graduation, 0.63% rate, 1793-sells/0-buys wallet, 15–20% pre-grad exit, 92% dump) — arxiv.org/html/2602.14860v1
17. Solana tx latency — fees buy inclusion not speed; trimodal 5/17/63s — chorus.one/reports-research (transaction-latency-on-solana)
18. ShredStream / colocation / RPC-is-late — rpcfast.com/blog/solana-trading-bot-guide, docs.jito.wtf/lowlatencytxnsend
19. Memecoin compliance / institutional avoidance — hypernative.io/blog (memecoins-gone-wild), onesafe.io/blog (memecoin-compliance), gtlaw (SEC meme-coin stance)
20. Imitation penalty / death spiral / bait bots — solanasniperbot.net/solana-copy-trading-guide, arxiv.org/pdf/2601.08641 (Resisting Manipulative Bots in Meme Coin Copy Trading)
21. Wash trading / pump-and-dump (2024 data) — chainalysis.com/blog (crypto-market-manipulation-wash-trading-pump-and-dump-2025)
22. Solana honeypot detection (freeze authority) — pumpora.net/blog/solana-honeypot-checker, barryguard.com/blog (solana-token-rug-pull)
23. MEV / sandwiching of copy txs — odinbot.io (solana-mev-bots-in-copytrading), quicknode.com/guides (mev-on-solana)

*SPIKE only — no code, no keys, no real money. Probe ran 2026-06-30.*
