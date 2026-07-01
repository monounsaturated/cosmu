# Crypto cash-and-carry / basis carry — capturing perp funding vs spot — 2026-07-01

**Question:** Can COSMU (a solo, FR-resident, unregulated quant) capture crypto perpetual **funding** as a
delta-neutral yield — long spot / short perp (or the reverse) on Kraken / Hyperliquid — net of real fees, and
does it survive the LOCKED per-combo Gate?

## Verdict: **LATER (conditional)** — build the harness now ($0, offline), do NOT arm live yet

This is the **least-dead** direction COSMU has surfaced. Unlike every killed lens (astro, funding-*direction*,
Polymarket wedges, public-price crypto), basis carry is not a fragile directional *alpha* that decays under a
proper null — it is a **structural positive-carry harvest** with a mechanical reason to exist (a funding
formula with a built-in interest-rate floor + a persistent long-leverage bias). The data is **free, PIT-clean,
immutable, and already backfilled** in this repo. The mechanics are **~80% built** (`master/neutral.py` accrues
long-spot/short-perp funding; `research/perp_market_neutral.py` has the Gate plumbing).

It is **LATER, not NOW**, for three honest reasons — the same "edges are real but live where fillability/cost/
decay kill them" pattern, here with the killer being **venue legality**, not fill:

1. **No clean FR-legal venue for the short-perp leg.** The spot leg is fine (Kraken spot = MiCA-legal). The
   *short-perp* leg is the problem: Kraken Futures is **ESMA/MiFID-restricted for EEA retail** (this repo already
   flags it `live_enabled=False`), IBKR has **no crypto perps**, and **Hyperliquid** — the only venue that
   technically works — is **unauthorised in the EEA**, and the **MiCA transitional window closes today
   (1 July 2026)**, tightening exactly the gray zone a solo would be relying on.
2. **Net-of-cost carry is thin and unproven against the right hurdle.** The honest BTC/ETH carry sits near the
   ~11%/yr funding *floor*, heavily compressed by Ethena-scale basis desks; after round-trip fees and the
   forced-exit decay it must beat the **T-bill opportunity cost (~4–5%)**, not zero. Whether it clears the
   Gate on real history is an *unrun* experiment — there is no single-instrument cash-and-carry arm gated yet.
3. **The short leg is SIM-able today at zero venue/legal risk** (a market-neutral SIM track needs no live venue),
   so the correct sequence is: **prove the net carry through the Gate first, resolve the venue second.**

**Do now (all $0, offline, PIT-clean):** build a *single-instrument* cash-and-carry research arm (long spot +
short perp, **same asset**) that routes through the existing deterministic Gate with real venue fees + real
funding + an honest exit assumption, on the funding history already in the store. **Do not** open a live short-perp
venue or arm capital until (a) it clears the deploy bar beating the T-bill hurdle, and (b) the operator makes an
explicit, documented call on the Hyperliquid legality/counterparty gamble.

---

## 1. What this is — and what it is NOT (do not re-litigate the killed work)

Cash-and-carry / basis carry = hold **two offsetting legs on the same asset** so price cancels and the P&L is the
**funding cash flow** (± the basis move at entry/exit):

- **Funding positive (the usual regime):** long-spot + **short-perp** → the short perp *receives* funding. Income.
- **Funding negative (reverse cash-and-carry):** short-spot + **long-perp** → the long perp *receives* funding.

This is **distinct** from three things COSMU has already tested or built — do not conflate them:

| Prior COSMU work | What it did | Status |
|---|---|---|
| **funding-contrarian** (`research/funding_contrarian/`, RESEARCH_PREVIEW row 2026-06-15) | funding-*z* as a **directional** predictor of price | **KILLED** — OOS 0.63 but DSR~0.10; funding-z is *causal* but too weak to trade *directionally* |
| **perp_market_neutral** cross-sectional L/S | rank the perp universe, **long top / short bottom** perps (both legs perps) — momentum & a **cross-sectional** carry spread | Deploy-lane SIM track; **not** spot-vs-perp basis |
| **`master/neutral.py`** | marks a long-spot/short-perp pair, accrues funding into `Position.funding_accrued` | The **mechanics** of cash-and-carry — but **nothing routes a cash-and-carry book through the Gate** |

The gap this research points at: **a single-instrument long-spot/short-perp carry book, gated.** The reason it is
worth building even though funding-*direction* failed: cash-and-carry does **not predict price**. It harvests a
cash flow the perp *pays by construction*. RESEARCH_PREVIEW already concedes "funding-z is GENUINELY CAUSAL
(lead-lag asymmetric, unlike astro's symmetric artifact)" — that causality is exactly why the **carry** (not the
direction) is a real thing to capture.

## 2. The edge thesis — why funding is structurally positive

Funding exists to tether the perp to spot. On Binance the mechanism is explicit:

> `Funding = Premium Index + clamp(Interest Rate − Premium Index, −0.05%, +0.05%)`, with the **Interest Rate fixed
> at 0.01% per 8h (≈0.03%/day ≈ 11.6%/yr) for BTC/ETH.**

Two structural forces make the payment land on the **short** more often than not:

1. **A built-in interest-rate floor.** Absent any premium, funding defaults to +0.01%/8h. That is a *subsidy to
   the short* baked into the contract, not a market view.
2. **Persistent long-leverage bias.** Crypto perps are the retail leverage instrument; speculators are structurally
   long and *pay up* to be long. Empirically funding is **positive > 92% of the time** (Q3 2025); BTC sat at the
   0.01% floor ~78% of the period, ETH ~88%. Jan-2026 BTC funding averaged **+0.51%/8h (≈70% APR)** in a euphoric
   window — the fat tail, not the base rate.

The honest read: the **base rate is the ~11%/yr floor**, with occasional multi-week spikes to 20–70%+ APR during
euphoria (and negative spikes during deleveraging). A carry harvester earns the floor most of the time and the
spikes rarely — *if* it can hold through the flips.

## 3. Why a small solo can capture what desks compress (the honest version)

The BTC/ETH majors' basis is **heavily arbitraged** — Ethena alone runs a multi-billion delta-neutral book that
*is* the compression; professional delta-neutral desks reported **~19% in 2025, explicitly "compression from
earlier periods."** So a solo will **not** out-compete desks on the deep, liquid majors. The defensible edges for a
small account are narrower and real:

- **Opportunity-cost asymmetry.** A desk needs to clear a ~15%+ cost-of-capital; a compressed 6–9% net carry is
  "not worth the balance sheet" for them but is **positive EV against a solo's T-bill alternative (~4–5%)**. The
  solo's hurdle is genuinely lower — that is the whole edge, and it is small.
- **Capacity-constrained tail.** The fat funding lives in **smaller-cap perps and transient spikes** that desks
  can't scale into without moving the rate. A solo's $100–$1k clip is invisible there (see §7) — but that tail is
  *also* where liquidation and slippage risk on the short leg are worst (§8). The tail is real and dangerous, not
  free money.
- **No size decay on the carry itself.** Funding is paid **pro-rata on notional**; there is no size-based haircut.
  Unlike a spread/latency edge that a solo loses by being slow, the carry pays a $100 short the same rate as a
  $100M short. This is the one COSMU edge where *small* is not a disadvantage.

**Verdict on the thesis:** real but *modest*. Frame it as **"harvest the funding floor net of the T-bill hurdle,"
not "beat the desks."** The Gate — beat-buy&hold replaced here by beat-cash / beat-T-bills — is exactly the right
converter.

## 4. Free PIT funding data — the honest, immutable, already-wired path

Funding data is **$0, keyless, and PIT-honest** — it satisfies the repo's own predictability rule (RESEARCH_LESSONS
§4: *"funding (Binance settlement)"* is named an **immutable** source: the backfilled value = the live value, no
revision, no look-ahead). This is the cleanest data class COSMU has.

| Source | Endpoint | Key? | In repo today |
|---|---|---|---|
| **Binance USDⓈ-M** | `GET fapi/v1/fundingRate` (paginated, settled 8h) | **No key** | ✅ `scripts/backfill_funding.py` → append-only PIT store (top-20 perps, ≥1yr); `data.altdata.BinanceFundingHistoryProvider` |
| **Hyperliquid** | `POST /info {"type":"fundingHistory","coin","startTime"}` (hourly funding) | **No key** | ✅ `scripts/ingest_hyperliquid_bars.py`; funding provider path exists |
| **Kraken Futures** | funding-rate API (data only — **legal to READ, restricted to TRADE** for EEA retail) | **No key** | ✅ `ingest/run.py` `KrakenFuturesFundingRateProvider`, `KRAKEN_FUTURES_UNIVERSE` |
| **OKX** | funding provider | No key | ✅ `test_okx_funding_provider.py` |

The join is already correct: `data.backtest.sum_funding_per_bar` sums **every real settlement** inside a held bar
(PIT: `available_at <= bar.ts`), and `master/neutral.py` applies the sign convention (long perp pays +rate, short
receives). **A cash-and-carry backtest can run offline today on data already in the store.** The one honest gap:
funding history is deep, but a spot-vs-perp *basis* series (perp mark − spot index at entry/exit) needs the paired
spot bars — those exist for the majors; the tail is thinner.

## 5. The economics — honest net-of-cost math (this is where it gets thin)

Carry is a **multi-week HOLD**, not a churn. The math that decides everything:

**Gross carry (base rate):** ~0.03%/day (11%/yr) on BTC/ETH at the floor; a euphoric window multiplies it.

**Round-trip cost, both legs (entry + exit):**

| Construction | Entry+exit cost (taker) | Break-even hold @ 0.03%/day |
|---|---|---|
| Cross-venue: Kraken spot (0.25–0.40%/side) + Hyperliquid perp (0.045%/side) | ~**0.6–0.9%** | **~20–30 days** |
| Single-venue Hyperliquid: spot (0.07%/side) + perp (0.045%/side) | ~**0.23%** | **~8 days** |
| Single-venue Hyperliquid, **maker** (post-only): spot 0.04% + perp 0.015%/side | ~**0.11%** | **~4 days** (but fills not guaranteed → leg-in risk) |

Two conclusions fall out of that table:

- **Single-venue beats cross-venue decisively.** Doing long-spot + short-perp on **one** venue (Hyperliquid has
  both) roughly thirds the fee drag, cross-margins the two legs (one liquidation engine sees the hedge, so far
  less margin is stranded), and **eliminates cross-venue basis-blowout risk** (§8). The cost is that *all* capital
  then sits on one ~2-year-old venue (§8 counterparty).
- **The carry must survive the flips over a 1–4 week hold.** Simulation research on carry windows finds **forced
  exits in ~95% of opportunities** — funding mean-reverts / flips before the "natural" exit, and if you exit before
  the accrued carry has covered the round trip, the trade is **net-negative**. This decay — not the headline APY —
  is what the Gate must price. It is precisely why the deploy bar's *beats-cash + positive-holdout + deflated-Sharpe*
  construction is the right, un-foolable test.

## 6. The venue wall — the actual binding constraint (and a code discrepancy to fix)

The spot leg is legal; **the short-perp leg has no clean FR-legal home**:

| Short-perp venue | FR/EEA retail legality | Verdict |
|---|---|---|
| **Kraken Futures** | Crypto **derivatives** are **ESMA/MiFID-restricted** for EEA retail (perps are MiFID-II instruments, *not* covered by a MiCA licence). This repo: `kraken_futures` stays `live_enabled=False`; `settings.py:239` says "live Kraken from FR/EU retail is ESMA-restricted for derivatives." | ❌ legally blocked |
| **IBKR** | No crypto perpetuals product | ❌ not offered |
| **Hyperliquid** | No geo-block, no KYC, trades fine from the EU — but **unauthorised in the EEA**; regulators increasingly treat it as an unlicensed CASP / MiFID investment firm serving EU retail, and the **MiCA transition ends 1 July 2026 (today)** | ⚠️ works, legal gray, tightening now |

> **Code discrepancy to correct (decision-relevant):** `research/perp_market_neutral_arm.py:43` comments
> `VENUE = "kraken_futures"  # … (2/5 bps, FR-legal)`. That inline **"FR-legal" is wrong** — it contradicts both
> `settings.py:239` and `docs/research/broker-recommendation-2026-06-29.md` ("only crypto **derivatives** are
> ESMA-restricted — that's the separate `kraken_futures` venue which stays `live_enabled=False`"). The comment
> should read *ESMA-restricted for EEA retail; SIM/data only*. Left uncorrected, it could mislead a future arming
> decision into thinking a live FR short-perp venue exists when it does not.

**Net:** the short leg is `live_enabled=False` today for good reason, and there is **no drop-in FR-legal
replacement**. This is the wall — and it is a *jurisdiction* wall, not a market-microstructure one, which is why
it is the operator's call, not the Gate's.

## 7. Fillability at small size — the one tailwind

Uniquely among COSMU's explored edges, small size is an **advantage** here:

- **Min sizes are tiny:** Hyperliquid perp $10 notional / spot 10 quote units; Kraken crypto is natively
  fractional. A $100–$1k clip is trivially fillable.
- **BTC/ETH perps are the deepest books in crypto.** A four-figure order has **zero market impact** — the entry/
  exit slippage that kills a spread edge is negligible here.
- **The carry pays pro-rata on notional** — no size haircut (§3). A small book earns the *same rate* as a desk.

So "fillability at small size" — the killer in most COSMU lenses — is **not** the constraint for basis carry. The
constraints are venue-legality (§6), net-of-cost thinness (§5), and flip-decay (§5) — in that order.

## 8. Top risks (ranked by how likely each is to kill it)

1. **Venue legality for the short leg (FR/EEA)** — *binding.* No clean legal venue; Hyperliquid is unauthorised in
   the EEA with the MiCA transition closing today. A solo unregulated trader arming an unlicensed perp venue is a
   real compliance exposure, not a rounding error. **This decides go/no-go, and it is the operator's call.**
2. **Counterparty / venue risk on the short leg** — Hyperliquid is a ~2-year-old DEX (bridge, oracle, HLP vault).
   A bridge/oracle/vault failure loses the collateral behind **both** legs if single-venue. Delta-neutrality does
   **not** hedge venue insolvency — the classic "the hedge worked, the exchange didn't" failure.
3. **Funding-regime flip + forced exit** — funding reverts / goes negative after liquidation cascades or
   deleveraging; ~95% of carry windows force-exit before their natural exit. Exit before the accrued carry covers
   the round trip → net loss. Reflexive with Ethena-scale unwinds (a crowded-trade unwind arrives "without anyone
   doing anything wrong").
4. **Compression / crowding** — the majors' basis is arbitraged near the floor; the fat carry lives in the
   capacity-constrained tail (§3), which is *also* where liquidation/slippage risk is worst. Realistic net BTC/ETH
   carry is **single digits** and must clear the **T-bill hurdle**, not zero.
5. **Cost & basis-blowout at small size** — cross-venue doubles fees, splits capital, and adds cross-venue basis
   divergence that can eat the carry; the short leg's margin must be over-collateralised so a price spike doesn't
   liquidate the hedge (lowering effective APY). Single-venue removes most of this but concentrates risk #2.

## 9. Quant vs LLM

**Pure quant. Keep the LLM entirely out of the numeric path** — consistent with locked COSMU doctrine (LLM out of
numeric price reasoning; `perp_market_neutral.py` is deterministic-for-a-fixed-cache, zero LLM on the Gate path).

- **Quant owns everything that touches money:** the funding series (PIT), the fee model (venue catalog, not a
  magic number), the delta-neutral weights, the basis at entry/exit, the hold/exit decision, and the Gate. Funding
  capture is **arithmetic**, not judgment — the LLM would only add non-determinism and a look-ahead surface.
- **The only defensible LLM roles are non-numeric and out-of-band:** (a) a **risk tripwire** that reads exchange
  announcements / funding-formula changes / venue-solvency news and flags "re-examine," never sizing or timing the
  book; (b) drafting the **plain-language strategy summary** (`backfill-summaries` — advisory text the engine only
  stores). Both are advisory, both stay out of the sizing loop.

## 10. Data path & recommended sequence (all pre-live steps are $0 / offline)

1. **Build a single-instrument cash-and-carry arm** (`research/perp_basis_carry.py`), mirroring
   `perp_market_neutral.py`'s honesty contract: for each major (BTC/ETH first, then the liquid tail), construct a
   **long-spot + short-perp** book, accrue **real funding** (`sum_funding_per_bar`, already correct), charge
   **real round-trip fees** from the venue catalog for the chosen construction, and model an **honest exit** (exit
   on funding-flip / basis-blowout, not a look-ahead-perfect exit). Data is already in the store.
2. **Route it through the LOCKED Gate** with `require_beat_buy_and_hold=False` and a **beat-T-bills** hurdle (not
   beat-cash-at-0 — a carry book's fair benchmark is the risk-free rate it displaces), plus the deploy-lane
   deflated-Sharpe / positive-holdout floors already in `perp_market_neutral.validate()`. This answers the only
   question that matters — *does the net carry clear the bar over honest holds?* — with **zero venue exposure.**
3. **Fix the `perp_market_neutral_arm.py:43` "FR-legal" comment** (§6) so the venue reality is not misrepresented
   in code.
4. **Only if it clears the Gate:** escalate the **venue decision** to the operator — the Hyperliquid legality +
   counterparty gamble, single-venue vs cross-venue, and margin/over-collateralisation policy — via
   `AskUserQuestion`. Prefer **single-venue Hyperliquid** on fee/basis grounds *if* the operator accepts the
   counterparty + EEA-legal risk; otherwise it stays a **SIM track** (market-neutral, so SIM is faithful) until a
   MiFID-licensed EU crypto-perp venue exists.

**Bottom line:** the edge is real and structural, the data is free and honest, the machinery is mostly built, and
small size is a *tailwind* — but the short-perp leg has no FR-legal venue and the net carry is thin and unproven
against the T-bill hurdle. **Prove the carry through the Gate now (free, offline); do not arm live until it clears
AND the operator owns the venue call.**

---

### Sources
- Cash-and-carry mechanics, 2025 pro delta-neutral ~19% (compression), 5.4% conservative BTC example, Ethena/Kraken custody: https://www.buildix.trade/blog/cash-and-carry-crypto-delta-neutral-funding-rate-strategy-2026 · https://arbitragescanner.io/blog/crypto-funding-rate-arbitrage-guide · https://www.forbes.com/sites/digital-assets/2026/06/15/ethenas-usde-pays-yield-legally-and-the-genius-act-has-no-answer-for-it/
- Delta-neutral risks (funding-regime, basis-compression, liquidation, execution — "not risk-free"): https://blofin.com/en/academy/education/delta-neutral-crypto-strategies · https://arbping.com/blog/funding-rate-arbitrage-risks
- Ethena funding-risk, crowded-trade unwind / reflexivity, ~95% forced-exit: https://docs.ethena.fi/solution-overview/risks/funding-risk · https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield
- Funding positive >92% of time (Q3 2025), 0.01% floor frequency, exchange comparison: https://www.bitmex.com/blog/2025q3-derivatives-report · https://zipmex.com/blog/how-to-analyze-funding-rates-in-crypto/ · https://en.macromicro.me/charts/49213/bitcoin-perpetual-futures-funding-rate
- Binance funding formula (interest 0.01%/8h floor + premium + ±0.05% clamp): https://www.binance.com/en/support/faq/360033525031 · https://medium.com/derivadex/funding-rates-under-the-hood-352e6be83ab
- Hyperliquid funding-history API (keyless `POST /info fundingHistory`): https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals · https://www.quicknode.com/docs/hyperliquid/info-endpoints/fundingHistory
- Hyperliquid fees (perp 0.045%/0.015%, spot 0.07%/0.04%) + min sizes ($10 perp / 10 quote spot): https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees · https://www.datawallet.com/crypto/hyperliquid-fees-explained
- Hyperliquid EEA legal status / no geo-block / MiCA-July-1-2026 / perps = MiFID-II derivatives: https://fintelegram.com/defi-is-not-a-legal-black-hole-why-mica-already-reaches-axiom-hyperliquid-co-and-why-eu-regulators-are-still-looking-away/ · https://hyperdash.com/learn/mica-crypto-exchange-ban-europe-2026 · https://www.coinperps.com/learn/hyperliquid-restricted-countries
- Kraken MiCA spot vs ESMA-restricted derivatives (COSMU internal): docs/research/broker-recommendation-2026-06-29.md · apps/engine/cosmu/config/settings.py:239
</content>
</invoke>
