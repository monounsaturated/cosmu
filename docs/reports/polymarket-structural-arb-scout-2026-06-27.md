# Single-venue Polymarket structural arb — SCOUT (`Σ(YES legs) < $1`)

**Date:** 2026-06-27 · **Mode:** EXPERIMENT / SCOUT — zero prod impact; a keyless research script + offline tests +
this report. No DB write, no engine change, no Gate constant touched, no money path. **PR, do NOT merge** (operator
merges).
**Playbook origin:** bridge #6a (`docs/reports/cross-disciplinary-playbook-2026-06-26.md`) — the strictly-better
pivot after the cross-venue Polymarket×Kalshi scout came back **NO-GO** (0 matched contracts; Kalshi excludes
France; `docs/reports/polymarket-kalshi-arb-scout-2026-06-27.md`).

**Thesis under test:**
> In a **mutually-exclusive, exhaustive** multi-outcome group (an N-candidate election, an N-band ladder),
> exactly one YES leg resolves to \$1 and the rest to \$0. Buying ONE share of EVERY YES leg therefore redeems
> exactly \$1. If `Σ(best-ask YES across all legs)` net of the real Polymarket taker fee is **persistently < \$1**,
> the basket is a market-neutral, desk-invisible, tiny-ticket **structural arb** — single venue (no second
> account, no France/jurisdiction wall), on a venue already wired for execution in-repo.

**Script:** `apps/engine/scripts/research/polymarket_structural_arb_scout.py` (keyless, read-only, injectable
fetcher). **Tests:** `apps/engine/tests/test_polymarket_structural_arb.py` (24 cases, offline, fixture-injected).

---

## Verdict: **instrument BUILT; live verdict PENDING a Polymarket-reachable run** — and the a-priori prior is *hostile*

Two separate findings, kept distinct because they have very different confidence:

1. **Built + tested (high confidence).** The scanner is complete and correct: it discovers both real Polymarket
   multi-outcome shapes, walks the live ask book per leg, prices the basket net of the **one in-repo fee model**,
   applies the **sequential-fill adverse-move haircut** and the **fat-tail exclusion guards**, and (with
   `--snapshots N`) **measures persistence** rather than asserting it. 24 offline unit tests pin the math and the
   sign convention.

2. **No live numbers from THIS session (egress-blocked).** This web session's egress policy **denies
   `*.polymarket.com`** (proxy returns `403` on `CONNECT` to `gamma-api.polymarket.com`, `clob.polymarket.com`,
   `data-api.polymarket.com`). Polymarket's API is keyless, so the block is environmental, not a credential gap —
   the prior cross-venue scout was simply run from a Polymarket-reachable box. **I did not fabricate a snapshot.**
   The script reports `status=egress_blocked` and exits cleanly; the operator runs one command (below) from a
   permitted environment to get the real `Σ(YES)` numbers.

3. **A-priori prior: this edge is structurally hard, and a worked example shows why** (next section). The headline
   "Σ(best-ask) < \$1" is a *mirage* the moment you charge the two costs you cannot avoid — the per-category taker
   fee and the non-atomic sequential fill. On a deliberately *favourable* synthetic 4-way basket with a **+3.5¢
   gross** gap, the net edge is **+0.85¢ with zero drift after fees alone, and goes NEGATIVE (−2.2¢) at just one
   tick of fill drift.** So the bar a live snapshot must clear is high: a *persistently* sub-\$1 basket whose gap
   exceeds fees **plus** the realized fill haircut, on a group that is provably exhaustive and not UMA-fat-tail.

This is the same shape of lesson as the cross-venue scout: the *clean* version of the arb is exactly where
professional bots compete hardest, so the residual after honest costs is most likely ≤ 0 at retail-reachable size.
**The point of the build is to MEASURE that residual, not to assume it.**

---

## The arb math (exact — this is the sign convention the tests pin)

For a mutually-exclusive, **exhaustive** group of N legs with best-ask YES prices `a_1 … a_N`:

```
Basket trade:   buy 1 YES share of every leg.            (taker — you LIFT the ask, never the bid)
Gross cost  =   Σ a_i
Entry fee_i =   rate(category_i) · a_i · (1 − a_i)        per share   [Polymarket per-category taker fee]
Payout      =   exactly ONE leg redeems $1, the rest $0   →  you receive exactly $1
Exit fees   =   $0   (redemption is not a trade; losing legs expire worthless — no sell)

Gross edge  =   $1 − Σ a_i
NET edge    =   $1 − Σ a_i·(1 + rate_i·(1 − a_i))         =  Gross edge − Σ fee_i
ARB iff     =   NET edge > 0   (before the sequential-fill haircut)
```

- **Direction is the #1 self-deception risk** (playbook red-team), so the tests assert it explicitly: a sub-\$1
  basket is **+edge**; fees and the haircut **only ever reduce** it; an over-\$1 basket is **−edge**.
- **Fees are the canonical in-repo model**, not re-hardcoded: `cosmu/spine/asset_fees.polymarket_category_fee_rate`
  (per-category, 0.00–0.072; unknown → the conservative crypto rate). Polymarket rolled out a taker fee on
  2026-03-23, so post-rollout this term is real (the exec adapter's "0 bps" comment is **stale**). Entry-only.

## The sequential-fill adverse-move haircut (the ⚠️ the brief flags)

You **cannot fill all N legs atomically** — you place N separate taker orders, and the book moves while you work
the sequence. The scanner models two distinct, additive costs:

1. **Static depth haircut (measured from the real book).** The best ask has finite size. To fill the ticket
   (`--ticket-shares`, default 100), the scanner **walks the live ask ladder** and pays the **VWAP**, not the top
   tick. A leg whose top-of-book can't supply the ticket is flagged not-fully-fillable (the apparent edge is a
   paper quote you can't actually lift).

2. **Dynamic adverse drift (modeled, swept).** Each leg filled *after the first* pays an extra
   `ADVERSE_MOVE_TICKS · $0.01`, because the asks drift up against a basket buyer during the latency of the
   non-atomic sequence. Swept as a **band** so the verdict is never one optimistic point estimate:

   | assumption | drift / post-first leg | reading |
   |---|---|---|
   | `optimistic` | 0 tick | a near-atomic fill (the neg-risk path, or a very fast taker sweep) |
   | `base` (primary) | 1 tick | one cent of slippage per later leg |
   | `conservative` | 2 ticks | a contested book that moves while you work it |

`net_edge = $1 − Σ (vwap_i + drift_i)·(1 + rate_i·(1 − fill_i))`. A basket is a **candidate** only if it clears all
exclusions, is **fully fillable** at the ticket, **and** `net_edge > 0` at the **base** assumption.

## The exclusion guards (the fat-tail / un-fillable filter)

A basket is market-neutral only if mutual-exclusivity **and** exhaustiveness **and** reliable resolution **and**
real fillable depth ALL hold. The scanner refuses a group on any of:

| guard | constant | why |
|---|---|---|
| `non_exhaustive` | (shape) | a non-neg-risk set of separate binaries is **not provably exhaustive** — zero legs could resolve YES → basket pays \$0, not \$1. Only neg-risk sets and single categorical markets are treated as exhaustive. |
| `uma_fat_tail_thin_leg` | `UMA_SAFETY_LIQUIDITY_USD = 2,000` | a thin leg is UMA-dispute-prone (a whale once falsely resolved a \$7M market) — never size as if resolution is risk-free. |
| `leg_spread_too_wide` | `MAX_LEG_SPREAD = 0.05` | a 5¢+ spread means the "best ask" is unreliable; you pay through it. |
| `leg_top_depth_too_thin` | `MIN_LEG_DEPTH_USD = 50` | a leg you can't lift at the quote. |
| `group_too_thin` | `MIN_GROUP_LIQUIDITY_USD = 5,000` | the whole basket is a paper mirage. |
| `resolves_too_soon` | `FINAL_EXCLUDE_HOURS = 24` | stale books + settlement noise near resolution. |

## Worked example — why the prior is hostile (SYNTHETIC fixture, **NOT live market data**)

A deliberately *favourable* 4-candidate neg-risk election where the displayed best-asks sum to **\$0.965** (a
**+3.5¢** gross gap), every leg deep, `category=politics` (4% fee). Reproducible from the unit-test fixtures — this
is an *illustration of the math*, **not** a measured market:

| assumption | Σ best-ask | Σ fill (VWAP + drift) | fees | **net edge / \$1** |
|---|---|---|---|---|
| optimistic (0 tick) | 0.9650 | 0.9650 | 0.0265 | **+0.0085** |
| base (1 tick) | 0.9650 | 0.9950 | 0.0272 | **−0.0222** |
| conservative (2 tick) | 0.9650 | 1.0250 | 0.0280 | **−0.0530** |

A **3.5-cent gross gap survives fees by less than a cent, and one tick of sequential-fill drift flips it
negative.** That is the structural prior in one table: the naive `Σ(YES) < $1` headline is eaten by the two costs
you cannot avoid. A live edge has to be *bigger and stickier* than this favourable illustration to be real.

---

## How to get the real numbers (one command, from a Polymarket-reachable env)

Polymarket Gamma + CLOB are **keyless** — no account, no key. From the operator's local Mac (or any environment
whose egress policy allows `*.polymarket.com`):

```bash
# one live snapshot over the 50 most-liquid multi-outcome groups
PYTHONPATH=apps/engine python3 apps/engine/scripts/research/polymarket_structural_arb_scout.py \
    --max-groups 50 --ticket-shares 100 --json-out /tmp/struct_arb.json

# PERSISTENCE: re-sample the same groups 6× at 2-minute spacing and report the hit-rate of each sub-$1 basket
PYTHONPATH=apps/engine python3 apps/engine/scripts/research/polymarket_structural_arb_scout.py \
    --snapshots 6 --interval 120
```

The script prints a per-group table (Σ best-ask, net edge at base + conservative, the exclusions that fired) and a
`SUMMARY_JSON` with `gross_sub_dollar_groups` (Σ best-ask < \$1, pre-cost) vs `net_haircut_candidates` (survive
fees + haircut + exclusions) and, in persistence mode, each candidate's `hit_rate`.

**What "GO" looks like:** ≥1 group with `net_edge_base > 0`, `all_filled = true`, **no** exclusions, and a
persistence `hit_rate == 1.0` across the snapshots. Anything less is the prior confirmed — `Σ(YES)` sits at \$1
net of cost because the neg-risk mechanism and the bots keep it there.

---

## Honesty notes / limitations

- **No live snapshot in this session.** Egress is blocked here; the numbers above are the *math on a synthetic
  fixture*, explicitly labeled. The script will not invent a market — it reports `egress_blocked`.
- **One snapshot ≠ persistence.** The thesis demands *persistent* sub-\$1. A single run can flag a candidate; only
  `--snapshots` over a window measures whether it *persists* (and a transient sub-\$1 that closes before you fill
  all N legs is exactly the adverse-move the haircut models).
- **Exhaustiveness is inferred, not proven.** Neg-risk sets and single categorical markets are treated as
  exhaustive; un-linked binaries are flagged `non_exhaustive`. A live build must confirm the neg-risk flag truly
  guarantees "exactly one resolves YES" for each flagged group (read the resolution text), not assume it.
- **Resolution risk is bounded by liquidity heuristics, not semantics.** The scanner can't parse every resolution
  rule offline; it excludes thin/dispute-prone legs conservatively and surfaces the rest for a human read.
- **Fees pinned to today's schedule** (the operator rule, `asset_fees.py`): the current per-category taker fee is
  charged, which post-2026-03-23 is non-zero — the single biggest reason a thin gross gap nets out.

## Next step — gated, NOT built here

Phase 2 (a typed `structural_arb` DataSource + strategy type through the Gate) is **conditional on a real, fillable,
persistent sub-\$1 basket surviving the haircut** — which **cannot be verified from this session**. Building a
money-path strategy on an unmeasured edge would violate the project's core rule (the Gate funds; measure first). So
Phase 2 is **explicitly deferred** to a confirmed live measurement. If the operator's run shows even one persistent
`net_haircut_candidate`, the build is: a keyless `structural_arb` source that snapshots the per-group basket cost,
a typed strategy whose entry is `net_edge_base > 0 ∧ all_filled ∧ no_exclusions ∧ persistence`, sized tiny-ticket,
routed through the **locked** Gate (no Gate constant changes). Until then, this scout is the durable artifact.

## TL;DR for the operator

1. **Built + tested:** a keyless single-venue `Σ(YES) < $1` scanner — both Polymarket shapes, depth-walked fills,
   **sequential-fill haircut** (best/base/worst band), fat-tail exclusions, a **persistence** mode, 24 offline
   tests. Zero prod impact.
2. **No live numbers here:** this session's egress **blocks `*.polymarket.com`** (keyless, so it's the environment,
   not a key). I did **not** fabricate a snapshot. Run the one command above from your Mac for the real `Σ(YES)`.
3. **Prior is hostile:** a +3.5¢ gross basket nets **+0.85¢ at best and goes negative at one tick of drift** once
   you charge the real per-category fee + the non-atomic fill. The live bar is high: persistent, exhaustive,
   non-fat-tail, fillable, *and* net-positive after the haircut.
4. **Phase 2 is deferred,** not abandoned — it builds only if a real basket clears the haircut. The Gate funds;
   we measure first.
