---
name: variance-attribution
description: Decompose a funded track's SIM→live divergence into named, signed buckets — fees · slippage · funding · signal-decay · regime (+ an honest residual) — so "the backtest was a lie" becomes "the backtest was a lie BECAUSE …". Review-only diagnostic; never moves money.
---

# variance-attribution

When a track's live results drift from its sim forward-test, `Track.sim_live_divergence` tells you *how much* the backtest missed — this skill tells you **why**. It decomposes the per-period divergence `(live − sim)` into five named, signed contributions plus a first-class **residual**, so you can tell a costs problem (fix execution) from an alpha problem (the edge is dead) from a luck problem (a different regime mix).

**Review-only.** It only *explains* — it never funds, defunds, sizes, or routes an order. It is out of the gate path and out of the money path; the deterministic lifecycle (`portfolio/rotation.py`), the anticipatory drift monitor (`master/drift.py`), and the live toggle alone dispose of capital.

## When to use
- A funded track is underperforming its sim and you ask: *"is this fees/slippage I can fix, or a dead edge I should pull?"*
- Post-mortem on a defunded track — attribute the shortfall before authoring the next variant.
- Sanity-check before launching live: how much of the forward-test edge survives realistic costs?

## Run (from repo root; `PYTHONPATH=apps/engine`)
```bash
PYTHONPATH=apps/engine python3 -m cosmu.research.attribution <strategy_version_id>
PYTHONPATH=apps/engine python3 -m cosmu.research.attribution <strategy_version_id> --sim-edge 0.012   # explicit per-period backtest edge
PYTHONPATH=apps/engine python3 -m cosmu.research.attribution <strategy_version_id> --json
```

## The decomposition (`research/attribution.py`)
`divergence = live_net − sim_net = fees + slippage + funding + signal_decay + regime + residual`, all in **per-period mean fractional** units (cost legs: per-trade), so every bucket is comparable to the divergence it explains. Sign convention: a component is its contribution *to* `(live − sim)`.

| Bucket | What it isolates | Source |
|--------|------------------|--------|
| **fees** | live paid more/less fee per trade than the sim model | `executions` ledger, `is_paper` line (sim vs live fills) |
| **slippage** | realized slippage worse/better than modeled | `executions.slippage` per fill |
| **funding** | perp/carry cash-flow differed live (spot = 0) | signed cash-flow leg |
| **signal_decay** | the edge itself eroded since funding (alpha decay) | reuses `master/drift` edge-decay fit: current edge vs funded reference |
| **regime** | live got a different regime *mix* than the backtest (Brinson allocation effect) | regime weights × sim per-regime gross |
| **residual** | everything the buckets don't explain — named, never hidden | `divergence − explained` |

The **residual is reported honestly**: the components are independent best-estimates (the cost legs are precise from the ledger; decay/regime are model estimates), so what they don't tie out is surfaced, not absorbed. A large residual means the story is incomplete — supply explicit regime buckets / a backtest `--sim-edge` to tighten it.

## Read the bar
- **Costs dominate** (fees/slippage strongly negative) → an execution problem: better order type, venue, or sizing — the edge may be fine.
- **signal_decay dominates** (strongly negative, short half-life) → the edge is dying; this is what the anticipatory **drift monitor** pulls on. Pull capital, don't re-tune.
- **regime dominates** → live just drew a worse regime mix than the backtest; not necessarily a dead edge, but check the strategy's proven-regime passport.
- **residual dominates** → you don't yet understand the divergence; don't act on a guess.

## Invariants
- **Pure + offline + deterministic + seed-free** — same rows in, same decomposition out.
- **Review-only** — explains divergence; never funds, defunds, sizes, or moves money. Out of the gate/money path and out of any LLM path.
- **Honest residual** — components + residual reconstruct the divergence exactly; the unexplained part is always named.
- **Signal & fill stay separate** — cost legs read the `is_paper` line of the executions ledger; the model decision and the venue fill are never collapsed.

## Verify
- `cd apps/engine && PYTHONPATH=. python3 -m pytest tests/test_attribution.py -q`
