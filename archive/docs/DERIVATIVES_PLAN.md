# Cosmu — Derivatives + Dynamic-Fees Plan (the lucrative track)

> **The operating plan to make Cosmu actually lucrative**, without changing the vision (internal, autonomous, profit-only money machine; buy-not-build; agentic-first; not a tool we sell). It re-points the machine from a long-only spot bot — which is structurally long crypto beta and uncompoundable — to a **market-neutral perpetual-futures carry + long/short engine**, harvested honestly with a **smart, account-specific, point-in-time dynamic-fee engine**. Grounded in a full code scan (2026-06-03) and venue/tax research. **France-only for now; UAE kept as a portable future switch, not a relocation in this plan.** This doc plans; it does not authorise any code change or live capital. Tax/venue notes are landscape, not advice.

---

## 0. Locked decisions (this cycle)

- **Jurisdiction = France only (UAE deferred but kept in mind).** Build + prove + go live in **France**, on a MiFID-legal venue (OKX X-Perps / Kraken Futures, 2:1). **No relocation in this plan.** Keep the build **jurisdiction-portable** — venue, leverage cap, and fees are catalog/config facts, never hardcoded — so adding **UAE later is a config switch, not a rewrite**. The FR ceiling we accept for now: **2:1 retail leverage + ~30–62% tax** (an autonomous HFT system risks "professional" reclassification). UAE (0% tax, 5:1, all venues) stays the documented pressure-release valve if those bind.
- **First instrument = perpetual futures.** Shorting + funding carry + market-neutral + ~3× faster paper convergence + ccxt-easy. Dated futures = Phase 2. **Options = deferred** (Phase 3, Deribit) — high ceiling, heavy build, not fast iteration.
- **Capital posture = small + conservative.** ~$1–5k, ≤2× leverage. In Phase 0/1 **absolute profit is secondary to validation** — prove the edge and the live mechanics first.
- **Deliverable = this doc.** Owner drives the build (no fan-out / specs generated this pass).

**Non-negotiables (never violate):** gate + money path stay deterministic, out of any LLM reach · LLM proposes, never disposes · no magic numbers (params fit; policy/risk constants are not strategy params) · point-in-time, no look-ahead (now including **fees**) · live OFF behind the interlocks · never display synthetic data · generated TS from OpenAPI only · ask first on schema/spend/live/broad-rename.

---

## 1. Why this is the lucrative move (the thesis in one screen)

Today the engine is **spot-only, long-only** — confirmed in the type system, not just the docs ([core/interfaces.py](../apps/engine/cosmu/core/interfaces.py): `Order/Instrument/Position` have no leverage/funding/short fields; [strategy/spec.py] setups are hardcoded "Upside-only"). That forces three losses: returns ≈ "did BTC go up" (beta, not alpha); 50–80% drawdowns (**uncompoundable**); and the funding-contrarian + cross-sectional-momentum thesis we actually want is **untradeable** without shorts.

**Profit equation — attack every term:**

```
Net profit ≈ Capital × Leverage × Σ(edge × freq) × (1 − cost) × uptime − drawdown − TAX
                         │                │                │                    │        │
                    2:1 FR now         carry +         smart dynamic        neutral   ~30–62% FR now
                    (5:1 UAE later)    neutral mom.    fees + routing       = low DD  (0% UAE later)
```

- **Two of the biggest multipliers — leverage and tax — are jurisdiction, not code.** Staying in France caps both (2:1; ~30–62% tax). UAE later would be ≈ **2.6× kept profit** (FR-pro ~62% → 0%) — the size of the prize we're deferring, and exactly why the build stays portable.
- **Market-neutral is also a research-velocity unlock:** killing the beta variance term tightens the t-stat by √(variance reduction) → significance in **~80 vs ~200 days** for the same edge. Faster paper = faster iteration to live.
- **Funding carry** (long spot / short perp) is a **documented risk premium** (BIS WP 1087), uncorrelated to BTC direction, small-and-shrinking but real, and **beneath institutional notice** — our capacity niche. The most-likely-real edge in the whole system.

---

## 2. Verified starting state (what's ready vs missing, ground-truthed)

**Ready (reuse, don't rebuild):**
- **Point-in-time store + daily ingest cron is proven on funding rates** ([data/altdata.py] `FundingRateProvider`, `PgAltDataStore.read_asof`, [ingest/run.py] `run_once`). Adding a daily **`venue_fees`** series is the *same pattern*.
- **`run_strategy_backtest(...)` is a pure, ~100ms/symbol function** ([data/backtest.py]) taking `fee_bps, slippage_bps, impact_bps, size_multiplier` → a **cost-surface scenario matrix is cheap** (~750 cells ≈ 6 min/strategy).
- **Capacity-aware slippage already modeled**: `slip = base_slip + impact·√(notional/quote_volume)` ([data/backtest.py]).
- **Deterministic gate, FDR, drift/decay monitor, 5-interlock live path, Slack webhook + Binance keys** present (`.env.local`: Binance real+testnet, xAI, FRED, Polymarket, OpenRouter, Slack, DB).
- **`ccxt` is a (soft) dependency**; `fetchTradingFees` / `fetchFundingRate(s)` available and currently unused.

**Missing (the build):**
- Derivatives in the data model: leverage, funding, liquidation, signed/short qty, expiry — none exist ([core/interfaces.py]).
- Short entries in the spec DSL ([strategy/spec.py] is "Upside-only").
- **Smart dynamic fees:** fees are static catalog constants ([spine/venue.py]); the gate uses one hardcoded `_FEE` ([research/gate.py:43]); the cost model has a single swap chokepoint ([execution/costopt.py] `FeeSchedule.from_venue`).
- Two-leg (market-neutral) paper marking: marking is single-leg spot ([master/portfolio.py] `mark_to_market`, [orchestrator/loop.py] `mark_tracks`).
- Perp/derivatives risk: margin, liquidation distance, short parity (the martingale ban must not block legit shorts), funding-flip unwind, basis-gap stop ([master/risk.py] `validate_order_full`).
- **A FR-legal perp venue account.** Our only configured venue, **Binance, is geoblocked for FR-retail derivatives** → need **OKX or Kraken Futures** keys.

---

## 3. Two tracks (run in parallel, decoupled)

**Build track** — perps → smart dynamic fees → cost-surface → two-leg neutral marking → meta-labeling. Jurisdiction-independent; runs in SIM on free data.

**Jurisdiction track (France)** — FR-legal venue account (OKX/Kraken) → live-small in France (2:1) → modest scale within FR limits. **UAE is an optional future switch (kept portable), not part of this plan.** Gates **scale**, not the build.

---

## 4. Roadmap by phase

Tags: *scope · cloud/local · model tier · worktree/PR*. Model tiers (house rule): **Opus** = money-path/gate/risk · **Sonnet** = adapters/wiring/tests · **Haiku** = scrape/summarize.

### Phase 0 — Prove carry/neutral in SIM (no live money). **The immediate work.**

Goal: answer **"does a real, net-of-cost, market-neutral edge exist?"** on real data — the #1 gating risk — using the most-likely-real edge (funding carry) with the fastest clock (neutral).

- **P0.1 Derivatives data model** — add `product_type` (spot|perp|future|option), `funding`, `max_leverage`, signed/short qty, `liquidation_price`, `funding_accrued` to `Order/Instrument/Position`. *engine · local · opus · PR*
- **P0.2 Short side in the backtest + spec DSL** — allow `direction ∈ {-1,0,+1}`; funding accrual as P&L; lift the long-only assumption ([data/backtest.py], [strategy/spec.py]). *engine · cloud · opus · worktree · PR*
- **P0.3 Funding-as-P&L + two-leg delta-neutral track** — long spot / short perp; mark both legs + accrue funding (new `master/neutral.py`; extend [master/portfolio.py]). *engine · cloud · opus · worktree · PR*
- **P0.4 Smart dynamic fee engine** — §5 below (co-built; carry can't be priced without it). *engine · cloud · sonnet · worktree · PR*
- **P0.5 Carry + neutral-momentum StrategySpecs** — funding-carry (long spot/short perp on positive funding, unwind on flip) + cross-sectional long/short momentum. Author via `create-strategy`/inbox. *engine · cloud · sonnet · PR*
- **P0.6 Run the Gate on REAL data** — ablation: neutral-carry vs price-only vs buy-and-hold, net of real fees+funding+slippage, ≥2 regimes, DSR/PBO/FDR. *engine · cloud · opus · PR*

**Phase 0 GATE (go/no-go):** carry and/or neutral-momentum **PASS on real data**, net of all costs, across ≥2 regimes, with `cost_ratio` healthy (net edge not a thin sliver of gross). → proceed to Phase 1.
**Kill:** no real PASS after honest attempts → thesis falsified cheaply; pivot (different edge family, or stop). **Pre-commit this in writing before running P0.6.**

### Phase 1 — Live-small in France, legally.

- **P1.1 OKX X-Perps or Kraken Futures execution adapter** (ccxt `defaultType:"future"`/`krakenfutures`); idempotent on `client_order_id`; testnet-first. *engine · cloud · sonnet · worktree · PR*
- **P1.2 Perp/margin risk** — leverage cap (≤2× FR), liquidation-distance buffer, funding-flip auto-unwind, basis-gap stop, short parity ([master/risk.py]). *engine · cloud · opus · worktree · PR*
- **P1.3 Slack alerting** (webhook already in env) — live order, daily-loss trip, regime block, reconcile mismatch, funding flip, fee-model drift. *engine · local · sonnet · PR*
- **P1.4 First live trade** — one neutral pair, ~$1–5k, ≤2×, your click via the modal. Smoke-test fills/slippage/funding accrual; reconcile live ≈ sim. *operator action*

**Phase 1 GATE:** live ≈ sim (slippage within tolerance, funding accrues as modeled), no surprise tail. → eligible to scale.

### Phase 2 — Scale in France (UAE optional, later).

Stay in France; deepen the edge within FR limits (2:1, MiFID venues). **No relocation in this plan** — but every task stays jurisdiction-portable so UAE is a later config switch.

- **P2.1 Multi-venue funding spread** — add OKX/Bybit (+ Hyperliquid only if you accept its KYC-free/legally-gray status for FR retail); normalize funding intervals (8h/4h/1h → annualized); route to richest net carry. *engine · cloud · sonnet · worktree · PR*
- **P2.2 Kelly-aware sizing on the neutral book** (low vol → size up; the compounding lever, within the 2:1 cap). *engine · cloud · opus · PR*
- **P2.3 Dated futures** — expiry/roll, calendar/basis edges (lift `delisted_at`-as-expiry; roll logic in [master/execution.py]). *engine · cloud · opus · worktree · PR*
- **P2.4 Meta-labeling** — deterministic entry filter extending [ml/survival.py] ("trade only high-conviction"); stays inside the gate-passed envelope, ML not LLM. *engine · cloud · opus · worktree · PR*
- *(optional, deferred) UAE switch* — if FR tax/leverage bind, relocate (UAE residency + TRC; sever FR centre-of-economic-interests) to unlock 5:1 + 0% + all venues. *operator action — not scheduled*

**Phase 2 GATE:** market-neutral Sharpe with **corr-to-BTC ≈ 0**, real net annualized yield, small drawdown, edge half-life > deploy time.

### Phase 3 — Options engine (Deribit). **Deferred.**

Vol-risk-premium selling as a second uncorrelated book. HIGH build (IV surface + Greeks + margin + Deribit adapter). **Gate behind a proven perp book** — do not let it block perps. Note Deribit is legally gray for EU retail (not MiFID-licensed) — revisit under UAE if/when that switch happens.

---

## 5. Smart dynamic-fee engine + cost-surface (spec)

**Principle: price every trade at the fee the venue would *actually* charge *this account* right now — never a hardcoded guess — and reconcile predicted vs realized so the model self-corrects.** This is the "fetch fees dynamically, smart" ask, plus the per-strategy×venue×asset cost surface (the "déclinaisons").

**A. Fetch the account-specific schedule, not the brochure.** ccxt `fetchTradingFees` returns *this account's* maker/taker (already reflecting VIP tier + BNB/token discount + promos) per symbol; `fetchFundingRate(s)` for perps. Authenticated where keys exist; **fallback ladder**: account fee → published `describe().fees` → static catalog. Never crash; degrade gracefully (the house pattern).

**B. Per venue × symbol × instrument_type.** Spot ≠ perp ≠ dated; some symbols differ. **Funding (perps) is the dominant "fee" on a carry book** — fetched and stored as a first-class cost, not an afterthought.

**C. Point-in-time, append-only.** Each snapshot stamped `available_at` → backtests read the fee **in effect at each historical bar** (no fee look-ahead). Same proven `read_asof` path as funding rates.

**D. Smart refresh cadence (cheap, rate-limit-aware).** Fees barely move → a daily cron snapshot is the baseline. Refresh *also* on: (i) trailing-30d volume crossing a tier threshold, (ii) after a batch of fills, (iii) a venue fee-change. Cache between — one call/venue/day baseline, not per-trade hammering.

**E. Tier anticipation = a profit lever.** Track trailing-30d volume; surface "X more volume → next tier (−n bps)." More volume → cheaper fills → more strategies clear net-of-cost. This is real money, not cosmetics.

**F. Predicted vs realized reconciliation (the smart loop).** Capture `fill.fee` (already on the `Fill` dataclass) at execution; compare to the predicted fee; **log drift + Slack-alert if it diverges**; feed realized fees into per-strategy ROI + `cost_ratio`. Backtests use *predicted* PIT fees; live attribution uses *realized*. Extend the existing `reconcile_fills` in [master/execution.py].

**G. Effective-cost model, not just a number.** Effective cost = maker/taker × fill-type (the existing `choose_order` maker/taker router in [execution/costopt.py]) + funding accrual (perps) + rebates (maker can be **negative** — a rebate you earn). Wire the dynamic schedule into `choose_order` so routing uses *live* fees, and prefer maker fills where fill-probability allows.

**H. Cost surface (the "déclinaisons").** Run the pure `run_strategy_backtest` across **{venue × asset × fee-tier(volume) × maker/taker × leverage × funding-regime × slippage/impact}** → per-cell `{net_return, sharpe, cost_ratio, breakeven_edge}`, stored as `cost_surface_json` (post-gate pass in [lab/finder.py], ~6 min/strategy). Drives **routing** (best net venue×asset at our real tier) and a **fragility flag** (breakeven within a slippage-doubling → down-rank/kill).

**I. `cost_ratio` (= net/gross edge) as a first-class gate metric** in `BacktestMetrics` ([master/scorer.py]) — cheap-but-real edges beat fragile high-gross ones.

**J. Normalize funding across venues** (8h Binance/OKX · 4h Kraken · 1h Hyperliquid → annualized) for apples-to-apples routing + the multi-venue spread.

**Seams:** new provider in [data/altdata.py] (mirror `FundingRateProvider`) → wire into [ingest/run.py] `run_once` → swap the hardcoded `_FEE` ([research/gate.py:43]) + the static lookup ([execution/costopt.py], [master/execution.py] chokepoint) to `read_asof` → extend `reconcile_fills` for the realized-vs-predicted loop.

---

## 6. Derivatives data-model changes (concrete seams)

| Concern | File | Change | Effort |
|---|---|---|---|
| Instrument | [core/interfaces.py] | `product_type`, `is_inverse`, `funding`, `max_leverage`, `maintenance_margin_pct`, `expiry_ts` | small |
| Order | [core/interfaces.py] | `leverage:int=1`, `reduce_only:bool=False` | small |
| Position | [core/interfaces.py] | signed/short qty, `liquidation_price`, `funding_accrued` | small |
| Spec DSL | [strategy/spec.py] | short entries (`direction ∈ {-1,0,+1}`) | medium |
| Backtest | [data/backtest.py] | short side + funding accrual in `_book()`; fee from PIT `venue_fees` | medium |
| Perp adapter | new `adapters/exec/okx.py` / `krakenfutures.py` | ccxt `defaultType:"future"`; signed positions, funding realizations, liq price | medium |
| Risk | [master/risk.py] | leverage cap, margin/liquidation buffer, short parity (don't block legit shorts), funding-flip unwind, basis-gap stop | medium |
| Two-leg marking | new `master/neutral.py` + [master/portfolio.py] + [orchestrator/loop.py] | pair legs, mark both, accrue funding | medium |
| Smart dynamic fees | [data/altdata.py] + [ingest/run.py] + [research/gate.py] + [execution/costopt.py] + [master/execution.py] | `venue_fees` PIT series + read-asof swap + realized reconciliation | small–medium |

---

## 7. Risk flags (carry-forward into every phase)

- **Carry has negative skew** — steady gains, rare violent losses (funding flip / liquidation cascade / basis gap). Auto-unwind on flip, liquidation buffer, basis-gap stop, **don't over-lever**. The drift monitor is the rotation tool.
- **ESMA 2:1 cap (Feb 2026)** — EU "regulated perps" may be reclassified as CFDs at 2:1 (unresolved). We accept this for now; small + conservative sizing matches the posture.
- **France HFT → "professional" tax reclassification** — an autonomous algorithmic system is the textbook trigger for BNC (~45% + 17.2% social); the 30% flat tax is optimistic for this activity. Mitigate while in FR: small size, lean on crypto-to-crypto deferral (tax only on fiat off-ramp), get written counsel. If it bites, **UAE is the documented exit** (deferred, not scheduled). *(Landscape, not advice.)*
- **Binance is geoblocked for FR-retail derivatives** — live perps in France must run on OKX/Kraken.
- **Options ≠ fast** — keep deferred; don't let the high ceiling pull off the perps-first path.
- **Keep gate-first** — Phase 0 must PASS on real data or be documented as a FAIL. No live capital before that.

---

## 8. Go/No-Go & criteria

**Validation (deserve more time/capital):** real-data Gate PASS on carry/neutral net of costs across ≥2 regimes · `cost_ratio` healthy · corr-to-BTC ≈ 0 · live ≈ sim on the smoke test · edge half-life > deploy time.

**Kill:** no real PASS after honest attempts · net edge a thin sliver of gross (fragile) · live slippage/funding erases the SIM edge · edge decays faster than it can be deployed · temptation to go live on synthetic/surrogate numbers.

---

## 9. Accounts / keys to set up (owner)

- **FR-legal perp venue:** open **OKX (X-Perps)** *or* **Kraken Futures** (MiFID-legal for FR retail) → API key+secret to Railway env when going live. *(Binance derivatives blocked in FR.)*
- **Already wired** (`.env.local`): Binance (spot data), xAI/Grok, FRED, Polymarket, OpenRouter, **Slack webhook** (alerting = quick win), DB.
- **UAE (optional, later — not in this plan):** if/when FR tax or leverage binds, UAE residency + TRC unlocks 5:1 + 0% + all venues (incl. legal Deribit options). Kept as a config switch; no action now.
- **Keys policy unchanged:** live keys server-side in Railway env only; UI shows a `configured` boolean; spot/withdrawal-disabled + IP-allowlisted sub-account before any live key.

---

## 10. Immediate next action

Build **Phase 0** (perp-carry SIM harness + smart dynamic-fee/cost-surface), then run **P0.6 — the real-data Gate** with kill/keep criteria written down first. Everything lucrative is gated on that one PASS. No live money, no relocation needed to learn the answer.
