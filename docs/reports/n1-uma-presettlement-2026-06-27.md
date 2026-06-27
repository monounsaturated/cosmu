# N1 — UMA pre-settlement convergence (2026-06-27)

**Scope:** EXPERIMENT ONLY — the test-first pick of [edge-hypothesis slate v2](edge-hypothesis-slate-v2-2026-06-26.md).
Zero production impact: offline, keyless, persists NOTHING to prod, NO Gate constant touched, NO behaviour
change, docs-only. Output = this report + a disposable HTML table
(`docs/reports/n1-uma-presettlement-table-2026-06-27.html`) + the harness
(`apps/engine/scripts/research/n1_uma_presettlement.py`). Do NOT merge code into a runtime path.

**Thesis (N1):** Polymarket resolves via UMA's optimistic oracle. When an outcome is PROPOSED on-chain a
~2-hour liveness window opens before the market is final ($1/$0). The proposal is a public on-chain event the
instant it lands, but the CLOB is still quoted by slow retail who do not watch the oracle. If the about-to-win
leg is still quoted at a **discount (< $1) inside the liveness window**, buying it and holding to resolution
captures the gap — an *oracle-watching* edge (not speed). The PROPOSAL event itself is the truth-feed. Distinct
from H9 (hold-to-resolution theta-decay) and the v1 slate's resolution-lag (which use an *external* feed); N1
trades only the terminal liveness window and uses the UMA proposal event as the marker.

---

## TL;DR verdict — KILL

| | value |
|---|---:|
| N clean single-proposal markets (customLiveness∈{0,None}, no dispute) | **120** |
| …with an in-window CLOB minute-quote | 119 |
| **Mean about-to-win leg price AT the proposal landing** | **0.9995** |
| Mean about-to-win leg price **30m BEFORE** the window opens | 0.9995 |
| Fraction of markets with winning leg ≥ 0.97 at proposal | **100%** |
| Fraction of markets with winning leg ≥ 0.99 at proposal | **100%** |
| Most-discounted single market (entire cohort) | 0.9975 (a **0.25¢** gap) |
| **Tradeable entries** (winning leg ≤ 0.97 at proposal — the pre-registered ENTRY) | **0** |
| Net edge after fees + spread | **n/a — no position was ever openable** |
| Leakage tripwire (per-market look-ahead audit) | **PASS** (120/120 markets backward-honest) |

**One-line:** N = 120 resolved markets; the about-to-win leg already quotes **$0.9995 on average — and is
already pinned to ~$1 *before* the proposal even lands** — so there is no discount to capture and **zero**
markets pass the pre-registered entry filter. The thesis's single failure mode (the window is already priced)
is the actual state of the world. **KILL** on pre-registered kill condition (ii). Fall through to **N5**
(token-unlock supply-shock drift), the slate's #2.

---

## What was pre-registered (BEFORE any result)

One rule, no sweep, declared in the slate and in the harness header:

1. **Universe:** resolved Polymarket binary markets, `customLiveness ∈ {0, None}` (the protocol DEFAULT 2h
   liveness applies), with NO `disputed` in `umaResolutionStatuses` (a dispute opens a second liveness round, so
   the proposal anchor would be wrong), a clean 0/1 `outcomePrices`, and a YES clobTokenId.
2. **The PIT marker — the proposal landing.** Gamma does **not** publish the proposal timestamp directly. But
   for the clean default-liveness case it is *reconstructable*: `umaEndDate == closedTime` is the moment liveness
   **ended**, and the proposal landed exactly `DEFAULT_LIVENESS_SEC = 7200` (2h) earlier:
   `proposal_ts = umaEndDate − 2h`. (Verified `umaEndDate == closedTime` on 499/499 closed markets; verified
   `customLiveness == 0` on 500/500 of the recent closed set.)
3. **Entry (PIT-honest):** at the FIRST CLOB minute-quote at-or-after `proposal_ts` and strictly before liveness
   end, read the about-to-win leg's price `q`. The about-to-win SIDE is what a proposal-watcher reads off the
   on-chain proposed outcome the instant it lands — that *is* the thesis. **Enter only if `q ≤ 0.97`** (a real
   discount). Buy at the ask (`q + 0.01` half-spread, the conservative fill), hold to resolution ($1).
4. **Return per $1 capital** = `(1 − ask)/ask`, net of the category taker fee (geo 0% / sports 3% / crypto 7.2%).
5. **Pre-registered kill criteria:** (i) <30 markets with a tradeable in-window quote; (ii) the about-to-win leg
   already quotes ≥ 0.97/0.99 inside the window (no discount); (iii) net return-to-$1 beats the category fee.
   **Any fail → KILL.**

---

## What the data shows

### The window is already priced — *before* the proposal

Across **120** clean markets the about-to-win leg averages **0.9995 at the proposal landing**, and — the decisive
diagnostic — it already averages **0.9995 a full 30 minutes *before* the 2h window even opens** (i.e. ~2.5h before
liveness end). The two numbers are identical to four decimals: **the market converges to the outcome well before
the on-chain proposal**, because for resolvable binaries the real-world fact (the election was called, the game
ended, the FDV printed) is public knowledge long before the UMA proposer submits on-chain. The proposal is a
*formality that ratifies an already-known price*, not a release of new information.

Concretely, scanning the raw minute path on the largest markets (Trump-2024, Harris-2024, Trump-inauguration)
the winning leg sits at **0.997–0.9995 for 5+ hours before liveness end** and never dips — there is no
"slow-retail mispricing the proposed outcome" to fade.

### Zero tradeable entries

- **100%** of markets have the winning leg **≥ 0.97** at proposal; **100%** have it **≥ 0.99**.
- The single **most-discounted** market in the entire cohort (`Giants win Super Bowl 2025`, the about-to-win NO
  leg) was at **0.9975 — a 0.25¢ gap** — still far above the entry threshold and smaller than any realistic
  fee+spread.
- Result: **0 of 120** markets clear the pre-registered `q ≤ 0.97` entry. There is no position to open, so there
  is no net edge to report — the trade does not exist on real data.

### The leakage tripwire — data is PIT-clean (the kill is real, not an artefact)

The engine's standing look-ahead guard (`cosmu.research.leakage_tripwire`) was run **per market** (each market's
2h window is its own unique, monotonic minute grid — pooling many markets onto one timestamp-keyed grid would
collide timestamps across markets and break `align_asof`'s single-winner identity, a pooling artefact, not a
leak):

- **[1] available_at audit: 120/120 markets strictly backward-looking** (0 look-ahead, 0 wrong-winner). The PIT
  join is honest.
- **[3] forward-shift sanity: 120/120 markets** show no baked-in peek.

So the convergence we measure is real, not a wiring artefact. (The module's own offline controls confirm it
works: the clean control PASSes; the deliberately 1-bar-leaked control correctly FAILs the forward-shift check.)
This matches the [trust experiment](polymarket-trust-experiment-2026-06-25.md): Polymarket odds are PIT-honest,
immutable, resolution-true — the data is trustworthy; the signal simply isn't there.

---

## Why the thesis was wrong (the mechanism, post-mortem)

The slate flagged the one real risk precisely: *"the liveness window is too short to fill at a discount."* The
reality is worse for the thesis — it's not that the window is too short, it's that **there is no discount at any
point in or around the window.** The thesis assumed the on-chain proposal is the moment information becomes
public and that the CLOB lags it. But for the markets UMA resolves cleanly (decisive, non-disputed, default
liveness), the *information* (who won) is public **hours to days** before the proposer bothers to post on-chain;
the CLOB has already arbitraged the price to ~$1. The UMA proposal is downstream of the price, not upstream of
it. "Oracle-watching" buys you nothing when the oracle is the last actor to move, not the first.

The cases where a proposal genuinely *would* surprise the CLOB are exactly the **disputed / custom-liveness**
markets — which we excluded on purpose (their proposal anchor is unknowable from Gamma, and a disputed outcome is
not a clean about-to-win leg). That tail is both rare and adverse (a dispute means the "obvious" outcome was
contestable), so it does not rescue the thesis.

---

## Verdict & next

**KILL** — pre-registered kill condition (ii) fires unambiguously: the about-to-win leg already quotes ≥ 0.99 in
100% of markets, there is no discount to capture, and **0/120 markets** clear the entry filter. The PIT join is
proven clean, so this is a true absence-of-edge, not a pipeline bug. No typed spec is authored; nothing is routed
to the Gate.

Per the slate's fall-through plan, the next test-first pick is **N5 — token-unlock supply-shock drift** (DefiLlama
`/unlocks`, the leak-proof dated event, the highest-novelty survivor), with **N11** (attention-acceleration) and
**N13** (delisted-survivorship reversion) behind it.

---

## Reproducibility / provenance

- **Endpoints (keyless, free):** `gamma-api.polymarket.com/events?closed=true` (discovery + UMA fields, embedded
  per-market — verified 189/189 carry `umaEndDate`/`customLiveness`/`umaResolutionStatuses`/`outcomePrices`, so
  **no per-market re-fetch**); `clob.polymarket.com/prices-history?...&fidelity=1&startTs&endTs` (minute odds in
  the window — the windowed path the [trust experiment](polymarket-trust-experiment-2026-06-25.md) proved is the
  only way to get sub-daily spacing).
- **Code read:** `cosmu/data/sources/polymarket.py` (`_parse_resolution_ts`, `PolymarketResolutionSource`,
  `PerMarketOddsSource`), `cosmu/research/leakage_tripwire.py`, `cosmu/master/scorer.py`,
  `scripts/research/h9_polymarket_thetadecay.py` (sibling-harness conventions reused).
- **Harness:** `apps/engine/scripts/research/n1_uma_presettlement.py`. Run:
  `python3 apps/engine/scripts/research/n1_uma_presettlement.py --max-events 400 --max-markets 120`.
  Deterministic given the public API state; all numbers above are from a live run on 2026-06-27.
- **Zero production impact:** read-only fetches; no DB writes, no `alt_data` rows, no cron, no Gate run, no code
  merged into a runtime path. Docs + harness only.
