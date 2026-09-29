# intent: fan ONE validated entry spec into N gate-ready StrategySpecs that differ ONLY over the EXIT envelope —
# multi-TP leg counts/levels, break-even on/off, runner/standalone trailing distances, ATR-mult vs fixed stop,
# time-stop ranges. inputs: a single validate_spec-clean StrategySpec; outputs: a list of typed StrategySpecs each
# passing validate_spec (every threshold a ParamRef in param_space — no magic numbers) and distinct/gate-ready.
# invariants: ENTRY is byte-identical across variants (entry conditions, setup, universe, horizon, direction,
# funding, meta_label untouched); DETERMINISTIC (variant i is a pure function of (base, i) — no RNG); PROPOSE-ONLY
# (this module never scores, promotes, or moves money — the deterministic Gate alone funds the fanned cohort).
#
# Why an exit-only fan: the operator's "fix one edge, fan the exit envelope" loop — once an ENTRY signal is found,
# the exit structure (where you stop, how you scale out, whether you trail) is a large, orthogonal design space
# that the seeder barely explores (only seed_orb_fvg emits a full ExitPlan). Holding the entry fixed and sweeping
# the exit turns one validated hypothesis into a whole gate-ready cohort, each judged BRUT on its own data.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.strategy.spec import (
    ExitPlan,
    ExitRules,
    ParamRef,
    ParamSpace,
    StrategySpec,
    TakeProfitLeg,
    TrailingStop,
)
from cosmu.strategy.static_check import validate_spec

# --------------------------------------------------------------------------- exit-envelope param names
# A FIXED namespace for every exit-side ParamRef the fan introduces. Kept disjoint from the base spec's entry-side
# params so a variant's param_space is exactly: (entry-side params carried over) ∪ (the exit params this variant
# uses). Deterministic names → deterministic config hashes downstream.
_PARAM_STOP = "stop"
_PARAM_TAKE = "take"
_PARAM_TIME_STOP = "time_stop"
_PARAM_ATR_MULT = "atr_mult"
_PARAM_TP1_AT = "tp1_at"
_PARAM_TP1_SIZE = "tp1_size"
_PARAM_TP2_AT = "tp2_at"
_PARAM_TP2_SIZE = "tp2_size"
_PARAM_TP3_AT = "tp3_at"
_PARAM_TP3_SIZE = "tp3_size"
_PARAM_RUNNER_TRAIL = "runner_trail"
_PARAM_TRAIL_DIST = "trail_dist"
_PARAM_TRAIL_ARM = "trail_arm"

# The set of names this module OWNS — every variant's param_space starts from the base's params with ALL of these
# stripped, then re-adds exactly the ones the variant uses. So an entry-side param named e.g. 'stop' on the base
# spec is replaced by the fan's own 'stop' space (the exit lives here now), and no orphan exit param survives.
_OWNED_PARAMS = frozenset(
    {
        _PARAM_STOP,
        _PARAM_TAKE,
        _PARAM_TIME_STOP,
        _PARAM_ATR_MULT,
        _PARAM_TP1_AT,
        _PARAM_TP1_SIZE,
        _PARAM_TP2_AT,
        _PARAM_TP2_SIZE,
        _PARAM_TP3_AT,
        _PARAM_TP3_SIZE,
        _PARAM_RUNNER_TRAIL,
        _PARAM_TRAIL_DIST,
        _PARAM_TRAIL_ARM,
    }
)

# Canonical fitted ranges for each exit param — the SAME shape the seeder uses (fractions of price for stop/take/
# trails, ATR multiples for atr_mult, integer days for the time stop). The Finder/optimizer fits within these; no
# magic number reaches the price path (every value is a ParamRef into one of these spaces).
_SPACE: dict[str, ParamSpace] = {
    _PARAM_STOP: ParamSpace(kind="float", lo=0.02, hi=0.12),
    _PARAM_TAKE: ParamSpace(kind="float", lo=0.04, hi=0.30),
    _PARAM_TIME_STOP: ParamSpace(kind="int", lo=2, hi=21, step=1),
    _PARAM_ATR_MULT: ParamSpace(kind="float", lo=1.0, hi=5.0),
    _PARAM_TP1_AT: ParamSpace(kind="float", lo=0.02, hi=0.08),
    _PARAM_TP1_SIZE: ParamSpace(kind="float", lo=0.25, hi=0.60),
    _PARAM_TP2_AT: ParamSpace(kind="float", lo=0.08, hi=0.20),
    _PARAM_TP2_SIZE: ParamSpace(kind="float", lo=0.20, hi=0.50),
    _PARAM_TP3_AT: ParamSpace(kind="float", lo=0.18, hi=0.40),
    _PARAM_TP3_SIZE: ParamSpace(kind="float", lo=0.15, hi=0.40),
    _PARAM_RUNNER_TRAIL: ParamSpace(kind="float", lo=0.02, hi=0.10),
    _PARAM_TRAIL_DIST: ParamSpace(kind="float", lo=0.02, hi=0.12),
    _PARAM_TRAIL_ARM: ParamSpace(kind="float", lo=0.01, hi=0.10),
}


@dataclass(frozen=True)
class _Envelope:
    """One concrete EXIT structure: the slug that tags the variant, the ExitRules it builds, and the exit params it
    introduces (so the variant's param_space carries exactly those, no orphans)."""

    slug: str
    label: str
    exit: ExitRules
    params: frozenset[str]


# --------------------------------------------------------------------------- the envelope catalogue
# Each builder returns ONE _Envelope. Time-stop is layered on independently below (a second axis), so these focus on
# the stop/take/scale-out structure. Every threshold is a ParamRef — the structure is fixed here, the LEVELS are fit.


def _env_fixed_baseline() -> _Envelope:
    """Plain fixed-% stop + single take. The control: the exit toolset's null structure (every existing simple
    seed). Fans the levels only — a useful baseline cell the Gate can rank the richer exits against."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
    )
    return _Envelope("fixed", "fixed stop + single TP", rules, frozenset({_PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP}))


def _env_atr_stop() -> _Envelope:
    """ATR-multiple initial stop (volatility-scaled) + single take. The stop distance adapts to each asset's ATR at
    entry instead of a fixed fraction — the structural alternative to a flat stop."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),  # still the warm-up / no-ATR fallback
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        atr_mult=ParamRef(param=_PARAM_ATR_MULT),
    )
    return _Envelope(
        "atr_stop", "ATR-mult stop + single TP", rules,
        frozenset({_PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_ATR_MULT}),
    )


def _env_trailing() -> _Envelope:
    """STANDALONE trailing stop armed after a profit cushion — no scale-out, the whole position rides the trail once
    it is in the money. Asymmetric: tight trailing risk, open-ended upside."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        trailing_stop=TrailingStop(distance=ParamRef(param=_PARAM_TRAIL_DIST), arm_after_profit=ParamRef(param=_PARAM_TRAIL_ARM)),
    )
    return _Envelope(
        "trailing", "standalone trailing stop", rules,
        frozenset({_PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_TRAIL_DIST, _PARAM_TRAIL_ARM}),
    )


def _env_trailing_immediate() -> _Envelope:
    """STANDALONE trailing stop armed IMMEDIATELY at entry (no profit cushion) — a tighter, always-on trail. The
    arm_after_profit=None lane of the trailing tool, distinct from the cushioned variant above."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        trailing_stop=TrailingStop(distance=ParamRef(param=_PARAM_TRAIL_DIST)),  # arm at entry
    )
    return _Envelope(
        "trailing_immediate", "trailing stop armed at entry", rules,
        frozenset({_PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_TRAIL_DIST}),
    )


def _env_multi_tp_2() -> _Envelope:
    """Two-leg scale-out (multi-TP) WITHOUT break-even — bank partial profit in two legs, the rest exits on the
    fixed stop/take. The simplest partial-exit structure."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        plan=ExitPlan(
            multi_tp=[
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP1_AT), size_pct=ParamRef(param=_PARAM_TP1_SIZE)),
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP2_AT), size_pct=ParamRef(param=_PARAM_TP2_SIZE)),
            ],
            break_even_after_tp1=False,
        ),
    )
    return _Envelope(
        "multi_tp2", "2-leg scale-out (no break-even)", rules,
        frozenset({_PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_TP1_AT, _PARAM_TP1_SIZE, _PARAM_TP2_AT, _PARAM_TP2_SIZE}),
    )


def _env_multi_tp_2_be_runner() -> _Envelope:
    """Two-leg scale-out + break-even-after-TP1 + a runner trail — the asymmetric runner structure (bank TP1, move
    the stop to break-even, let the rest ride a trail). The classic 'free runner'."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        plan=ExitPlan(
            multi_tp=[
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP1_AT), size_pct=ParamRef(param=_PARAM_TP1_SIZE)),
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP2_AT), size_pct=ParamRef(param=_PARAM_TP2_SIZE)),
            ],
            break_even_after_tp1=True,
            runner_trail=ParamRef(param=_PARAM_RUNNER_TRAIL),
        ),
    )
    return _Envelope(
        "multi_tp2_be_runner", "2-leg scale-out + break-even + runner trail", rules,
        frozenset({
            _PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_TP1_AT, _PARAM_TP1_SIZE,
            _PARAM_TP2_AT, _PARAM_TP2_SIZE, _PARAM_RUNNER_TRAIL,
        }),
    )


def _env_multi_tp_3_be_runner() -> _Envelope:
    """Three-leg scale-out + break-even + runner trail — a finer scale-out ladder (three partials) than the two-leg
    runner, holding a smaller runner for longer. Distinct leg COUNT, same break-even-runner shape."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        plan=ExitPlan(
            multi_tp=[
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP1_AT), size_pct=ParamRef(param=_PARAM_TP1_SIZE)),
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP2_AT), size_pct=ParamRef(param=_PARAM_TP2_SIZE)),
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP3_AT), size_pct=ParamRef(param=_PARAM_TP3_SIZE)),
            ],
            break_even_after_tp1=True,
            runner_trail=ParamRef(param=_PARAM_RUNNER_TRAIL),
        ),
    )
    return _Envelope(
        "multi_tp3_be_runner", "3-leg scale-out + break-even + runner trail", rules,
        frozenset({
            _PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_TP1_AT, _PARAM_TP1_SIZE,
            _PARAM_TP2_AT, _PARAM_TP2_SIZE, _PARAM_TP3_AT, _PARAM_TP3_SIZE, _PARAM_RUNNER_TRAIL,
        }),
    )


def _env_atr_multi_tp_be_runner() -> _Envelope:
    """The full toolset in one cell: an ATR-multiple initial stop + two-leg scale-out + break-even + runner trail.
    Volatility-scaled risk with an asymmetric scale-out runner — the richest exit the toolset composes."""
    rules = ExitRules(
        stop_loss=ParamRef(param=_PARAM_STOP),
        take_profit=ParamRef(param=_PARAM_TAKE),
        time_stop_days=ParamRef(param=_PARAM_TIME_STOP),
        atr_mult=ParamRef(param=_PARAM_ATR_MULT),
        plan=ExitPlan(
            multi_tp=[
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP1_AT), size_pct=ParamRef(param=_PARAM_TP1_SIZE)),
                TakeProfitLeg(at=ParamRef(param=_PARAM_TP2_AT), size_pct=ParamRef(param=_PARAM_TP2_SIZE)),
            ],
            break_even_after_tp1=True,
            runner_trail=ParamRef(param=_PARAM_RUNNER_TRAIL),
        ),
    )
    return _Envelope(
        "atr_multi_tp_be_runner", "ATR-mult stop + 2-leg scale-out + break-even + runner trail", rules,
        frozenset({
            _PARAM_STOP, _PARAM_TAKE, _PARAM_TIME_STOP, _PARAM_ATR_MULT, _PARAM_TP1_AT, _PARAM_TP1_SIZE,
            _PARAM_TP2_AT, _PARAM_TP2_SIZE, _PARAM_RUNNER_TRAIL,
        }),
    )


# The ordered catalogue of distinct exit structures. ORDER IS STABLE — the fan walks it deterministically, so
# variant i is always the same structure for the same base spec. Each is a distinct, gate-ready exit design.
_ENVELOPE_BUILDERS = (
    _env_fixed_baseline,
    _env_atr_stop,
    _env_trailing,
    _env_trailing_immediate,
    _env_multi_tp_2,
    _env_multi_tp_2_be_runner,
    _env_multi_tp_3_be_runner,
    _env_atr_multi_tp_be_runner,
)


def exit_envelope_count() -> int:
    """How many distinct exit structures the fan can produce (the natural N if `n` is left unbounded)."""
    return len(_ENVELOPE_BUILDERS)


# --------------------------------------------------------------------------- the fan


def _entry_side_param_space(base: StrategySpec) -> dict[str, ParamSpace]:
    """The base spec's param_space with every EXIT-owned param stripped — i.e. exactly the entry/setup/meta params
    the fan must carry forward unchanged. The exit params for each variant are layered back on top."""
    return {k: v for k, v in base.param_space.items() if k not in _OWNED_PARAMS}


def _build_variant(base: StrategySpec, env: _Envelope, *, index: int) -> StrategySpec:
    """One fanned spec: the base's ENTRY (conditions, setup, universe, horizon, direction, funding, meta_label)
    verbatim, this envelope's EXIT, and a param_space of (entry-side params) ∪ (this envelope's exit params)."""
    param_space = _entry_side_param_space(base)
    for name in env.params:
        param_space[name] = _SPACE[name]

    variant = base.model_copy(deep=True)
    variant.exit = env.exit.model_copy(deep=True)
    variant.param_space = param_space
    # A distinct, self-describing name + rationale so the cohort reads honestly on /lab and the de-dup/novelty
    # guards see N different specs (the EXIT structure is what differs — say so).
    variant.name = f"{base.name} · exit:{env.slug}"
    variant.rationale = (
        f"{(base.rationale or '').strip()} "
        f"[exit-envelope fan #{index}: {env.label}] — entry unchanged; only the exit structure varies so the "
        f"Gate can judge this stop/take/scale-out shape on its own data."
    ).strip()
    return variant


def fan_exit_envelope(base_spec: StrategySpec, *, n: int | None = None) -> list[StrategySpec]:
    """Fan ONE validated entry spec into a list of gate-ready StrategySpecs that differ ONLY over the exit envelope.

    The ENTRY is held byte-identical across every variant (entry conditions, setup, universe, horizon, direction,
    funding_feature, meta_label). Each variant carries a distinct exit structure drawn from the stable envelope
    catalogue — fixed/ATR stop, standalone trailing (cushioned + immediate), 2-/3-leg scale-out, break-even runner,
    and the full composite — with every threshold a ParamRef in a complete param_space (no magic numbers).

    Deterministic: variant i is a pure function of (base_spec, i) — no RNG, the catalogue order is fixed. `n` caps
    the count (defaults to the whole catalogue); n>catalogue is clamped to the catalogue (no duplicates).

    PROPOSE-ONLY: returns typed specs. It never scores, promotes, or funds — route the list through the existing
    deterministic Gate (e.g. the inbox cohort) to dispose. Raises ValueError if `base_spec` is not itself
    validate_spec-clean (you cannot fan an invalid entry).
    """
    base_issues = validate_spec(base_spec)
    if base_issues:
        raise ValueError(f"base_spec is not gate-ready (validate_spec issues): {base_issues}")

    count = exit_envelope_count() if n is None else max(1, min(int(n), exit_envelope_count()))
    out: list[StrategySpec] = []
    for index in range(count):
        env = _ENVELOPE_BUILDERS[index]()
        variant = _build_variant(base_spec, env, index=index)
        issues = validate_spec(variant)
        if issues:  # pragma: no cover — a builder bug; surface loudly rather than emit a bad spec
            raise ValueError(f"fanned variant '{variant.name}' failed validate_spec: {issues}")
        out.append(variant)
    return out
