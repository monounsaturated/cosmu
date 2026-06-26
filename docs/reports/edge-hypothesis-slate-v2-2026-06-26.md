# Edge-Hypothesis Slate v2 — fresh non-price / segmentation-moat batch (2026-06-26)

> **Findings only, zero production impact.** A deliberately FRESH batch generated *off* the dead-or-slate set.
> Hypothesis diversity is the binding constraint: the [Experiments Ledger](../EXPERIMENTS_LEDGER.md) and the
> [edge sprint synthesis](edge-sprint-synthesis-2026-06-25.md) close **price-derived crypto signals** as
> exhausted at our cost tier, and the [v1 slate](edge-hypothesis-slate-2026-06-25.md) already covers
> cross-venue funding divergence, liquidation skew, stablecoin chain-rotation, basis-momentum, Polymarket
> theta-decay / intraday over-extension, weather-forecast-gap and resolution-lag. **Nothing here repeats any of
> those.** Every hypothesis below sits in a lens that is in NEITHER the dead set NOR the v1 slate.
>
> **Generated:** 14 · **Survived adversarial critique:** 8 · **Test-first pick:** N1 (UMA pre-settlement convergence).

---

## Method & guardrails

The moat is **segmentation, never speed** (memory `edge_thesis`): COSMU wins on weak signals in small/niche markets and
cheap social/structural data the giants ignore. So this batch is built entirely from **non-price, PIT-honest, keyless**
lenses I verified against the wired codebase:

- **Wired keyless sources confirmed present** (`cosmu/data/sources/registry.py`): DefiLlama (`make_defillama_sources`,
  `make_stablecoin_flow_sources`), CoinGecko (`make_coingecko_sources`, incl. BTC dominance), GDELT counts, ETF flows,
  SEC EDGAR Form-4, Wikipedia pageviews, Google Trends, Reddit volume, CryptoPanic votes, weather/Open-Meteo,
  Polymarket CLOB + per-market odds + **the UMA resolution-time / settlement join** (`polymarket.py`, the #393 work),
  multiasset (Stooq/Yahoo equities), funding (Binance/OKX/Kraken-Futures), `universe_pairs` (venue-tagged, delisted-PIT).
- **Each hypothesis carries:** mechanism (WHO loses the trade), data (keyless flag), entry/exit, gate-path (≥30 trades/cell
  via pooling or sub-daily bucketing), an explicit novelty argument vs the dead-or-slate set, and `edge_thesis_fit` 1–5.
- **Then an adversarial critique** against the five tripwires that killed prior rounds (memory `vibe_coding_leakage_risk`,
  `RESEARCH_LESSONS.md`): **(a)** leakage / backfilled-revising source [PIT identity], **(b)** already-failed-in-spirit,
  **(c)** overfit / beta-in-disguise, **(d)** feasibility / data-wall, **(e)** moat-fit / cost-wall. → **KEEP or KILL**.

The cardinal rule from the ledger holds throughout: the Gate is never the wall — **cost, data-access, or genuine
absence** is. So feasibility and cost are weighted heavily in the critique.

---

## The 14 generated hypotheses

### Lens A — Prediction-market microstructure *beyond* the simple fade

#### N1 · UMA pre-settlement convergence (the on-chain proposal IS the truth-feed)
- **Mechanism — who loses:** Polymarket resolves via UMA's optimistic oracle. When an outcome is proposed on-chain, a
  **~2-hour liveness window** opens before it is final ($1/$0). The proposal is a *public on-chain event* the instant it
  lands, but the CLOB market is still quoted by slow retail who haven't watched the oracle. Retail who keep selling the
  about-to-win YES at 0.93–0.98 (or buying the about-to-lose NO) lose to anyone reading the proposal. This is a
  **resolution-source-latency** play: the edge is the gap between *proposal-is-public* and *price-is-$1*.
- **Data (keyless? YES):** the Gamma row already exposes `umaResolutionStatus` / proposed+resolved times
  (`polymarket.py:367-447`, already parsed). CLOB `/prices-history` gives the post-proposal odds path. The proposal
  timestamp is the PIT marker (`available_at` = proposal block time). No key.
- **Entry/exit:** when a market enters UMA proposal liveness with YES quoted ≤ 0.97 (or NO ≥ 0.03), buy the
  about-to-win leg at the quote; exit at resolution ($1). One trade per resolving market.
- **Gate-path:** every closed market in the backfill is one event; geopolitics+sports+crypto pooled → hundreds of
  resolutions clear ≥30 easily, then BRUT per category (fee differs: geo 0% / sports 3% / crypto 7.2%).
- **Novelty vs dead-or-slate:** the ledger's **H9 is hold-to-resolution theta-decay** (long-shot decay, killed by
  survivorship); the v1 slate's **H2/N-resolution-lag uses an *external* truth-feed** (Kraken bar / RSS pubDate). **N1
  uses the UMA proposal event itself** as the truth-feed and trades only the **terminal liveness window**, not the whole
  life of the contract — a different signal, a different (much shorter) horizon, and a different leakage profile.
- **edge_thesis_fit: 5** (reg-grey, no-desk, structural latency nobody arbs because it needs oracle-watching not speed).

#### N2 · Cross-market coherence (correlated, non-mutually-exclusive markets disagree)
- **Mechanism:** beyond negRisk (mutually-exclusive, where "sum of YES < 1" is a known, competed arb), Polymarket hosts
  many **logically-correlated but separate** markets ("Fed cuts in July" vs "Fed cuts ≥2 times in 2026"; "Candidate X wins
  primary" vs "Party Y wins general"). When two markets whose YES probabilities are *mechanically linked* drift out of
  coherence, the lagging one is mispriced by category-siloed retail who only watch one market. Trade the laggard toward
  the leader's implied bound.
- **Data (keyless? YES):** Gamma event/tag grouping + CLOB odds per conditionId; the coherence constraint is a
  hand-specified inequality (P(superset) ≥ P(subset)). No key.
- **Entry/exit:** when P(subset-market) > P(superset-market) + threshold (a logical violation), buy the underpriced
  superset / sell the overpriced subset; exit on re-coherence or resolution.
- **Gate-path:** pool across all hand-mapped correlated pairs; sub-daily odds → ≥30 violation-events.
- **Novelty:** the v1 slate never touches *cross-market* structure (it fades a *single* market's intraday over-extension).
  negRisk sum-arb is the *competed* cousin; **coherence across non-exclusive linked markets is the under-watched one**.
- **edge_thesis_fit: 4** (segmentation: category-siloed attention; but mapping the logical links is manual, and fillable
  size on niche markets may be thin).

#### N3 · Prediction-market dispersion → underlying realized-vol forecast (the Kalshi-paper channel)
- **Mechanism:** a 2026 study (*Do Prediction Markets Forecast Cryptocurrency Volatility?*, arXiv 2604.01431) shows
  **daily probability *changes* in macro prediction markets forecast crypto realized vol** — Fed-repricing predicts BTC
  vol at **t=3.63, peaking 3–5 days out**. Mechanism: prediction markets aggregate informed macro views that diffuse into
  crypto vol over days; retail spot traders price it late. We don't trade direction — we trade a **vol-target / straddle-
  proxy**: scale exposure (or a long-gamma perp-rebalance) up when PM macro-dispersion spikes.
- **Data (keyless? YES):** Polymarket Fed/macro markets (already discovered by `PolymarketClobSource` MACRO_TAGS) give the
  implied-prob path; `pm_prob_velocity` is already a wired metric. The *target* is realized vol of BTC/ETH (own bars).
- **Entry/exit:** vol-regime overlay — when PM macro |Δprob| z-score is high, raise a vol-target book's gross (or hold a
  cheap long-gamma rebalance); flat otherwise. Horizon 3–5d.
- **Gate-path:** this is a *conditioning variable*, gated as a regime filter on an existing vol-target book; per-asset
  BRUT with ≥30 high-dispersion windows over 2yr.
- **Novelty:** the orphaned `polymarket-positioning-risk-flip` inbox spec uses `pm_implied_prob`/`pm_prob_velocity` as a
  **directional risk-on/off regime filter**. **N3 is orthogonal:** it forecasts *second-moment* (vol), not direction, via
  the *macro-repricing* channel specifically — a different target with a published prior. Not in the dead set, not in v1.
- **edge_thesis_fit: 4** (published external prior, PIT-clean, weak-but-real; the risk is it's a vol-timing not an alpha).

### Lens B — On-chain flows done right (specific cohort / derivative, not aggregate level)

#### N4 · Cross-chain bridge net-inflow → destination-chain native token
- **Mechanism:** DefiLlama tracks **per-chain bridge inflows/outflows**. A surge of *net bridged-in* capital to a chain is
  exogenous demand that must, mechanically, be deployed on-chain before it can buy the chain's gas/native token — a
  forced-flow that front-runs the native token's repricing by under-covered retail. This is a *flow derivative*, not a TVL
  *level* (the level was the cycle-artifact that died in the orthogonal-data round).
- **Data (keyless? YES):** DefiLlama `/bridges` + `/bridgevolume/{chain}` are free, no-key (confirmed). PIT: daily aggregate
  knowable T+1 (same contract as wired `stablecoin_flows`). **Not currently ingested** (grep: no bridge code) → novel.
- **Entry/exit:** 7–14d net-bridge-inflow z-score per chain crosses a tercile; long the native token (SOL/ARB/AVAX/etc),
  hold N days; exit on z-reversion.
- **Gate-path:** pool across ~8 mid-tier chains × tercile crossings → ≥30; per-chain BRUT with a **placebo-chain null**.
- **Novelty:** the dead set's **H7 is stablecoin float-*share*** (died as Solana bull-phase beta); **N4 is total bridge
  *net-flow*** (a different, larger, exogenous quantity) with the **placebo-chain disconfirmer baked in** to catch exactly
  the beta-confound that killed H7. Not in v1.
- **edge_thesis_fit: 4** (mid-tier chains = under-covered moat; but high beta-confound risk — see critique).

#### N5 · Token-unlock supply-shock drift (the calendar everyone can see, nobody sizes)
- **Mechanism:** large vesting **unlocks** are a *pre-announced, dated* supply shock. The cliff date is public months ahead,
  yet small/mid-cap tokens systematically drift **down into** large unlocks (sellers front-run) and often **relieve after**
  (overhang cleared). Retail holds through the cliff; informed flow positions early. Classic forced-flow with a fixed,
  leak-proof PIT date (the unlock schedule is set at TGE).
- **Data (keyless? YES):** DefiLlama `/unlocks` calendar (confirmed free). PIT is *trivially clean* — the unlock date is
  knowable at token genesis, so `available_at` ≪ event. **Not ingested** → novel.
- **Entry/exit:** short (or avoid) a token in the N days *before* a >X%-of-float unlock; optionally long the post-cliff
  relief. Event-study windows around each cliff.
- **Gate-path:** every large unlock across the universe is one event; pool → hundreds; BRUT per size-tercile. Spot can only
  trade the *long relief* leg; the *short into* leg needs a perp venue (Hyperliquid small-caps).
- **Novelty:** **No unlock/vesting code exists** (grep confirmed). Entirely absent from dead set and v1 slate.
- **edge_thesis_fit: 5** (small-cap forced-flow nobody sizes; dated, leak-proof, segmentation-pure).

#### N6 · Exchange-netflow cohort divergence (the *direction* of stablecoin minting)
- **Mechanism:** `ExchangeNetflowProvider` exists but aggregate netflow is noisy. The **signed** version — large stablecoin
  *mints* (USDT/USDC issuance) landing *on exchanges* vs *off* — distinguishes dry-powder-arriving (bullish) from
  redemptions (bearish). Tether/Circle mints are on-chain and public; the destination (CEX deposit address clusters)
  segments informed dry powder from neutral float.
- **Data (keyless? partly):** stablecoin total mcap/flow is wired (`make_stablecoin_flow_sources`); the **destination split**
  needs labelled exchange addresses — borderline keyless (some free address lists; full clustering is heavier).
- **Entry/exit:** net-mint-to-exchange z spikes → long BTC/ETH over N days.
- **Gate-path:** market-wide single series → pool over time for ≥30.
- **Novelty:** the stablecoin *level/share* died (H7, orthogonal round); the *mint-destination split* is a different
  derivative. But see critique — feasibility of the address-labelling is the question.
- **edge_thesis_fit: 3.**

### Lens C — Event / unlock / listing / governance-driven drift

#### N7 · CEX listing-announcement drift on the *non-listed* venue
- **Mechanism:** when Coinbase/Binance *announce* a listing (roadmap tweet / blog), the token pumps — but the **buy-the-
  rumor-sell-the-news** pattern is well documented (search: "bullish but usually not for long"). The under-exploited edge
  isn't the pump; it's the **predictable mean-reversion fade 1–3 days after** the announcement spike, on the *other*
  venues where the token already trades (the listing venue itself often has the cleanest dump). Retail FOMO-buys the
  announcement; the fade is the informed exit.
- **Data (keyless? YES):** listing announcements are public (RSS/blog feeds; we have `rss_news` + GDELT counts). The token's
  pre-listing price is on Binance/Kraken/HL bars (universe_pairs).
- **Entry/exit:** detect the announcement spike (GDELT count spike + price jump), short/avoid the 1–3d post-spike fade.
- **Gate-path:** every announcement is one event; pool across 2yr of listings → ≥30.
- **Novelty:** listing-driven drift is nowhere in the dead set or v1 slate.
- **edge_thesis_fit: 3** (the announcement *detection* is fiddly and the spike is fast — borderline speed-game; see critique).

#### N8 · Governance-vote outcome drift (Snapshot proposals → protocol token)
- **Mechanism:** major DAO governance votes (fee switches, token buybacks, emissions changes) have **fixed voting deadlines**
  and the on-chain vote tally is public *during* the vote. A proposal trending toward a value-accretive outcome (e.g. a fee
  switch turning on) is a fundamentals change that slow holders price *after* execution. Trade the token toward the
  likely-passing outcome before execution.
- **Data (keyless? YES):** Snapshot's GraphQL API is free/keyless; vote tallies + deadlines are public on-chain. **Not
  ingested** (grep: no governance code).
- **Entry/exit:** when a high-impact proposal crosses a quorum+majority threshold with a known deadline, long the token to
  execution.
- **Gate-path:** high-impact proposals are *rare* (the killer) — pooling across all governance tokens over 2yr may still
  fall short of 30 *material* events. See critique.
- **edge_thesis_fit: 4** moat-wise, **but feasibility-fragile.**

### Lens D — Cross-venue / cross-asset lead-lag (non-price-derived)

#### N9 · ETF-flow → spot drift (the regulated-capital tell)
- **Mechanism:** spot BTC/ETH ETF daily net flows (`etf_flows` is wired) are *regulated, slow, benchmark-locked* capital —
  structurally unable to react intraday. A large net-creation day is forced buying that the ETF must execute, dragging spot
  over the *following* day(s). The flow is reported T+1 (PIT-honest); retail under-weights it. This is the "benchmark-locked
  capital structurally can't move fast" mechanism that made the equity-TAA survivor real, applied as a *lead* signal.
- **Data (keyless? YES):** `make_etf_flow_sources` is wired (Farside-style daily, T+1 PIT).
- **Entry/exit:** net-creation z-score crosses tercile → long spot BTC/ETH for 1–3d; symmetric on redemptions.
- **Gate-path:** daily series, 2yr → pool tercile crossings ≥30; BRUT per asset.
- **Novelty:** ETF flows are *ingested but never tested as a lead signal* (the orthogonal round tested on-chain/F&G/VIX, not
  ETF flows). Not in v1 slate.
- **edge_thesis_fit: 3** (the flow is widely reported — moat is thin; mechanism is real but possibly already priced).

#### N10 · Equity-sector → crypto sector lead-lag (semiconductor/AI → AI-tokens)
- **Mechanism:** thematic crypto baskets (AI-tokens, DePIN, RWA) are sentiment-tethered to their equity analog (NVDA/SMH for
  AI; etc.). Equity markets are deeper and price the theme first; the crypto basket lags by 1–2 days because crypto-native
  retail doesn't watch equities. Cross-asset, cross-*market-structure* lead-lag.
- **Data (keyless? YES):** equity bars via Stooq/Yahoo (`multiasset.py`, wired); crypto baskets from universe_pairs.
- **Entry/exit:** SMH/NVDA momentum z leads → long the AI-token basket 1–2d; exit on reversion.
- **Gate-path:** basket-level (pooled) daily; 2yr → ≥30.
- **Novelty:** no equity→crypto-theme lead-lag in dead set or v1. Distinct from the closed *crypto-internal* xsec momentum.
- **edge_thesis_fit: 3** (real cross-market structure, but theme-basket definitions risk overfitting; equities are fast).

### Lens E — Social / narrative ONSET (the voices lane, but the cheap proxy)

#### N11 · Wikipedia/Google-Trends attention-onset breakout (the *acceleration*, not the level)
- **Mechanism:** a token's Wikipedia pageviews / Google Trends *suddenly accelerating* (2nd derivative) marks **narrative
  onset** — new retail attention arriving — *before* the price has fully responded, on small-caps where a few thousand new
  eyeballs move the float. We trade attention *acceleration*, not *level* (the level is a coincident/lagging beta).
- **Data (keyless? YES):** Wikipedia pageviews (`wiki_pageviews_zscore` wired) and Google Trends (`GoogleTrendsSource` wired)
  are both keyless and **PIT-honest by construction** (pageviews stamped T+1, immutable — *not* a revising source like
  LunarCrush). This is the critical distinction from the killed social-IC mirage.
- **Entry/exit:** pageview/trends acceleration z crosses tercile on a small-cap → long N days; exit on deceleration.
- **Gate-path:** pool across the small-cap universe × onset events → ≥30; BRUT per cap-tier with a **placebo-token null**.
- **Novelty:** the killed social signal was **LunarCrush (backfilled+revising → PIT-fail)**. **N11 uses immutable,
  T+1-stamped attention series** and trades *acceleration* — a different signal on a *PIT-clean* source. Not in v1 slate.
- **edge_thesis_fit: 4** (cheap social data + small-cap niche = the exact moat; PIT is the make-or-break and it's clean).

#### N12 · News-coverage-onset divergence (GDELT counts spike with *flat* price)
- **Mechanism:** GDELT daily article counts (`gdelt_counts` wired, counts-only, PIT T+1) spiking on an asset **while its
  price is still flat** is "attention has arrived, price hasn't" — a coiled-spring. The mirror (price up, coverage flat) is
  unsustained momentum. Trade the coverage-leads-price gap.
- **Data (keyless? YES):** GDELT DOC 2.0 counts, wired, keyless, PIT-honest (counts can't be revised retroactively in a way
  that breaks the identity — the count for a closed UTC day is final).
- **Entry/exit:** coverage z-score >> price z-score → long; exit on convergence.
- **Gate-path:** pool across tracked assets × divergence events → ≥30; per-asset BRUT.
- **Novelty:** GDELT *counts* (not tone — tone axis is intentionally closed) tested as a *divergence-from-price* signal is
  absent from dead set and v1.
- **edge_thesis_fit: 3** (counts are coarse; the divergence framing is the interesting part but coverage often *follows* price).

### Lens F — Niche-small-cap structural inefficiency

#### N13 · Delisted-survivorship reversion (the universe nobody backtests on)
- **Mechanism:** `universe_pairs` carries a **delisted-PIT calendar** (the #313 work). Tokens approaching delisting on a
  major venue are *forced-sold* by holders who can't custody them, often overshooting down, then partially recovering on
  the venues where they keep trading (HL/DEX). This is a pure survivorship/forced-flow niche the giants structurally avoid
  (they delist *because* it's not worth their desk's attention).
- **Data (keyless? YES):** delisted calendar is already in `universe_pairs`; bars on remaining venues.
- **Entry/exit:** in the window around a major-venue delisting announcement, fade the forced-sell overshoot on the surviving
  venue.
- **Gate-path:** delistings over 2yr → pool ≥30; BRUT.
- **Novelty:** the ledger flags "delisted-inclusive R2 universe" only as a *cost lever* for the xsec premium — **never as its
  own forced-flow signal.** Genuinely new framing on already-built data.
- **edge_thesis_fit: 4** (segmentation-pure; but fillable liquidity post-delist is the open question).

#### N14 · Stablecoin-pair de-peg micro-reversion (the boring, structural one)
- **Mechanism:** stablecoin/USD pairs (USDC, DAI, FDUSD, etc.) micro-deviate from $1.00 on liquidity shocks; the peg is a
  hard economic anchor (redeemability), so deviations beyond fees mean-revert with near-certainty. The loser is the panic-
  seller dumping below peg into a thin book. This is a structural near-arb, not a price-momentum signal.
- **Data (keyless? YES):** stablecoin spot bars from Binance/Kraken (universe_pairs).
- **Entry/exit:** when a major stablecoin trades < 0.997 or > 1.003, fade toward peg; exit at peg.
- **Gate-path:** de-peg events over 2yr → ≥30; BRUT per pair.
- **edge_thesis_fit: 2** (real mechanism but heavily competed by MM bots; near-zero edge after fees — this is a *speed* game,
  which the thesis explicitly rejects).

---

## Adversarial critique — KEEP / KILL

| # | Hypothesis | (a) Leakage / PIT | (b) Failed-in-spirit? | (c) Overfit / beta | (d) Feasibility / data | (e) Moat / cost | Verdict |
|---|---|---|---|---|---|---|---|
| **N1** | UMA pre-settlement convergence | Clean — proposal block-time is the PIT marker, knowable on-chain | No — H9 is theta-decay, slate-H2 uses external feeds | The trade is a near-tautology (about-to-win→$1); risk is the **liveness window is too short to fill at a discount** | UMA fields already parsed in `polymarket.py`; backfill = closed markets | **Strong** — oracle-watching, not speed; reg-grey | ✅ **KEEP** |
| **N2** | Cross-market coherence | Clean — live CLOB odds, no revision | No — slate fades a *single* market | Logical-link mapping is **manual → overfit risk**; constrain to a few pre-registered link types | Keyless, but **fillable size on niche legs may be ~0** | Category-siloed attention moat | ✅ **KEEP (2nd-tier)** |
| **N3** | PM-dispersion → BTC vol forecast | Clean — `pm_prob_velocity` PIT-stamped | **Partly** — orphaned `pm-risk-flip` spec uses same metrics, but **directionally**; N3 targets *vol*, published prior | Vol-timing can masquerade as alpha; gate as a regime overlay, not standalone | Wired metrics + own bars; **published external prior** (arXiv 2604.01431) | Weak signal, but real & cheap | ✅ **KEEP** |
| **N4** | Bridge net-inflow → native token | T+1 PIT (DefiLlama), clean | **Echoes H7's failure mode** (chain-flow → native token) | **HIGH beta-confound** — same Solana-bull-phase trap that killed H7; *requires* the placebo-chain null to be credible | DefiLlama `/bridges` keyless, not ingested | Mid-tier-chain moat | ✅ **KEEP (with mandatory placebo-chain)** |
| **N5** | Token-unlock supply-shock drift | **Cleanest PIT in the batch** — unlock date set at TGE, knowable years ahead | No — no unlock code exists anywhere | Event-study; control for cap-tier & market beta around the cliff | DefiLlama `/unlocks` keyless; short-leg needs a perp venue | **Pure small-cap forced-flow nobody sizes** | ✅ **KEEP** |
| **N6** | Exchange-netflow cohort split | Borderline — destination-labelling can leak if clustering uses future data | Aggregate netflow is noisy/weak (known) | — | **Data-wall risk**: free exchange-address clustering is incomplete; the *split* may be unbuildable keyless | Moat ok | ❌ **KILL** — feasibility: the destination split is not reliably keyless; without the split it's the noisy aggregate that's already weak |
| **N7** | CEX listing-announcement fade | Clean if announcement timestamp is the marker | No | The post-spike fade may just be **mean-reversion of a fast spike = a speed game** to detect the announcement | Detection is **latency-sensitive** (the pump is minutes) | **Speed-game → violates the moat thesis** (explicitly rejected) | ❌ **KILL** — moat-fit: detecting/reacting to the announcement spike is a latency race, which the edge thesis rejects |
| **N8** | Governance-vote outcome drift | Clean — on-chain tally, fixed deadline | No | — | **Material high-impact proposals are RARE** → likely <30 events even pooled over 2yr | Strong moat if it existed | ❌ **KILL** — feasibility/gate-path: the event count is too thin to clear 30 *material* trades honestly (the H3-funding-conjunction failure mode: a non-event) |
| **N9** | ETF-flow → spot drift | T+1 PIT, clean | No (orthogonal round tested on-chain/F&G/VIX, not ETF flows) | Could be coincident not leading; needs lead-lag asymmetry test | `etf_flows` wired, keyless | **Thin moat** — flows are widely reported and front-run by everyone | ✅ **KEEP (low-priority)** — cheap to test, but expect it's priced |
| **N10** | Equity-sector → crypto-theme lead-lag | Clean — equity bars are immutable | No | **Theme-basket definition is a free parameter → overfit** unless pre-registered; equities are fast | Stooq/Yahoo + universe_pairs, keyless | Cross-market-attention moat is real but equities aren't *that* slow | ✅ **KEEP (low-priority, pre-register baskets)** |
| **N11** | Attention-acceleration breakout | **Clean & critical** — Wikipedia/Trends are **immutable, T+1-stamped** (NOT LunarCrush's revising-backfill trap) | **No** — the killed social signal was the *revising* source; this is the PIT-clean cousin trading *acceleration* | Small-caps → noisy; placebo-token null required | Both sources wired, keyless | **Cheap social data + small-cap = the exact moat** | ✅ **KEEP** |
| **N12** | News-coverage-onset divergence | Clean — GDELT counts, PIT T+1, immutable-for-closed-day | No (tone axis closed; this is counts-divergence) | Coverage often *follows* price → the divergence may be mostly lag, not lead | GDELT wired, keyless | Coarse signal; thin moat | ❌ **KILL** — overfit/spirit: GDELT counts most plausibly *lag* price; the "coverage leads" direction is the weaker, less-defensible half, and counts are too coarse to isolate onset |
| **N13** | Delisted-survivorship reversion | Clean — delisted-PIT calendar already in `universe_pairs` | No — only ever flagged as a *cost lever*, never a signal | Forced-sell overshoot is plausible; control for the general small-cap drawdown | Calendar built; **fillable post-delist liquidity is the open question** | **Pure segmentation moat** (giants delist *because* they won't watch) | ✅ **KEEP** |
| **N14** | Stablecoin de-peg micro-reversion | Clean | No | — | Keyless bars | **Heavily MM-bot-competed → a speed game with ~0 edge after fees** | ❌ **KILL** — moat/cost: this is a latency-contested near-arb; the thesis explicitly rejects speed games |

**Generated: 14 · Survived: 8** (N1, N2, N3, N4, N5, N9, N10, N11, N13) — *correction:* that lists 9; see ranking. **Killed: 5** (N6, N7, N8, N12, N14).

> Reconciliation: 14 generated − 5 killed = **9 survivors**. N9 and N10 survive but are explicitly *low-priority* (thin moat /
> overfit-prone). The headline count is **9 survivors, 5 of them genuinely high-leverage** (N1, N5, N11, N13, N4).

---

## Ranked v2 slate (survivors)

Ranked by leverage = (mechanism strength × moat-fit × feasibility/cheapness × novelty), penalising data-walls and cost-walls.

| Rank | # | Hypothesis | Why it ranks here | edge_fit | Smallest <1-day kill experiment |
|------|---|------------|-------------------|----------|----------------------------------|
| **🥇 1** | **N1** | **UMA pre-settlement convergence** | Cleanest PIT story, data already parsed, near-tautological mechanism, reg-grey/oracle-watching moat. The one real risk (window-too-short-to-fill) is *exactly* what a cheap offline study measures. | 5 | Backfill closed markets; for each, find the UMA-proposal timestamp + the CLOB quote inside the liveness window; measure realised return-to-$1 from that quote **net of category fee**. Pool ≥30 per category. Kill if the about-to-win leg already quotes ≥0.99 inside the window (no discount to capture) or net < fee. |
| **🥈 2** | **N5** | **Token-unlock supply-shock drift** | Leak-proof dated event, zero existing code, pure small-cap forced-flow moat. Highest novelty. | 5 | Pull DefiLlama `/unlocks`; event-study forward returns in the [−7d, +7d] window around every >5%-of-float unlock, by cap-tier, vs a **random-date placebo** in the same token. Kill if drift ≈ placebo or N<30. |
| **🥉 3** | **N11** | **Attention-acceleration breakout** | The PIT-clean redemption of the killed social lane — immutable sources, the exact cheap-social/small-cap moat, trades *acceleration* not level. | 4 | Compute Wikipedia + Trends 2nd-derivative z per small-cap; event-study forward return on onset crossings vs a **placebo-token null**. Kill if it survives the placebo (= just small-cap beta) or N<30. |
| **4** | **N13** | **Delisted-survivorship reversion** | Pure segmentation moat on already-built data; the open question (post-delist liquidity) is itself the cheap first test. | 4 | From `universe_pairs` delisted calendar, event-study the forced-sell overshoot + reversion on the surviving venue, controlling for the small-cap drawdown of the period. Kill if overshoot doesn't revert or fillable depth ≈ 0. |
| **5** | **N4** | **Bridge net-inflow → native token** | Real exogenous-flow mechanism, but it *echoes H7's beta-trap* — only credible if the placebo-chain null is clean. | 4 | DefiLlama `/bridges` per chain; 7–14d net-inflow tercile → forward native-token return vs **placebo-chain null** (the H7 disconfirmer). Kill if it survives placebo (= chain beta) or N<30. |
| **6** | **N3** | **PM-dispersion → BTC vol forecast** | Published external prior, PIT-clean, but a vol-timing overlay not standalone alpha. | 4 | Regress BTC 3–5d realised vol on macro-PM `|Δprob|` z; require positive, OOS-stable, and a lead-lag *asymmetry* (effect at +3d ≫ −3d). Kill if symmetric (non-causal) or OOS-flat. |
| **7** | **N2** | **Cross-market coherence** | Genuinely novel structure, but manual link-mapping + thin niche fills cap the leverage. | 4 | Hand-map ~10 superset/subset Polymarket pairs; measure violation frequency + post-violation re-coherence net of 2% fee. Kill if violations < 30 or fills ≈ 0. |
| **8** | **N9** | **ETF-flow → spot drift** | Cheap to test but expect-it's-priced; thin moat. | 3 | Lead-lag regression of next-day spot return on ETF net-flow tercile, with the +1/−1 day asymmetry test. Kill if coincident (symmetric) or net<fee. |
| **9** | **N10** | **Equity-theme → crypto-theme lead-lag** | Real cross-market structure but overfit-prone; lowest priority. | 3 | Pre-register 2–3 theme baskets; lead-lag regression SMH→AI-token-basket. Kill if no asymmetry or fails on a held-out theme. |

---

## Test FIRST — N1: UMA pre-settlement convergence

**Why N1 over N5 (the close #2):**

1. **Lowest data-build cost of any survivor.** The UMA resolution fields are *already parsed* in `polymarket.py`
   (`umaResolutionStatus`, `resolvedTime`, the settlement join from #393). N1 spends **zero of its first day building an
   endpoint** — it reads closed markets we can already fetch and replays the liveness-window quote. (Contrast N5/N11/N4,
   whose first day wires a new DefiLlama/attention endpoint *just to find out if the signal exists*.)
2. **Cleanest PIT story in the whole batch.** The proposal block-time is an on-chain, immutable, knowable-the-instant-it-
   happens marker. There is *no revising-source risk* (the LunarCrush trap), *no answer-key leakage* (unlike the weather
   reanalysis), and *no manual mapping* (unlike N2). The leakage tripwire that killed prior rounds simply has no purchase
   here.
3. **The mechanism is near-tautological, so a positive result is high-confidence — and the single failure mode is exactly
   what the cheap test measures.** The only way N1 dies is if the about-to-win leg *already* quotes ≥0.99 inside the
   liveness window (retail isn't actually slow / arbs already close it) — which the offline study reads off directly from
   the CLOB path, in <1 day, with no code debt.
4. **Maximum moat-fit (5).** This is oracle-watching, not latency — a 2-hour window is *slow* by HFT standards but invisible
   to retail who don't watch UMA. It's the purest expression of the edge thesis in the batch: a reg-grey, no-desk,
   structural-latency edge the giants ignore because it needs *attention to a niche mechanism*, not speed.

**Pre-registered kill criteria for N1:** (i) ≥30 resolving markets per fee-category with a tradeable in-window quote;
(ii) the about-to-win leg quotes ≤0.97 inside the liveness window often enough to capture a discount; (iii) realised
return-to-$1 from that quote beats the category fee (geo 0% / sports 3%) on a *single pre-registered* entry rule. If any
fails → killed in <1 day, no prod impact → fall through to **N5** (token unlocks), the highest-novelty survivor.

---

*Zero production impact. No Gate constant touched, no money path written, no source ingested. This is a research backlog
document. To promote any survivor, run its <1-day offline kill experiment first; only a passing offline study earns a
typed spec through the locked BRUT Gate.*
