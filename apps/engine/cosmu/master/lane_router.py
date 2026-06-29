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

Lane = Literal["gate", "deploy", "explore"]

# A deploy-lane evaluator is a `taa.validate()`-style callable: it runs the documented strategy on REAL prices and
# returns its deployment-bar verdict dict (the one carrying the "deployable" key). The router does not care which
# documented strategy it is — the runner supplies the right module's `validate` so the router stays a pure dispatcher.
DeployValidate = Callable[..., dict[str, Any]]

# An explore-lane evaluator is the SAME `promote_cohort` the gate-lane uses — the explore lane NEVER has a softer
# bar. The difference is timing + capital, not the threshold: an explore spec lives in a ZERO-CAPITAL paper/observe
# disposition until it actually clears this honest gate, at which point it GRADUATES to the gate-lane. So routing an
# explore spec through `evaluate_by_lane` simply applies the unchanged gate (the graduation test); nothing is loosened.


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

    explore-lane: the GRADUATION test for a vibe. Until graduation an explore spec carries zero capital and is
        observed on paper (it never reaches here). When a caller DOES route it here it is run through the SAME
        `promote_cohort` the gate-lane uses — i.e. the explore lane's bar IS the honest gate, with nothing relaxed.
        A spec that clears it has graduated; a caller flips its lane to "gate". Same required inputs as gate-lane.

    The router only chooses the path and forwards arguments; it does not invent a verdict, and it never relaxes a
    threshold. A lane whose required inputs are missing raises ValueError loudly (so a mis-wired runner fails fast
    rather than silently mis-routing — the very failure this module exists to kill)."""
    # MODEL guard (taxonomy choke point): a kind='llm' conviction strategy has NO honest backtest to deflate, so it
    # must NEVER reach the deterministic Gate (promote_cohort/promote_brut) — it belongs on the conviction lane
    # (cosmu.master.conviction.propose_conviction), a chill check + hard guardrails, human-armed. The gate/deploy/
    # explore lanes are all QUANT evaluators; refusing kind='llm' here keeps a conviction bet structurally off them.
    if getattr(spec, "kind", "quant") == "llm":
        raise ValueError(
            f"spec {getattr(spec, 'name', '<spec>')!r} is kind='llm' (a conviction strategy) — it must NOT be "
            f"routed through the quant Gate; use cosmu.master.conviction.propose_conviction (the conviction lane: "
            f"max-loss + small-size guardrails, human-armed) instead of evaluate_by_lane."
        )
    lane = lane_of(spec)

    if lane == "deploy":
        if deploy_validate is None:
            raise ValueError(
                f"spec {spec.name!r} is deploy-lane but no `deploy_validate` evaluator was supplied — the "
                f"deploy-lane is the documented-strategy positive-OOS bar (taa.validate-style), so the runner "
                f"must pass that strategy module's `validate` callable."
            )
        return deploy_validate(**(validate_kwargs or {}))

    # gate-lane (default) AND explore-lane graduation both run the SAME honest cohort gate — the explore lane is a
    # disposition (zero-capital paper observation) NOT a softer threshold, so its graduation test IS this gate.
    if store is None or candidates is None or gates is None:
        raise ValueError(
            f"spec {spec.name!r} is {lane}-lane but requires `store`, `candidates`, and `gates` — this lane "
            f"judges a cohort against the 0.95 deflated-Sharpe bar + BH-FDR, not a single spec in isolation."
        )
    return promote_cohort(store, list(candidates), gates, **(promote_kwargs or {}))


def is_explore(spec: StrategySpec) -> bool:
    """True iff the spec is in the zero-capital VIBE/EXPLORE disposition — observed on paper, NOT yet gate-judged.
    A thin read used by the explore graduation path to decide which tracks to re-test against the unchanged gate."""
    return lane_of(spec) == "explore"


def graduated_spec(spec: StrategySpec) -> StrategySpec:
    """An explore spec PROMOTED to the gate-lane after it cleared the honest gate — the only lane transition the
    vibe lane makes. Pure: returns a copy with lane='gate' (so the rest of the system treats it as a normal
    gate-lane survivor); a non-explore spec is returned unchanged. NEVER loosens anything — graduation happens
    only after `evaluate_by_lane`/`promote_cohort` already promoted the candidate on the unchanged 0.95 bar."""
    if lane_of(spec) != "explore":
        return spec
    return spec.model_copy(update={"lane": "gate"})
