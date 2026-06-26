# Polymarket trading — end-to-end readiness assessment (2026-06-26)

**Scope:** READ-ONLY. One report. Answers the operator's three questions:
1. How ready is Polymarket trading / bots / combos?
2. Can he CREATE a Polymarket strategy in Claude Code in **natural language**?
3. Is the pipeline OK end-to-end (author → backtest → paper → live)?

**Mode:** code-verified, file-by-file. No code changed, no Gate constant touched, nothing armed, nothing merged. Isolated worktree on `origin/main` @ `7741c65` (the just-merged #393).

---

## Verdict (one line)

**Polymarket is ~85% wired as a first-class venue — author, paper, and live all work TODAY — but it is NOT yet honestly *backtestable* as a tradeable contract, because the one missing piece (the UMA resolution / `payoutNumerators` settlement join) means the backtest measures odds mean-reversion, not the real P&L a YES share earns at \$1/\$0.** Everything else (NL authoring, per-market odds data, the finder branch, the cost overlay, the CLOB execution adapter, the live routing, the maker order type) is built and merged. It is **wiring + one data join, not a separate big chantier.**

**Can he author a Polymarket strategy in NL today? → YES.** The keyword `polymarket` / `prediction` / `election` / `odds` / `probability` all route the brief to `asset_class=prediction, venue=polymarket` and produce a valid typed `StrategySpec`. It will paper-trade. What it will NOT do is produce a *trustworthy* backtest number, for the resolution-join reason above.

---

## Readiness table — per stage

| Stage | Status | What works | The exact gap |
|---|---|---|---|
| **Author (NL)** | 🟢 **READY** | `lab/author.py` maps `polymarket`/`prediction`/`election` → `("prediction","polymarket")` (`_ASSET_HINTS`), and `odds`/`probability`/`polymarket`/`prediction market` → `pm_implied_prob`/`pm_risk_on` (`_FEATURE_HINTS`). `features_for(["prediction"])` validates the pick. Output is a typed `StrategySpec` (`asset_classes=["prediction"]`, `venues=["polymarket"]`). A worked example already lives in the inbox: `g2-prediction-prob-overextension-fade-short.json`. | The NL→spec path produces a **price-asset-shaped** spec: `exit` uses `stop_loss`/`take_profit`/`time_stop` *fractions over the odds price*. There is no binary-contract exit semantics (settle to \$1/\$0 at resolution). The author cannot express "hold to resolution, pay the actual outcome." This is a spec-model + backtest gap, not an authoring-UX gap. |
| **Backtest** | 🟡 **PARTIAL — runs, but the number is not yet trustworthy** | The finder has a real prediction branch: `finder._prediction_symbols` → `screen_universe.prediction_markets` (top-30 liquid open conditionIds from `universe_pairs`) → `finder._prediction_bars` → `PredictionDataAdapter` reads the per-market `odds` series back as Bars whose OHLC **is** the probability in [0,1]. Each conditionId is one BRUT cell, priced at Polymarket's per-category fee via `build_cost_context`. | **TWO gaps.** (1) **No UMA resolution join** (Fix-B, deferred): `payoutNumerators` exists ONLY in the exec adapter; the research/backtest path never joins the resolved outcome, so a position held to resolution settles at the *last odds quote*, not the authoritative \$1/\$0 — the favorite-longshot edge it is hunting is *defined* by resolution and is therefore untestable (the spec's own Disconfirmer 2 can't run). (2) **Trade-frequency**: even with #393's hourly `odds_60` series now ingesting, the per-cell min-trades floor (`_BRUT_MIN_TRADES=30`) needs the hourly cadence to accumulate; daily (`odds`, ~1 trade/market) is correctly refused. |
| **Paper / forward** | 🟢 **READY (mechanically)** | The lifecycle (backtest → paper → live) is venue-agnostic. A prediction track opens a paper cell and the SIM executor (`master/execution.py`) steps it forward, charging the half-spread the adverse way at the real per-category Polymarket fee (0% geopolitics / 3% sports). `is_maker` and `order_type="maker"` exist on the core `Order`. | Paper P&L inherits the same backtest blind spot: a paper position held to resolution **also** has no authoritative settlement join, so a long-hold prediction track marks at the last quote, not the outcome. Fine for the *intraday-reversion-before-resolution* thesis (the live maker candidate), wrong for any *hold-to-resolution* thesis. |
| **Live (arm)** | 🟢 **READY (testnet-default, real-money interlocked)** | `adapters/exec/polymarket.py` is a complete `core.ExecutionAdapter`: submit/cancel/positions/fills, idempotent on `client_order_id`, EIP-712 signing via `py-clob-client` (`_polymarket_clob.py`, lazy import → absent lib stays disabled/paper). The exec registry routes `polymarket` (`registry.py:15,34`). The live step coerces a prediction order to a **limit** at the mark (`execution.py:260` — the CLOB has no market order), supports reduce-only, and cross-restart idempotency guards a venue with no native client-id index. `resolve_mode` mirrors Binance/Alpaca exactly: testnet key → testnet (Amoy fake funds, default); mainnet key honored ONLY when `live.mode=="real"` AND no testnet key; no key → disabled. Proxy-signer-without-funder refuses to arm (never wrong-wallet). | No code gap on the arm path itself. The remaining work is **operational**: set the keys (`POLYMARKET_TESTNET_PRIVATE_KEY` for testnet, or the mainnet key + funder for live), and human-click arm (live is human-only by design). The maker-feasibility study (#401) says the only plausibly-positive live edge is **geopolitics-only, 0% fee, mid-band, small passive size** — and even that needs a live fill log to confirm (queue position / partials / own-size impact are unknowable offline). |

Legend: 🟢 ready · 🟡 partial · 🔴 blocked.

---

## (2) What happens TODAY if he describes a Polymarket strategy in NL

Trace of a real brief, e.g. *"fade Polymarket contracts whose odds have spiked and are rolling over"*:

1. **Author** (`lab/author.py::draft_from_brief`): `_pick_asset` matches `polymarket` → `("prediction","polymarket")`; `spec.universe.asset_classes=["prediction"]`, `venues=["polymarket"]`. `_detect_features` matches `odds`/`probability` → `pm_implied_prob`. `validate_spec` passes (thresholds are ParamRefs, no magic numbers). **→ a valid typed StrategySpec is produced. WORKS.**
2. **Screen** (`finder._market` → `_prediction_symbols` → `screen_universe.prediction_markets`): because the spec declares `polymarket` + `prediction`, it pulls the top-30 liquid open conditionIds from `universe_pairs`. **Polymarket DOES appear in `universe_pairs`** (`venue_universe.fetch_polymarket`, keyed by `conditionId`, `asset_class="prediction"`, #313). **→ markets are found (assuming the universe table is populated in prod). WORKS.**
3. **Bars** (`finder._prediction_bars` → `PredictionDataAdapter`): reads the per-market `odds` series (`provider="polymarket"`, `symbol=conditionId`, `metric="odds"`) written by `ingest/polymarket_odds.py`. **As of #393 (merged), this ingest is now SCHEDULED** on the hourly cron (`research/loop.py::_hoard_per_market_odds`, both daily `odds` and hourly `odds_60`), with the +1-bucket PIT lag. So prod will accumulate odds rows. **→ bars flow once the cron has run a few cycles. WORKS (newly).**
4. **Backtest**: the odds series is treated like a price series — entries fire on the conditions, exits on `stop`/`tp`/`time_stop`. **→ HERE IS WHERE IT BREAKS for any resolution-dependent edge.** The backtest never settles the contract at its true \$1/\$0 outcome (no UMA join), so the P&L it reports is odds drift, not the real favorite-longshot P&L. The trust experiment (`polymarket-trust-experiment-2026-06-25.md`) and the maker study (`polymarket-maker-feasibility-2026-06-25.md`) both confirm this empirically: a naive hold-to-resolution fade *loses every toy trade* because rich contracts mostly resolve YES — a fact the wired backtest literally cannot see.
5. **Feature nuance (subtle, worth knowing):** the canonical inbox spec keys entries on `pm_implied_prob`/`pm_prob_velocity` — but those are registered as `source="polymarket_clob"` MACRO-aggregate series stored under `symbol="MARKET"` (a single market-wide composite), whereas the finder feeds the PER-conditionId `odds` series as the bar OHLC. So the entry *condition* feature and the *bar* series are not the same object. The bar IS the per-market odds; the `pm_implied_prob` condition reads the aggregate. For a "the contract's own odds spiked" thesis you want the entry to read the *cell's own odds bar*, not the macro composite. This is a real (small) wiring mismatch in the flagship spec, not a blocker, but it means the authored spec doesn't quite test what its rationale claims.

**Net: NL authoring → spec → screen → paper → live all execute. The backtest *runs* but its number is not yet trustworthy for any resolution-sensitive edge.** For the ONE edge the research sprint found plausible (intraday over-extension that reverts *before* resolution, traded as a passive maker), resolution settlement matters less — which is exactly why that candidate is the recommended live test.

---

## (3) Concrete minimal steps to make Polymarket a first-class authorable+testable+armable venue

Ranked by leverage. All additive; none touch the locked Gate constants. This list is the union of scout #385 Fix-A/B/C and the maker study, with #393 already landed.

1. **[DONE — #393]** Schedule the per-market odds ingest (daily `odds` + hourly `odds_60`) + apply the +1-bucket PIT lag. *The prediction lane now has data.*

2. **[THE ONE REAL GAP] UMA resolution / `payoutNumerators` join (scout Fix-B).** Add a resolution source that, per ingested `conditionId`, fetches the resolved winning outcome + actual resolution timestamp (Gamma `umaResolutionStatus`/`outcomePrices` + CTF `payoutNumerators`), stored append-only as `(provider="polymarket", symbol=conditionId, metric="resolution")` with `available_at = real_resolution_ts` (NOT the scheduled `endDate`). Then join it in `PredictionDataAdapter` / the prediction backtest so a position held to resolution settles at the authoritative \$1/\$0. PIT-safe (only visible once `available_at <= as_of`). **This converts the lane from "odds mean-reversion" (untestable) to a real resolution-settled backtest.** Files: `data/sources/polymarket.py`, `adapters/data/prediction.py`, the backtest exit path. *This is the single highest-value item.*

3. **Run the per-market odds through the leakage tripwire before the Gate trusts it (scout Fix-C).** `research/leakage_tripwire.py` already exists and was run on real odds in the trust experiment (look-ahead checks PASS; the source is PIT-clean). Gate the `odds`/`resolution` features behind it as policy before any prediction cell is funded. Low effort (tripwire built), high safety.

4. **Windowed hourly fetch confirmation.** The trust experiment proved `interval=max&fidelity=60` silently returns *daily-or-nothing*; real hourly needs explicit `startTs`/`endTs` windowing (~335 rows/14-day window). #393 added the `fidelity=60` `odds_60` metric — verify in prod it actually returns hourly spacing (it may need the windowed/paged path, not just the fidelity param) so cells clear `_BRUT_MIN_TRADES=30` honestly. Files: `data/sources/polymarket.py::PerMarketOddsSource.fetch_odds`.

5. **(Optional, correctness) Binary-contract exit semantics in the spec model.** Today a prediction spec borrows `stop_loss`/`take_profit` *fractions* — fine for the intraday-reversion thesis, wrong for hold-to-resolution. A small `StrategySpec` addition (e.g. an `exit.settle_at_resolution: bool`) would let NL authoring express the favorite-longshot edge faithfully. Pairs with item 2. Not needed for the live maker candidate.

6. **(Optional, authoring fidelity) Per-cell odds feature.** Make the prediction entry conditions read the cell's OWN per-market odds (the bar series) rather than the `pm_implied_prob` macro composite, so an authored "this contract over-extended" spec tests what its rationale says. Small change in how `_entry_from_features` / the prediction backtest binds the condition feature for prediction cells.

7. **(Go-live, operational not code) Arm the geopolitics-only maker test.** Per #401: set Polymarket keys (testnet first), human-arm a small passive (maker) fade in the 0%-fee geopolitics corner, mid-band [0.05, 0.95], and log real fills to confirm the +1.68c expected maker-net. This is the only plausibly-positive live edge the sprint found, and the only thing that can convert "plausibly positive" into "real."

---

## (4) Separate big chantier, or mostly wired?

**Mostly wired.** The hard infrastructure is all built and merged:

- **Data:** `universe_pairs` has Polymarket (conditionId-keyed, #313); per-market odds ingest is scheduled (#393); the PIT store + revision safety + the leakage tripwire all exist and were validated on real odds.
- **Backtest:** the finder prediction branch, `PredictionDataAdapter`, the per-category cost overlay, and BRUT per-cell scoring are all wired.
- **Execution:** a complete, testnet-default, real-money-interlocked CLOB adapter (`polymarket.py` + `_polymarket_clob.py`), routed by the exec registry, with the live step coercing prediction orders to limit and supporting maker/post-only.

**The remaining work is one data join + a tripwire gate + an operational arm — measured in days, not a rewrite.** The single item that stands between "runs" and "trustworthy" is the **UMA resolution join (item 2)**. Without it, the prediction-contract backtest is honest in *shape* but cannot measure the resolution-defined edge it targets. With it (plus the tripwire gate), Polymarket is a fully first-class authorable, testable, armable venue — and, per the memory's repeated framing, **the cleanest shot at COSMU's first forward survivor from an axis the giants ignore.**

---

## Provenance (files read, code-verified)

- Exec: `apps/engine/cosmu/adapters/exec/polymarket.py`, `_polymarket_clob.py`, `registry.py`, `master/execution.py` (live routing, lines 242-299)
- Data/research: `adapters/data/prediction.py`, `data/sources/polymarket.py` (`PerMarketOddsSource`, `PolymarketClobSource`), `ingest/polymarket_odds.py`, `research/loop.py::_hoard_per_market_odds` (#393)
- Authoring: `lab/author.py` (`_ASSET_HINTS`, `_FEATURE_HINTS`, `draft_from_brief`), `strategy/spec.py` (`StrategySpec`, `AssetClass.PREDICTION`), `config/feature_registry.py` (pm_* features), `strategies/inbox/g2-prediction-prob-overextension-fade-short.json`
- Screen/universe: `master/screen_universe.py::prediction_markets`, `data/venue_universe.py::fetch_polymarket`
- Prior reports: `docs/reports/polymarket-odds-scout-2026-06-25.md` (#385), `polymarket-trust-experiment-2026-06-25.md` (#389), `polymarket-intraday-overextension-2026-06-25.md` (#400), `polymarket-maker-feasibility-2026-06-25.md` (#401), `h9-polymarket-thetadecay-2026-06-25.md` (#399)
- #393 commit: `7741c65` (schedule per-market odds ingest + +1-bucket PIT lag; Fix-B/UMA join explicitly deferred)

**Zero production impact:** read-only, docs-only, no merge.
