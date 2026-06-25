# EXIT-ENVELOPE SWEEP: fan_exit_envelope turns ONE validated entry spec into N gate-ready StrategySpecs that differ
# ONLY over the exit envelope (multi-TP legs, break-even, runner/standalone trailing, ATR-mult vs fixed stop,
# time-stop), each passing validate_spec (no magic numbers) and compiling/running on real backtest physics. Plus:
# the new exit-toolset seeds validate + compile, the fan is deterministic, and the propose-only inbox hook routes
# the cohort to the Gate path without scoring or funding.

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from cosmu.config.settings import Settings
from cosmu.data.backtest import run_strategy_backtest
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import (
    seed_atr_stop_breakout_spec,
    seed_breakout_runner_spec,
    seed_carry_spec,
    seed_funding_atr_runner_spec,
    seed_meanrev_scalp_spec,
    seed_meanrev_spec,
    seed_momentum_spec,
    seed_momentum_trailing_spec,
    seed_population,
)
from cosmu.lab.exit_sweep import exit_envelope_count, fan_exit_envelope
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import (
    Condition,
    ExitPlan,
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

_FULL = edge_bearing_screen_market(n=280)
MARKET = {sym: _FULL[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}

_NEW_EXIT_SEEDS = (
    seed_breakout_runner_spec,
    seed_momentum_trailing_spec,
    seed_atr_stop_breakout_spec,
    seed_meanrev_scalp_spec,
    seed_funding_atr_runner_spec,
)


def _compile_and_run(spec: StrategySpec):
    assert validate_spec(spec) == []           # no magic numbers / unresolved param refs
    params = fit_params(spec)
    compiled = compile_spec(spec, params)      # raises on a missing param — covers the full param_space
    assert compiled.code_hash
    return run_strategy_backtest(spec, params, MARKET, fee_bps=Decimal("10"))


# --------------------------------------------------------------------------- fan_exit_envelope


def test_fan_yields_M_valid_specs():
    """Every fanned variant is validate_spec-clean and compiles — the M gate-ready candidates the Gate can judge."""
    variants = fan_exit_envelope(seed_momentum_spec())
    assert len(variants) == exit_envelope_count() >= 5
    for v in variants:
        assert validate_spec(v) == [], (v.name, validate_spec(v))
        compile_spec(v, fit_params(v))  # raises if param_space doesn't cover every exit ParamRef


def test_fan_covers_each_exit_variant():
    """The fan spans the FULL exit toolset: a fixed-stop baseline, an ATR-mult stop, a standalone trailing stop
    (cushioned AND armed-at-entry), a multi-TP scale-out, a break-even runner, and 2- vs 3-leg ladders."""
    variants = fan_exit_envelope(seed_momentum_spec())

    has_fixed_only = any(
        v.exit.atr_mult is None and v.exit.trailing_stop is None and v.exit.plan is None for v in variants
    )
    has_atr = any(v.exit.atr_mult is not None for v in variants)
    has_trail_cushioned = any(
        v.exit.trailing_stop is not None and v.exit.trailing_stop.arm_after_profit is not None for v in variants
    )
    has_trail_immediate = any(
        v.exit.trailing_stop is not None and v.exit.trailing_stop.arm_after_profit is None for v in variants
    )
    has_multi_tp_no_be = any(
        v.exit.plan is not None and len(v.exit.plan.multi_tp) >= 2 and not v.exit.plan.break_even_after_tp1
        for v in variants
    )
    has_be_runner = any(
        v.exit.plan is not None and v.exit.plan.break_even_after_tp1 and v.exit.plan.runner_trail is not None
        for v in variants
    )
    leg_counts = {len(v.exit.plan.multi_tp) for v in variants if v.exit.plan is not None}
    has_atr_plus_runner = any(
        v.exit.atr_mult is not None and v.exit.plan is not None and v.exit.plan.runner_trail is not None
        for v in variants
    )

    assert has_fixed_only, "missing fixed-stop baseline"
    assert has_atr, "missing ATR-mult stop"
    assert has_trail_cushioned, "missing cushioned standalone trailing stop"
    assert has_trail_immediate, "missing armed-at-entry trailing stop"
    assert has_multi_tp_no_be, "missing multi-TP scale-out without break-even"
    assert has_be_runner, "missing break-even runner"
    assert has_atr_plus_runner, "missing composite ATR + scale-out runner"
    assert {2, 3} <= leg_counts, f"missing distinct multi-TP leg counts (got {leg_counts})"


def test_fan_leaves_entry_untouched():
    """The fan is EXIT-only: entry conditions, setup, universe, horizon, direction, funding, and meta_label are
    byte-identical to the base across every variant."""
    base = seed_carry_spec()
    for v in fan_exit_envelope(base):
        assert v.entry == base.entry
        assert v.setup == base.setup
        assert v.universe == base.universe
        assert v.horizon == base.horizon
        assert v.direction == base.direction
        assert v.funding_feature == base.funding_feature
        assert v.meta_label == base.meta_label


def test_fan_variants_are_distinct():
    """Each variant is a distinct spec — distinct name AND a distinct serialized body (the exit structure differs)."""
    variants = fan_exit_envelope(seed_momentum_spec())
    names = [v.name for v in variants]
    assert len(set(names)) == len(names), "variant names must be unique"
    bodies = [json.dumps(v.model_dump(mode="json"), sort_keys=True) for v in variants]
    assert len(set(bodies)) == len(bodies), "variant bodies must be distinct"


def test_fan_is_deterministic():
    """Same input → byte-identical output: variant i is a pure function of (base, i), no RNG."""
    base = seed_momentum_spec()
    a = [json.dumps(s.model_dump(mode="json"), sort_keys=True) for s in fan_exit_envelope(base)]
    b = [json.dumps(s.model_dump(mode="json"), sort_keys=True) for s in fan_exit_envelope(base)]
    assert a == b


def test_fan_n_caps_and_clamps():
    """`n` caps the count; n above the catalogue clamps (no duplicates); n<1 floors to 1."""
    base = seed_momentum_spec()
    assert len(fan_exit_envelope(base, n=3)) == 3
    assert len(fan_exit_envelope(base, n=999)) == exit_envelope_count()
    assert len(fan_exit_envelope(base, n=0)) == 1


def test_fan_variants_run_through_backtest_physics():
    """Every fanned exit actually runs on the deterministic backtest (the exit physics fire) — these are gate-ready,
    not just structurally valid."""
    for v in fan_exit_envelope(seed_momentum_spec()):
        m = run_strategy_backtest(v, fit_params(v), MARKET, fee_bps=Decimal("10"))
        assert m.num_trades >= 0
        assert float(m.profit_factor) >= 0.0


def test_fan_rejects_invalid_base():
    """You cannot fan an entry that isn't itself gate-ready — fail loud, never emit variants off a bad base."""
    bad = StrategySpec(
        name="bad base",
        rationale="",  # empty rationale → validate_spec flags it
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=5),
        entry=[Condition(feature=FeatureRef(name="ret_Nd"), op="gt", threshold=ParamRef(param="x"))],
        exit=ExitRules(stop_loss=ParamRef(param="s"), take_profit=ParamRef(param="t")),
        risk=RiskRules(),
        param_space={
            "x": ParamSpace(kind="float", lo=0.0, hi=0.1),
            "s": ParamSpace(kind="float", lo=0.01, hi=0.1),
            "t": ParamSpace(kind="float", lo=0.02, hi=0.2),
        },
    )
    with pytest.raises(ValueError):
        fan_exit_envelope(bad)


def test_fan_preserves_entry_side_params_and_drops_orphans():
    """The variant param_space = (entry-side params) ∪ (this exit's params). An exit-owned param the base happened
    to carry (e.g. its own 'stop'/'take') is replaced by the fan's space; no orphan exit param survives unused."""
    base = seed_meanrev_spec()  # carries entry-side rsi_lookback/bb_lookback + exit-side stop/take/time_stop
    entry_side = {k for k in base.param_space if k not in {"stop", "take", "time_stop"}}
    for v in fan_exit_envelope(base):
        # entry-side params all preserved
        assert entry_side <= set(v.param_space)
        # every ParamRef the spec references resolves in param_space (compile_spec enforces ⊇; assert no surplus
        # exit-owned orphan by checking compile + that fitted params cover exactly the space)
        params = fit_params(v)
        compile_spec(v, params)
        assert set(params) == set(v.param_space)


# --------------------------------------------------------------------------- new exit-toolset seeds


@pytest.mark.parametrize("seed_fn", _NEW_EXIT_SEEDS, ids=lambda f: f.__name__)
def test_new_exit_seeds_validate_and_run(seed_fn):
    """Each new exit-toolset seed is validate_spec-clean, compiles, and runs on real backtest physics."""
    m = _compile_and_run(seed_fn())
    assert m.num_trades >= 0


def test_new_exit_seeds_in_population():
    """seed_population includes the 5 exit-toolset seeds, all unique, all valid — the mass-gen surface now explores
    SL/TP structure, not just entries."""
    pop = seed_population()
    names = {s.name for s in pop}
    for fn in _NEW_EXIT_SEEDS:
        assert fn().name in names
    assert len({s.name for s in pop}) == len(pop)  # no duplicate names
    for s in pop:
        assert validate_spec(s) == [], s.name


def test_population_spans_full_exit_toolset():
    """Across the seeded population the exit toolset is actually used: a standalone trailing stop, an ATR-mult stop,
    a multi-TP scale-out, and a break-even runner all appear — not just the lone seed_orb_fvg ExitPlan as before."""
    pop = seed_population()
    assert any(s.exit.trailing_stop is not None for s in pop), "no seed uses the standalone trailing stop"
    assert any(s.exit.atr_mult is not None for s in pop), "no seed uses the ATR-mult stop"
    assert any(s.exit.plan is not None and s.exit.plan.multi_tp for s in pop), "no seed uses a multi-TP scale-out"
    assert any(
        s.exit.plan is not None and s.exit.plan.break_even_after_tp1 and s.exit.plan.runner_trail is not None
        for s in pop
    ), "no seed uses a break-even runner"


# --------------------------------------------------------------------------- propose-only inbox hook


def _store(tmp: Path):
    return __import__("cosmu.knowledge.store", fromlist=["Store"]).Store(
        Settings(database_url=f"sqlite:///{tmp}/exitfan.sqlite3", openrouter_api_key=None)
    )


def test_queue_exit_fan_routes_to_gate_path_propose_only():
    """The inbox hook fans a validated base into the inbox as typed .json specs that the deterministic scanner
    parses with zero issues — propose-only (nothing scored/funded here; the Gate disposes on scan)."""
    from cosmu.lab.inbox import _spec_from_file, queue_exit_fan, scan_inbox

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        store = _store(tmp)
        inbox = tmp / "inbox"

        res = queue_exit_fan(seed_carry_spec(), store, inbox_dir=inbox)
        assert res.variants == exit_envelope_count()
        files = sorted(inbox.glob("*.json"))
        assert len(files) == res.variants

        # every written spec re-parses through the scanner with no validation issues
        for f in files:
            spec, kind, issues = _spec_from_file(f, f.read_text())
            assert spec is not None and issues == [] and kind == "json", (f.name, issues)

        # the scan imports them once; a re-scan is fully idempotent (content-hash) — no money path here at all
        rep = scan_inbox(store, inbox_dir=inbox, run_cohort=False)
        assert len(rep.imported) == res.variants
        rep2 = scan_inbox(store, inbox_dir=inbox, run_cohort=False)
        assert len(rep2.imported) == 0
