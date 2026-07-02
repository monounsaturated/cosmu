# intent: catalog of deterministic mutation + wildcard operators that turn a parent StrategySpec into a child; inputs: parent spec(s) + seeded RNG; outputs: child spec + operator name + rationale; invariants: children stay structurally valid, thresholds remain ParamRefs, no hardcoded magic numbers leak in (operators adjust param_space ranges, never fix values).

from __future__ import annotations

import random
from dataclasses import dataclass

from cosmu.config.feature_registry import features_for
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)

BAR_SIZES = ["1h", "4h", "1d"]
ENTRY_OPS = ["gt", "gte", "lt", "lte", "cross_up", "cross_down"]


@dataclass(frozen=True)
class Child:
    spec: StrategySpec
    operator: str
    rationale: str


def _param_name(base: str, existing: set[str]) -> str:
    name = base
    i = 1
    while name in existing:
        i += 1
        name = f"{base}_{i}"
    return name


def _registry_feature_names(spec: StrategySpec) -> list[str]:
    return [f.name for f in features_for(spec.universe.asset_classes)]


# The learned-prior exploration FLOOR: every candidate feature keeps at least this share of the weight even if its
# prior is 0, so a feature the flywheel has never scored can never be sampled with probability 0 (the search must
# stay able to escape the basin the priors describe). Small relative to a strong prior (≈1.0) but strictly non-zero.
_PRIOR_FLOOR = 0.05


def _prior_weighted_choice(candidates: list[str], rng: random.Random, feature_priors: dict[str, float]) -> str:
    """Draw one feature from `candidates` with probability ∝ (floor + its learned prior). A feature the priors have
    never seen still carries `_PRIOR_FLOOR` weight (exploration floor: no feature is ever probability 0). Consumes
    EXACTLY ONE rng draw (rng.random()) so a caller's rng-draw accounting stays stable. `candidates` is assumed
    non-empty (callers guard that). Deterministic for a fixed rng + priors."""
    weights = [_PRIOR_FLOOR + max(0.0, float(feature_priors.get(name, 0.0))) for name in candidates]
    total = sum(weights)
    if total <= 0:  # defensive — the floor makes this unreachable, but never divide by zero
        return candidates[rng.randrange(len(candidates))]
    target = rng.random() * total
    upto = 0.0
    for name, w in zip(candidates, weights):
        upto += w
        if upto >= target:
            return name
    return candidates[-1]


# ---- exploit-lane operators (single-variable by default for clean attribution) ----


def swap_feature(spec: StrategySpec, rng: random.Random, *, feature_priors: dict[str, float] | None = None) -> Child:
    child = spec.model_copy(deep=True)
    pool = _registry_feature_names(child)
    if child.entry and pool:
        idx = rng.randrange(len(child.entry))
        current = child.entry[idx].feature.name
        candidates = [n for n in pool if n != current] or pool
        # DEFAULT (feature_priors is None): an unweighted rng.choice — byte-identical to the pre-prior behaviour.
        # STEERED: draw the replacement feature ∝ its learned prior (with the exploration floor); a single rng draw
        # either way, so the child count / downstream rng stream is unchanged only in the None path.
        new_feature = (
            rng.choice(candidates) if feature_priors is None else _prior_weighted_choice(candidates, rng, feature_priors)
        )
        child.entry[idx].feature = FeatureRef(name=new_feature, lookback=child.entry[idx].feature.lookback)
        rationale = f"swap entry feature {current}→{new_feature}"
    else:
        rationale = "swap_feature noop"
    child.name = f"{spec.name} · swap"
    return Child(spec=child, operator="swap_feature", rationale=rationale)


def _scale_param(space: ParamSpace, lo_mult: float, hi_mult: float) -> ParamSpace:
    new = space.model_copy(deep=True)
    if new.lo is not None:
        new.lo = round(new.lo * lo_mult, 6)
    if new.hi is not None:
        new.hi = round(new.hi * hi_mult, 6)
    if new.kind == "int":
        if new.lo is not None:
            new.lo = max(1, int(new.lo))
        if new.hi is not None and new.lo is not None:
            new.hi = max(int(new.lo) + 1, int(new.hi))
    return new


def widen_param(spec: StrategySpec, rng: random.Random) -> Child:
    child = spec.model_copy(deep=True)
    if child.param_space:
        key = rng.choice(list(child.param_space))
        child.param_space[key] = _scale_param(child.param_space[key], 0.6, 1.6)
        rationale = f"widen search range for {key}"
    else:
        rationale = "widen_param noop"
    child.name = f"{spec.name} · wide"
    return Child(spec=child, operator="widen_param", rationale=rationale)


def narrow_param(spec: StrategySpec, rng: random.Random) -> Child:
    child = spec.model_copy(deep=True)
    if child.param_space:
        key = rng.choice(list(child.param_space))
        child.param_space[key] = _scale_param(child.param_space[key], 1.15, 0.85)
        rationale = f"narrow search range for {key}"
    else:
        rationale = "narrow_param noop"
    child.name = f"{spec.name} · tight"
    return Child(spec=child, operator="narrow_param", rationale=rationale)


def tighten_risk(spec: StrategySpec, rng: random.Random) -> Child:
    child = spec.model_copy(deep=True)
    child.risk.max_position_pct = round(max(0.01, child.risk.max_position_pct * 0.75), 4)
    child.risk.max_concurrent_positions = max(1, child.risk.max_concurrent_positions - 1)
    child.name = f"{spec.name} · derisk"
    return Child(spec=child, operator="tighten_risk", rationale="reduce per-position size and concurrency")


def loosen_risk(spec: StrategySpec, rng: random.Random) -> Child:
    child = spec.model_copy(deep=True)
    child.risk.max_position_pct = round(min(0.10, child.risk.max_position_pct * 1.3), 4)
    child.risk.max_concurrent_positions = min(8, child.risk.max_concurrent_positions + 1)
    child.name = f"{spec.name} · press"
    return Child(spec=child, operator="loosen_risk", rationale="increase size/concurrency to press a working edge")


def change_horizon(spec: StrategySpec, rng: random.Random) -> Child:
    child = spec.model_copy(deep=True)
    child.horizon.bar_size = rng.choice(BAR_SIZES)
    shift = rng.choice([-2, -1, 1, 2])
    child.horizon.min_hold_days = max(1, child.horizon.min_hold_days + shift)
    child.horizon.max_hold_days = max(child.horizon.min_hold_days + 1, child.horizon.max_hold_days + shift * 2)
    child.name = f"{spec.name} · {child.horizon.bar_size}"
    return Child(spec=child, operator="change_horizon", rationale="shift holding horizon / bar size")


def add_condition(spec: StrategySpec, rng: random.Random, *, feature_priors: dict[str, float] | None = None) -> Child:
    child = spec.model_copy(deep=True)
    pool = _registry_feature_names(child)
    used = {c.feature.name for c in child.entry}
    candidates = [n for n in pool if n not in used] or pool
    if candidates:
        # DEFAULT: unweighted rng.choice (byte-identical). STEERED: draw the confluence feature ∝ its learned prior
        # (floor-guarded) — one rng draw either way.
        feature = rng.choice(candidates) if feature_priors is None else _prior_weighted_choice(candidates, rng, feature_priors)
        pname = _param_name(f"th_{feature}", set(child.param_space))
        child.entry.append(
            Condition(feature=FeatureRef(name=feature), op=rng.choice(["gt", "lt"]), threshold=ParamRef(param=pname))
        )
        child.param_space[pname] = ParamSpace(kind="float", lo=-1.0, hi=1.0)
        rationale = f"add confluence condition on {feature}"
    else:
        rationale = "add_condition noop"
    child.name = f"{spec.name} · +filter"
    return Child(spec=child, operator="add_condition", rationale=rationale)


def crossover(parent_a: StrategySpec, parent_b: StrategySpec, rng: random.Random) -> Child:
    """Two-parent recombination — flagged multi-variable (explore-leaning)."""
    child = parent_a.model_copy(deep=True)
    child.exit = parent_b.exit.model_copy(deep=True)
    # carry over the exit's params so references resolve
    for cond in [*parent_b.exit.signal_exits]:
        if cond.threshold.param not in child.param_space:
            child.param_space[cond.threshold.param] = ParamSpace(kind="float", lo=-1.0, hi=1.0)
    for ref in (parent_b.exit.stop_loss, parent_b.exit.take_profit, parent_b.exit.time_stop_days):
        if ref and ref.param not in child.param_space:
            kind = "int" if ref is parent_b.exit.time_stop_days else "float"
            child.param_space[ref.param] = (
                ParamSpace(kind="int", lo=2, hi=21, step=1)
                if kind == "int"
                else ParamSpace(kind="float", lo=0.02, hi=0.2)
            )
    if child.exit.plan:
        for leg in child.exit.plan.multi_tp:
            for ref in (leg.at, leg.size_pct):
                if ref.param not in child.param_space:
                    child.param_space[ref.param] = ParamSpace(kind="float", lo=0.02, hi=0.3)
        if child.exit.plan.runner_trail and child.exit.plan.runner_trail.param not in child.param_space:
            child.param_space[child.exit.plan.runner_trail.param] = ParamSpace(kind="float", lo=0.02, hi=0.1)
    child.name = f"{parent_a.name} × {parent_b.name}"
    return Child(spec=child, operator="crossover", rationale=f"recombine entry of '{parent_a.name}' with exit of '{parent_b.name}'")


EXPLOIT_OPERATORS = [
    swap_feature,
    widen_param,
    narrow_param,
    tighten_risk,
    loosen_risk,
    change_horizon,
    add_condition,
]

# The operators that SELECT a feature from the registry — the only ones the learned feature_priors can steer.
_FEATURE_OPERATORS = (swap_feature, add_condition)

# "Refine" operators keep the parent's structure and tune it in place (a high-survival parent is worth refining);
# "escape" operators change the parent's shape — feature/horizon/confluence (a low-survival parent is worth
# escaping from). Ordering matches EXPLOIT_OPERATORS above; each op is in exactly one bucket.
_REFINE_OPERATORS = (widen_param, narrow_param, tighten_risk, loosen_risk)
_ESCAPE_OPERATORS = (swap_feature, change_horizon, add_condition)


def _survival_biased_operator(rng: random.Random, survival: float):  # noqa: ANN202 — returns one operator callable
    """Pick an exploit operator, biased by the parent's survival score in [0,1]. High survival → weight the REFINE
    operators (tune the winner in place); low survival → weight the ESCAPE operators (change its shape to break out
    of a losing basin). Never zeroes either bucket (both stay reachable). Only reached when survival is not None, so
    the None default keeps its original single rng.choice draw. Consumes one rng draw (rng.random())."""
    s = max(0.0, min(1.0, float(survival)))
    # refine share rises with survival (0.3 → 0.7 across s∈[0,1]); both buckets always keep weight.
    refine_share = 0.3 + 0.4 * s
    bucket = _REFINE_OPERATORS if rng.random() < refine_share else _ESCAPE_OPERATORS
    return bucket[rng.randrange(len(bucket))]


def mutate_exploit(
    parent: StrategySpec,
    rng: random.Random,
    *,
    feature_priors: dict[str, float] | None = None,
    survival: float | None = None,
) -> Child:
    """Single-operator child for clean causal attribution.

    Two OPTIONAL steering inputs let the autonomous search COMPOUND instead of re-searching blind noise:
      - `feature_priors` (feature → learned grade): when given, feature-selecting operators draw features ∝ their
        prior, with an exploration floor so no feature is ever probability 0.
      - `survival` (the parent's edge-persistence score in [0,1]): when given, biases the operator choice — a
        high-survival parent is REFINED in place, a low-survival one is ESCAPED from (its shape is changed).

    INVARIANT: when BOTH steering inputs are None this is BYTE-IDENTICAL to the pre-steering behaviour — the same
    `rng.choice(EXPLOIT_OPERATORS)` draw, then the operator called with no priors → the exact same output. The
    compounding paths only activate when the caller passes real learned signal (offline/cold-start → None → old)."""
    if survival is None:
        op = rng.choice(EXPLOIT_OPERATORS)
    else:
        op = _survival_biased_operator(rng, survival)
    # Only the feature-selecting operators can consume priors; passing the kwarg to them (and NOT to the others)
    # keeps every other operator's signature + rng stream untouched.
    if feature_priors is not None and op in _FEATURE_OPERATORS:
        return op(parent, rng, feature_priors=feature_priors)
    return op(parent, rng)


# ---- explore / wildcard generators (deliberately high-variance, multi-variable allowed) ----


def _random_universe(rng: random.Random) -> UniverseSelector:
    classes = rng.choice([["crypto"], ["equity"], ["crypto", "equity"], ["prediction"]])
    venue_map = {"crypto": "binance", "equity": "ibkr", "prediction": "polymarket"}
    venues = sorted({venue_map[c] for c in classes})
    return UniverseSelector(venues=venues, asset_classes=classes, min_liquidity_usd=2_000_000, min_instruments=5)


def _fresh_param_space(names: list[str], rng: random.Random) -> dict[str, ParamSpace]:
    space: dict[str, ParamSpace] = {}
    for n in names:
        space[n] = ParamSpace(kind="float", lo=round(rng.uniform(-1.0, 0.0), 3), hi=round(rng.uniform(0.0, 1.0) + 0.1, 3))
    space["stop"] = ParamSpace(kind="float", lo=0.02, hi=0.12)
    space["take"] = ParamSpace(kind="float", lo=0.04, hi=0.24)
    space["time_stop"] = ParamSpace(kind="int", lo=3, hi=21, step=1)
    return space


def random_feature_combo(rng: random.Random, universe: UniverseSelector | None = None) -> Child:
    uni = universe or _random_universe(rng)
    pool = [f.name for f in features_for(uni.asset_classes)] or ["ret_Nd", "rsi"]
    k = rng.randint(2, min(4, len(pool)))
    chosen = rng.sample(pool, k)
    entry = [
        Condition(feature=FeatureRef(name=name), op=rng.choice(ENTRY_OPS), threshold=ParamRef(param=f"th_{i}"))
        for i, name in enumerate(chosen)
    ]
    space = _fresh_param_space([f"th_{i}" for i in range(len(chosen))], rng)
    spec = StrategySpec(
        name="Wildcard feature combo",
        rationale="Novel confluence of features sampled across the registry to escape local optima.",
        universe=uni,
        horizon=Horizon(bar_size=rng.choice(BAR_SIZES), min_hold_days=rng.randint(1, 4), max_hold_days=rng.randint(8, 20)),
        entry=entry,
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=rng.randint(2, 5), max_position_pct=round(rng.uniform(0.02, 0.06), 3), conviction=round(rng.uniform(0.4, 0.7), 2)),
        param_space=space,
    )
    return Child(spec=spec, operator="random_feature_combo", rationale=f"sampled {k} features: {', '.join(chosen)}")


def cross_market_transfer(parent: StrategySpec, rng: random.Random) -> Child:
    child = parent.model_copy(deep=True)
    target = rng.choice([["equity"], ["crypto"], ["prediction"]])
    venue_map = {"crypto": "binance", "equity": "ibkr", "prediction": "polymarket"}
    child.universe = UniverseSelector(
        venues=sorted({venue_map[c] for c in target}),
        asset_classes=target,
        min_liquidity_usd=2_000_000,
        min_instruments=5,
    )
    # retarget any entry feature not valid for the new asset class
    valid = {f.name for f in features_for(target)}
    fallback = sorted(valid)[0] if valid else "ret_Nd"
    for cond in child.entry:
        if cond.feature.name not in valid:
            cond.feature = FeatureRef(name=fallback)
    child.name = f"{parent.name} → {target[0]}"
    return Child(spec=child, operator="cross_market_transfer", rationale=f"port signal to {target[0]} market")


def novel_hypothesis(rng: random.Random) -> Child:
    child = random_feature_combo(rng)
    spec = child.spec.model_copy(deep=True)
    spec.name = "Frontier novel hypothesis"
    spec.rationale = "From-scratch low-prior thesis authored in the explore lane; sorted by the cheap screen + scorer, never judged at birth."
    return Child(spec=spec, operator="novel_hypothesis", rationale="fresh from-scratch spec on a low-prior thesis")


WILDCARD_GENERATORS = ["random_feature_combo", "cross_market_transfer", "novel_hypothesis", "bold_recombination"]


def wildcard(parents: list[StrategySpec], rng: random.Random) -> Child:
    choice = rng.choice(WILDCARD_GENERATORS)
    if choice == "random_feature_combo" or not parents:
        return random_feature_combo(rng)
    if choice == "cross_market_transfer":
        return cross_market_transfer(rng.choice(parents), rng)
    if choice == "novel_hypothesis":
        return novel_hypothesis(rng)
    # bold_recombination: multi-block crossover of two random parents
    if len(parents) >= 2:
        a, b = rng.sample(parents, 2)
        return crossover(a, b, rng)
    return random_feature_combo(rng)
