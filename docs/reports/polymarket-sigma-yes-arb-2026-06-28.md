# Polymarket single-venue Σ(YES) < $1 structural-arb — bounded live scan + verdict (2026-06-28)

**Autonomous-run experiment. DO NOT MERGE / DO NOT TRADE.** Read-only scan + analysis only; no order
was ever placed, no prod/DB/Gate touched.

## TL;DR — VERDICT: **KILL**

The price-signal-free, market-neutral "buy every YES leg of a mutually-exclusive market for a total
< $1" thesis does **not** survive a live look at the most-traded Polymarket markets. Over a bounded live
scan of the **top 58 multi-outcome markets by 24h volume** (38.7% of the ~150 target; budget-capped),
**19 baskets were gross Σ(best-ask YES) < $1, but ZERO survived** fees + the sequential-fill haircut +
the fat-tail / fillability / resolution-trust exclusions. Dominant killing wall: **leg_top_depth_too_thin
(16 of 19)** — the sub-$1 sum is a top-of-book mirage on illiquid tail legs you cannot actually lift at
the quote. No small live test is warranted.

| Field | Value |
|---|---|
| Verdict | **KILL** |
| Dominant wall | `leg_top_depth_too_thin` (fillability) — then `non_exhaustive` (resolution-trust) |
| Net-of-fee+haircut candidates | **0** |
| Gross Σ(best-ask)<$1 baskets | 19 |
| Groups scanned | **58 / 150 target (38.7%)** |
| Events inspected | 67 |
| API calls | 829 |
| Wall-clock | 661.7s (~11 min; stopped on the 660s budget wall, as designed) |
| Live test warranted | **NO** |

## Method

- **Engine:** the on-main SCOUT shipped in PR #449
  (`apps/engine/scripts/research/polymarket_structural_arb_scout.py`) — its pure math (`price_basket`,
  `vwap_to_fill`, `leg_fee_frac`, `exclusions`) and Gamma/CLOB parsing (`_group_from_event`, `fetch_book`)
  are reused **verbatim** and are unit-tested offline (`tests/test_polymarket_structural_arb.py`).
- **New bounded driver:** `apps/engine/scripts/research/polymarket_arb_bounded_scan.py` adds only the three
  things this autonomous run required and the scout did not enforce:
  1. **Volume-ordered discovery** — pages Gamma `/events?order=volume24hr` (the fillable-universe order),
     stopping at `--max-groups 150`. An arb is only fillable on liquid-and-traded markets.
  2. **A hard compute budget** — a prior unbounded sweep timed out at 27 min. Enforces BOTH a wall-clock
     wall (`--budget-seconds 660`) AND an API-call cap (`--max-api-calls`), whichever trips first; emits an
     honest partial verdict + COVERAGE, never a raised timeout, never a fabricated number.
  3. **Coverage accounting + a single pre-registered verdict block.**
- **Keyless, read-only.** Polymarket Gamma + CLOB; no account, no key, no order.
- **Fees:** the ONE in-repo per-category model (`cosmu/spine/asset_fees.polymarket_category_fee_rate`,
  pinned-to-today), entry-only (winner redeems at $1 untaxed, losers expire — N entry taker fees).
- **Sequential-fill haircut:** each leg's cost is the depth-VWAP up its real ask ladder to a 100-share
  ticket (not best-ask), plus an adverse-drift add-on on every post-first leg (non-atomic fills) swept
  optimistic / **base (1 tick, primary)** / conservative (2 ticks).
- **Exclusions (fat-tail guard):** non-exhaustive set, group/leg too thin, wide leg spread, thin-UMA
  fat-tail leg, top-of-book depth < $50, resolves within 24h.

### Coverage note (why 38.7%, not 100%)

The highest-volume Polymarket markets are deep multi-outcome books (24-way World Cup / Wimbledon / MLB /
nominee fields). Each leg = one CLOB `/book` call, so a single 24-leg event costs 24 calls and ~0.8s/call
of live latency. The first run tripped the 300-call cap at 20 groups (13.3%); raising the cap to 900 made
the **wall-clock the binding wall** at 58 groups / 661s — the intended honest-partial behavior. The
scanned 58 are the **most-liquid 58 multi-outcome markets by 24h volume**, i.e. exactly the fillable head
of the universe where an arb would have to live; the un-scanned tail is strictly thinner and would only
add more `leg_top_depth_too_thin` / `non_exhaustive` kills, not a survivor.

## Three walls, with live numbers

**1. Fillability (the dominant wall — `leg_top_depth_too_thin`, 16/19 gross-sub-$1 baskets).**
The genuinely exhaustive neg-risk baskets that ARE gross sub-$1 are sub-$1 *because* their long-tail
candidates are quoted at 1–2¢ with no real depth. Examples (Σ best-ask | base-case net edge):

| Market | shape | legs | Σ ask | net(base) | killed by |
|---|---|---|---|---|---|
| Democratic Presidential Nominee 2028 | neg_risk | 24 | 0.465 | +0.257 | leg_top_depth_too_thin |
| NFL Champion 2027 | neg_risk | 24 | 0.604 | +0.106 | leg_top_depth_too_thin |
| 2026 Women's Wimbledon Winner | neg_risk | 24 | 0.651 | +0.051 | leg_top_depth_too_thin |
| MLB World Series Champion 2026 | neg_risk | 24 | 0.657 | +0.048 | leg_top_depth_too_thin |

Their "Σ(YES) far below $1" headline looks like free money — but it is the artifact of dozens of dust
quotes. You cannot buy 100 shares of every leg at those asks; the top-of-book depth on the tail legs is
below the $50 fillability floor. The deeper-book legs would re-price as you swept them. This is the
textbook **stale/dust top-of-book mirage**, not a fillable arb.

**2. Resolution-trust / exhaustiveness (`non_exhaustive`, 8/19).**
The *fattest* apparent edges are all unlinked binaries, NOT mutually-exclusive-AND-exhaustive sets — so
the basket can pay **$0** (zero legs resolve YES) and is not market-neutral at all:

| Market | Σ ask | why it's a trap |
|---|---|---|
| Who will enter Iran by June 30? | 0.021 | unlinked binaries; nobody entering pays $0 |
| Will the US confirm aliens exist by …? | 0.138 | single tail binary; not a partition |
| What price will Bitcoin hit June 22–28? | 0.085 | overlapping price-ladder binaries, not exhaustive |
| What price will Ethereum hit in June? | 0.413 | same — bands don't partition the space |

These are exactly the fat-left-tail / ambiguous-resolution markets the guard is built to refuse. A "free"
sub-$1 set is worthless if one leg need not win.

**3. Persistence / haircut (`persistence_haircut_eats_edge`, 1/19) + the overround on clean markets.**
The clean, well-quoted, fully-exhaustive 3-way matches — the only baskets where every leg is fillable and
resolution is trustworthy — are uniformly **Σ(YES) > $1** (the bookmaker overround): France/Sweden 1.010,
Brazil/Japan 1.030, Argentina/Cabo Verde 1.009, US/Bosnia 1.010, Germany/Paraguay 1.020. Where the market
is liquid and trustworthy enough to fill, the vig has already removed the edge — and the thin gross-arb
that did exist was eaten by the 1-tick base haircut.

## Conclusion

The thesis fails the way the scout was designed to detect: **the only Σ(YES)<$1 baskets are either
un-fillable (dust tail legs), un-exhaustive (can pay $0), or both; the only fillable-and-trustworthy
baskets carry the overround and are >$1.** There is no persistent, fillable, trustworthy-resolution sub-$1
set in the liquid head of Polymarket. **KILL. No live test.** The single-venue structural-arb lane is
closed; the scout/driver remain as a reusable, budget-bounded re-check tool.

## Reproduce

```
cd apps/engine
python3 scripts/research/polymarket_arb_bounded_scan.py \
  --max-groups 150 --budget-seconds 660 --max-api-calls 900 --ticket-shares 100 \
  --json-out /tmp/pmarb/scan.json
python3 -m pytest tests/test_polymarket_arb_bounded_scan.py tests/test_polymarket_structural_arb.py -q
```

Raw SUMMARY_JSON of the scan this report quotes:

```json
{"status":"ok","ticket_shares":100.0,"coverage":{"target_groups":150,"groups_scanned":58,
"coverage_pct":38.7,"events_seen":67,"api_calls":829,"elapsed_s":661.71,"stop_reason":"budget_seconds"},
"verdict":"KILL","wall":"leg_top_depth_too_thin","live_test_warranted":false,
"net_haircut_candidates":0,"gross_sub_dollar_groups":19,
"wall_breakdown":{"leg_top_depth_too_thin":16,"non_exhaustive":8,"resolves_too_soon":2,
"persistence_haircut_eats_edge":1},"candidates":[]}
```
