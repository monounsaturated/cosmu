# intent: the self-reinforcing core — isolate a GATE-PASSED strategy's winning SIGNAL logic (its entry
# conditions + entry-setup modules + the param_space ranges they reference), then GRAFT that logic onto OTHER
# assets in the universe and RECOMBINE it with other survivors' modules to emit a COHORT of fresh StrategySpecs;
# inputs: one gate-passed survivor's spec (+ optional sibling survivors to mix with) + a seeded RNG;
# outputs: a deterministic list of derived specs; invariants: thresholds stay ParamRefs (no magic numbers leak —
# every grafted condition's param keeps the parent's fitted range), generation is seeded/reproducible, and the
# cohort is NEVER judged here — it is handed to the EXISTING FarmLoop screen+score+FDR path (the LLM/this code
# never decides edge; volume can't manufacture a winner because FDR is the brake on the whole family).

from __future__ import annotations

import random
from dataclasses import dataclass, field

from cosmu.config.feature_registry import features_for
from cosmu.strategy.spec import (
    Condition,
    EntrySetup,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)
from cosmu.strategy.static_check import validate_spec

# Asset class → its default venue, so a grafted universe is internally consistent (the screen prices fees
# against spec.universe.venues). Mirrors the map the mutator's cross-market operators already use.
_VENUE_FOR_CLASS: dict[str, str] = {
    "crypto": "binance",
    "equity": "ibkr",
    "fx": "ibkr",
    "prediction": "polymarket",
}

# The asset classes a winning signal may be grafted onto. crypto is the binding/home market (spot-only); the
# others let a proven edge be transferred where its features still resolve (the registry decides per class).
_GRAFT_CLASSES: tuple[str, ...] = ("crypto", "equity", "prediction")

# Exit/risk plumbing a graft needs to be a complete, screenable spec. RANGES (not values) — the Finder fits
# them, exactly like the seeds. Nothing is hardcoded into the signal; these are the same neutral ranges the
# seeder uses for stop/take/time_stop.
_GRAFT_EXIT_RANGES: tuple[tuple[str, ParamSpace], ...] = (
    ("stop", ParamSpace(kind="float", lo=0.02, hi=0.12)),
    ("take", ParamSpace(kind="float", lo=0.04, hi=0.24)),
    ("time_stop", ParamSpace(kind="int", lo=3, hi=21, step=1)),
)


@dataclass(frozen=True)
class WinningLogic:
    """The isolated, transferable signal core of a gate-passed survivor — the part that expresses the EDGE
    (what to buy), kept separate from the universe (where) and the exit/risk plumbing (how to manage). Carries
    only the param_space entries its own conditions/setup reference, so a graft stays a valid, magic-number-free
    spec wherever it lands."""

    name: str
    rationale: str
    entry: list[Condition]
    setup: EntrySetup | None
    param_space: dict[str, ParamSpace]  # subset of the parent's space: only keys the entry/setup reference


def isolate_winning_logic(spec: StrategySpec) -> WinningLogic:
    """Pull a survivor's SIGNAL out of its full spec: the entry conditions + entry-setup modules and ONLY the
    param_space entries they reference. Deep-copied so grafts never alias the parent. This is the unit the
    flywheel replicates — the 'winning logic' the goal calls out, isolated from venue/exit/risk."""
    entry = [c.model_copy(deep=True) for c in spec.entry]
    setup = spec.setup.model_copy(deep=True) if spec.setup is not None else None
    needed = _signal_param_keys(entry, setup)
    sub = {k: spec.param_space[k].model_copy(deep=True) for k in needed if k in spec.param_space}
    return WinningLogic(name=spec.name, rationale=spec.rationale, entry=entry, setup=setup, param_space=sub)


def _signal_param_keys(entry: list[Condition], setup: EntrySetup | None) -> set[str]:
    """The param_space keys referenced by a signal's entry conditions + entry-setup modules (so a graft carries
    exactly the fitted ranges it needs — no orphan params, no magic numbers)."""
    keys: set[str] = {c.threshold.param for c in entry}
    for c in entry:
        if isinstance(c.feature.lookback, ParamRef):
            keys.add(c.feature.lookback.param)
    if setup is not None:
        if setup.ma_trend_filter is not None:
            keys.add(setup.ma_trend_filter.ma_lookback.param)
        if setup.orb is not None:
            keys.update({setup.orb.range_bars.param, setup.orb.buffer.param})
        if setup.fvg is not None:
            keys.update({setup.fvg.max_retests.param, setup.fvg.gap_min.param})
    return keys


def _universe_for(asset_class: str) -> UniverseSelector:
    return UniverseSelector(
        venues=[_VENUE_FOR_CLASS[asset_class]],
        asset_classes=[asset_class],
        min_liquidity_usd=2_000_000,
        min_instruments=5,
    )


def _retarget_features(entry: list[Condition], asset_class: str) -> tuple[list[Condition], bool]:
    """Re-point any entry feature that is NOT valid for `asset_class` onto a deterministic in-class fallback
    (the registry decides what's valid per class). Returns the retargeted conditions and whether the signal
    still carries at least one of its ORIGINAL features (a graft that had to replace every feature has lost the
    edge and should be dropped). Entry-setup modules are price-only, so they transfer unchanged."""
    valid = {f.name for f in features_for([asset_class])}
    fallback = sorted(valid)[0] if valid else "ret_Nd"
    out: list[Condition] = []
    kept_original = False
    for cond in entry:
        c = cond.model_copy(deep=True)
        if c.feature.name in valid:
            kept_original = True
        else:
            c.feature = FeatureRef(name=fallback, lookback=c.feature.lookback)
        out.append(c)
    return out, kept_original


def _graft(logic: WinningLogic, asset_class: str, *, tag: str) -> StrategySpec | None:
    """Graft an isolated signal onto one asset class, pairing it with minimal, fully-parametrised exit/risk
    plumbing (every threshold a ParamRef → no magic numbers). Returns None if the graft can't keep any of the
    signal's original features in the new class (edge lost) or fails static validation."""
    entry, kept = _retarget_features(logic.entry, asset_class)
    if not entry or not kept:
        return None
    space: dict[str, ParamSpace] = {k: v.model_copy(deep=True) for k, v in logic.param_space.items()}
    for key, ps in _GRAFT_EXIT_RANGES:
        space.setdefault(key, ps.model_copy(deep=True))
    spec = StrategySpec(
        name=f"{logic.name} -> {asset_class} [{tag}]",
        rationale=(
            f"Graft of the gate-passed signal '{logic.name}' onto {asset_class}: isolate the winning entry "
            f"logic and replicate it on a different market so the deterministic gate can re-judge it there. "
            f"Origin thesis: {logic.rationale}"
        ),
        universe=_universe_for(asset_class),
        horizon=Horizon(bar_size="4h", min_hold_days=2, max_hold_days=14),
        entry=entry,
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
        ),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.04, conviction=0.55),
        param_space=space,
        setup=logic.setup.model_copy(deep=True) if logic.setup is not None else None,
    )
    return spec if not validate_spec(spec) else None


def _recombine(logic: WinningLogic, partner: StrategySpec, *, tag: str) -> StrategySpec | None:
    """Mix the winner's SIGNAL with a sibling survivor's EXIT/RISK plumbing on the partner's universe: keep the
    proven entry edge, borrow how another survivor MANAGES the trade. Features are retargeted to the partner's
    asset class so the signal still resolves. Returns None on edge-loss or validation failure."""
    target_class = partner.universe.asset_classes[0] if partner.universe.asset_classes else "crypto"
    entry, kept = _retarget_features(logic.entry, target_class)
    if not entry or not kept:
        return None
    space: dict[str, ParamSpace] = {k: v.model_copy(deep=True) for k, v in logic.param_space.items()}
    exit_plan = partner.exit.model_copy(deep=True)
    # Carry the partner's exit param ranges so its borrowed exit/plan references resolve in the new spec.
    for ref in (exit_plan.stop_loss, exit_plan.take_profit, exit_plan.time_stop_days):
        if ref is not None and ref.param in partner.param_space:
            space.setdefault(ref.param, partner.param_space[ref.param].model_copy(deep=True))
    for cond in exit_plan.signal_exits:
        if cond.threshold.param in partner.param_space:
            space.setdefault(cond.threshold.param, partner.param_space[cond.threshold.param].model_copy(deep=True))
    if exit_plan.plan is not None:
        for leg in exit_plan.plan.multi_tp:
            for ref in (leg.at, leg.size_pct):
                if ref.param in partner.param_space:
                    space.setdefault(ref.param, partner.param_space[ref.param].model_copy(deep=True))
        rt = exit_plan.plan.runner_trail
        if rt is not None and rt.param in partner.param_space:
            space.setdefault(rt.param, partner.param_space[rt.param].model_copy(deep=True))
    spec = StrategySpec(
        name=f"{logic.name} x {partner.name} [{tag}]",
        rationale=(
            f"Recombine the gate-passed signal '{logic.name}' with the exit/risk plumbing of survivor "
            f"'{partner.name}': proven entry edge, a different trade-management style — re-judged by the gate."
        ),
        universe=partner.universe.model_copy(deep=True),
        horizon=partner.horizon.model_copy(deep=True),
        entry=entry,
        exit=exit_plan,
        risk=partner.risk.model_copy(deep=True),
        param_space=space,
        setup=logic.setup.model_copy(deep=True) if logic.setup is not None else None,
    )
    return spec if not validate_spec(spec) else None


@dataclass
class EvolvedCohort:
    """The deterministic output of evolving one survivor: the grafted/recombined specs to hand to the gate,
    plus a record of which classes/partners they came from (for the event log / debugging — never a verdict)."""

    parent_name: str
    specs: list[StrategySpec] = field(default_factory=list)
    grafts: int = 0
    recombinations: int = 0
    dropped: int = 0  # grafts/mixes that lost the edge (no original feature survived) or failed validation


def evolve_survivor(
    survivor: StrategySpec,
    *,
    siblings: list[StrategySpec] | None = None,
    seed: int = 7,
    max_specs: int = 16,
    rank: dict[str, float] | None = None,
) -> EvolvedCohort:
    """ENTRY FUNCTION. Take ONE gate-passed survivor, isolate its winning signal logic, and deterministically
    generate a cohort of derived specs that (a) GRAFT that logic onto other asset classes in the universe and
    (b) RECOMBINE it with other survivors' exit/risk plumbing. Pure + seeded: same inputs -> same cohort. Does
    NOT screen, score, or gate anything — call `run_evolution_cohort` (or pass `.specs` to
    `FarmLoop.run_cohort(extra_seeds=...)`) to route the cohort through the EXISTING gate. The gate alone judges
    edge; FDR across the whole family is the brake on volume."""
    rng = random.Random(seed)
    logic = isolate_winning_logic(survivor)
    home_class = survivor.universe.asset_classes[0] if survivor.universe.asset_classes else "crypto"
    cohort = EvolvedCohort(parent_name=survivor.name)
    seen: set[str] = set()

    def _add(spec: StrategySpec | None, *, graft: bool) -> None:
        if spec is None:
            cohort.dropped += 1
            return
        if spec.name in seen or len(cohort.specs) >= max_specs:
            return
        seen.add(spec.name)
        cohort.specs.append(spec)
        if graft:
            cohort.grafts += 1
        else:
            cohort.recombinations += 1

    # (a) GRAFT the winning logic onto every OTHER asset class in the graft set (deterministic order), plus a
    # same-class replicate so the home market also gets a fresh, gate-re-judged copy of the isolated edge.
    graft_targets = [home_class] + [c for c in _GRAFT_CLASSES if c != home_class]
    for asset_class in graft_targets:
        _add(_graft(logic, asset_class, tag=f"graft-{rng.randint(1000, 9999)}"), graft=True)

    # (b) RECOMBINE with sibling survivors' exit/risk plumbing — proven entry, borrowed management. Deterministic
    # order: by descending block-registry strength when a `rank` is provided (the observed funded-rate of each
    # partner's exit/sizing blocks — observational, the Gate still judges every output), name as tie-break and
    # as the only key when no rank exists. Same inputs + same DB state -> same cohort.
    partner_rank = rank or {}
    for partner in sorted(siblings or [], key=lambda s: (-partner_rank.get(s.name, 0.0), s.name)):
        if partner.name == survivor.name:
            continue
        _add(_recombine(logic, partner, tag=f"mix-{rng.randint(1000, 9999)}"), graft=False)

    return cohort


def run_evolution_cohort(
    farm_loop,  # noqa: ANN001 — cosmu.evolution.loop.FarmLoop; untyped to avoid an import cycle
    survivor: StrategySpec,
    *,
    siblings: list[StrategySpec] | None = None,
    seed: int = 7,
    max_specs: int = 16,
):  # noqa: ANN201 — returns cosmu.evolution.loop.CohortSummary
    """Glue: evolve a survivor into a cohort, then route it through the EXISTING FarmLoop gate path. The evolved
    specs enter as `extra_seeds` with `explore_pct=0.0` (no wildcards — we are testing THIS edge's grafts, not
    sampling noise). FarmLoop runs the SAME screen -> score() -> Benjamini-Hochberg FDR cull as every other
    cohort; nothing here re-implements or bypasses the gate/scorer/FDR. Returns the FarmLoop CohortSummary.

    Partner ordering: when the block registry is available on the farm_loop's store, siblings whose exit/sizing
    blocks have historically been funded more often are recombined FIRST (so a capped cohort spends its slots
    on the empirically stronger plumbing). Observational re-ordering only — fail-open to name order."""
    from cosmu.knowledge.block_registry import partner_rank

    rank = partner_rank(farm_loop.store, siblings or [])
    cohort = evolve_survivor(survivor, siblings=siblings, seed=seed, max_specs=max_specs, rank=rank)
    if not cohort.specs:
        return farm_loop.run_cohort(seed=seed, cohort_size=1, explore_pct=0.0)
    return farm_loop.run_cohort(
        seed=seed,
        cohort_size=len(cohort.specs),
        explore_pct=0.0,
        extra_seeds=cohort.specs,
    )
