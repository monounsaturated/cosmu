# intent: the TYPED two-lane router — read a StrategySpec's `lane` discriminator and dispatch to the ONE correct
# evaluator path, so routing is explicit on the spec instead of an accident of which function a runner happens to
# call; inputs: a StrategySpec + the args the chosen evaluator needs; outputs: that evaluator's verdict (a list of
# Promotions for the gate-lane, a deploy-bar dict for the deploy-lane); invariants: this is a THIN router only — it
# NEVER re-implements, softens, or duplicates an evaluator (it imports and calls the existing ones), it NEVER moves
# money, and the gate-lane stays the honest 0.95 deflated-Sharpe + BH-FDR cohort gate (no threshold is touched here).
#
# WHY THIS EXISTS. There are two unconnected evaluator paths today:
#   - "deploy-lane": externally-documented strategies (GEM, Faber GTAA, risk parity, ...) cleared by a
#     positive-OOS DEPLOYMENT bar (`taa.validate()`-style), NOT the 0.95 in-sample Gate.
#   - "gate-lane": NOVEL in-sample-mined hypotheses judged by `promote_cohort` (0.95 deflated-Sharpe per
#     candidate AND surviving Benjamini-Hochberg FDR across the cohort).
# Which path a candidate hit was decided implicitly by which function a runner happened to call — a silent
# mis-route (a documented long-only equity strategy shoved through the gate-lane is exactly what killed it).
# The fix is a typed discriminator (`StrategySpec.lane`) + this router, NOT softening either bar.

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

from cosmu.config.settings import GateSettings
from cosmu.master.cohort import Candidate, Promotion, promote_cohort

if TYPE_CHECKING:  # avoid importing the heavy store/spec at module load — only types
    from cosmu.knowledge.store import Store
    from cosmu.strategy.spec import StrategySpec

Lane = Literal["gate", "deploy"]

# A deploy-lane evaluator is a `taa.validate()`-style callable: it runs the documented strategy on REAL prices and
# returns its deployment-bar verdict dict (the one carrying the "deployable" key). The router does not care which
# documented strategy it is — the runner supplies the right module's `validate` so the router stays a pure dispatcher.
DeployValidate = Callable[..., dict[str, Any]]


def lane_of(spec: StrategySpec) -> Lane:
    """The spec's evaluation lane. An unset / legacy spec defaults to "gate" (the discriminator's default), so
    every existing spec keeps its current gate-lane behaviour. Pure read — no side effects, no money moved."""
    # `spec.lane` is the typed discriminator (Literal["gate","deploy"], default "gate"); read it directly so a
    # spec missing the attribute entirely (a hand-rolled stub in a test) still falls back to the gate-lane.
    return getattr(spec, "lane", "gate")


def route_spec(spec: StrategySpec) -> Lane:
    """Resolve which lane a spec routes to WITHOUT running anything — the thin discriminator read on its own, for
    callers that want to branch/log/audit before paying for an evaluation. Alias-friendly to `lane_of`."""
    return lane_of(spec)


def evaluate_by_lane(
    spec: StrategySpec,
    *,
    store: Store | None = None,
    candidates: Sequence[Candidate] | None = None,
    gates: GateSettings | None = None,
    deploy_validate: DeployValidate | None = None,
    promote_kwargs: dict[str, Any] | None = None,
    validate_kwargs: dict[str, Any] | None = None,
) -> list[Promotion] | dict[str, Any]:
    """Dispatch `spec` to the ONE correct evaluator by its typed `lane`, calling the existing evaluator (never a
    copy). This is the choke point that replaces "whichever function the runner happened to call".

    gate-lane  (default): runs `promote_cohort(store, candidates, gates, **promote_kwargs)` — the honest 0.95
        deflated-Sharpe per-candidate bar AND Benjamini-Hochberg FDR across the cohort. Returns `list[Promotion]`.
        Requires `store`, `candidates`, and `gates` (this lane judges a COHORT, not one spec in isolation).

    deploy-lane: runs the supplied `deploy_validate(**validate_kwargs)` — the documented strategy's positive-OOS
        DEPLOYMENT bar (`taa.validate()`-style), NOT the 0.95 in-sample Gate. Returns its verdict dict.

    The router only chooses the path and forwards arguments; it does not invent a verdict, and it never relaxes a
    threshold. A lane whose required inputs are missing raises ValueError loudly (so a mis-wired runner fails fast
    rather than silently mis-routing — the very failure this module exists to kill)."""
    lane = lane_of(spec)

    if lane == "deploy":
        if deploy_validate is None:
            raise ValueError(
                f"spec {spec.name!r} is deploy-lane but no `deploy_validate` evaluator was supplied — the "
                f"deploy-lane is the documented-strategy positive-OOS bar (taa.validate-style), so the runner "
                f"must pass that strategy module's `validate` callable."
            )
        return deploy_validate(**(validate_kwargs or {}))

    # gate-lane (the default for every existing spec): the 0.95 deflated-Sharpe + BH-FDR cohort gate.
    if store is None or candidates is None or gates is None:
        raise ValueError(
            f"spec {spec.name!r} is gate-lane but requires `store`, `candidates`, and `gates` — the gate-lane "
            f"judges a cohort against the 0.95 deflated-Sharpe bar + BH-FDR, not a single spec in isolation."
        )
    return promote_cohort(store, list(candidates), gates, **(promote_kwargs or {}))
