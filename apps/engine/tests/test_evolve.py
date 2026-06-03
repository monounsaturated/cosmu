# The self-reinforcing core: isolate a gate-passed survivor's winning signal, graft it onto other assets and
# recombine it with other survivors, emit a COHORT, and route that cohort through the EXISTING FarmLoop gate
# (screen -> score -> Benjamini-Hochberg FDR). Offline + deterministic: same survivor + seed -> same cohort,
# every emitted spec is magic-number-free (validate_spec clean), and volume can't manufacture a winner because
# the gate/FDR — never this code — decides edge.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.evolve import (
    EvolvedCohort,
    evolve_survivor,
    isolate_winning_logic,
    run_evolution_cohort,
)
from cosmu.evolution.loop import FarmLoop
from cosmu.evolution.seeder import (
    seed_carry_spec,
    seed_meanrev_spec,
    seed_momentum_spec,
    seed_orb_fvg_spec,
    seed_population,
)
from cosmu.knowledge.store import Store
from cosmu.strategy.compiler import compile_spec
from cosmu.evolution.loop import fit_params
from cosmu.strategy.static_check import validate_spec


class FixtureProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self.bars[-limit:]


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/evolve.sqlite3"))


def _fixture_bars(count: int = 420, start: Decimal = Decimal("100")) -> list[Bar]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    price = start
    bars: list[Bar] = []
    for idx in range(count):
        cycle = Decimal(idx % 18)
        move = Decimal("0.012") if cycle < 9 else Decimal("-0.009")
        if idx % 53 == 0:
            move -= Decimal("0.035")
        open_ = price
        close = (price * (Decimal("1") + move)).quantize(Decimal("0.0001"))
        high = max(open_, close) * Decimal("1.006")
        low = min(open_, close) * Decimal("0.994")
        bars.append(
            Bar(
                ts=ts + timedelta(days=idx),
                open=open_,
                high=high.quantize(Decimal("0.0001")),
                low=low.quantize(Decimal("0.0001")),
                close=close,
                volume=Decimal("1000") + Decimal(idx),
            )
        )
        price = close
    return bars


# ---------------------------------------------------------------- isolation

def test_isolate_keeps_only_signal_params():
    spec = seed_momentum_spec()  # entry: ret_Nd (mom_lookback, mom_floor) + adx (adx_lookback, adx_floor)
    logic = isolate_winning_logic(spec)
    assert {c.feature.name for c in logic.entry} == {"ret_Nd", "adx"}
    # only the entry-referenced params come along — exit params (stop/take/time_stop) are NOT signal logic
    assert set(logic.param_space) == {"mom_lookback", "mom_floor", "adx_lookback", "adx_floor"}
    assert "stop" not in logic.param_space and "take" not in logic.param_space


def test_isolate_carries_setup_module_params():
    spec = seed_orb_fvg_spec()  # has a full EntrySetup (ma_trend_filter, orb, fvg)
    logic = isolate_winning_logic(spec)
    assert logic.setup is not None
    assert {"ma_lookback", "orb_range", "orb_buffer", "fvg_retests", "fvg_gap_min"} <= set(logic.param_space)


def test_isolate_does_not_alias_parent():
    spec = seed_carry_spec()
    logic = isolate_winning_logic(spec)
    logic.entry[0].feature = type(logic.entry[0].feature)(name="rsi")
    assert spec.entry[0].feature.name != "rsi"  # parent untouched (deep copy)


# ---------------------------------------------------------------- grafting

def test_graft_produces_other_asset_classes():
    spec = seed_momentum_spec()  # crypto+equity feature ret_Nd/adx; home class = crypto
    cohort = evolve_survivor(spec, seed=7)
    classes = {s.universe.asset_classes[0] for s in cohort.specs}
    # the signal is grafted onto multiple classes, not just its home market
    assert len(classes) >= 2
    assert "crypto" in classes


def test_every_emitted_spec_is_valid_and_compiles():
    # No magic numbers may leak in: validate_spec must be clean and the compiler must accept every graft/mix.
    survivors = seed_population()
    for survivor in survivors:
        cohort = evolve_survivor(survivor, siblings=survivors, seed=7)
        for derived in cohort.specs:
            assert validate_spec(derived) == [], f"{derived.name} failed static check"
            compile_spec(derived, fit_params(derived))  # must not raise


def test_graft_drops_when_edge_lost():
    # A crypto-only signal (funding_rate + perp_spot_basis) cannot survive a graft to prediction markets — none
    # of its features are valid there — so that graft is DROPPED, never emitted as a hollow spec.
    spec = seed_carry_spec()
    cohort = evolve_survivor(spec, seed=7)
    classes = {s.universe.asset_classes[0] for s in cohort.specs}
    assert "prediction" not in classes  # no crypto-funding feature resolves on prediction markets
    assert cohort.dropped >= 1


# ---------------------------------------------------------------- recombination

def test_recombine_borrows_partner_exit_keeps_signal_entry():
    survivor = seed_momentum_spec()
    partner = seed_orb_fvg_spec()  # has a multi-TP exit plan to borrow
    cohort = evolve_survivor(survivor, siblings=[partner], seed=7)
    mixes = [s for s in cohort.specs if " x " in s.name]
    assert mixes, "expected a recombination with the partner"
    mix = mixes[0]
    # entry edge is the survivor's; exit plumbing is the partner's (its TP plan came along)
    assert {c.feature.name for c in mix.entry} == {c.feature.name for c in survivor.entry}
    assert mix.exit.plan is not None  # borrowed the partner's multi-TP plan


def test_recombine_skips_self():
    survivor = seed_meanrev_spec()
    cohort = evolve_survivor(survivor, siblings=[survivor], seed=7)
    assert all(" x " not in s.name for s in cohort.specs)  # never recombines a survivor with itself


# ---------------------------------------------------------------- determinism

def test_evolution_is_deterministic():
    survivors = seed_population()
    a = evolve_survivor(survivors[3], siblings=survivors, seed=7)
    b = evolve_survivor(survivors[3], siblings=survivors, seed=7)
    assert [s.name for s in a.specs] == [s.name for s in b.specs]
    assert (a.grafts, a.recombinations, a.dropped) == (b.grafts, b.recombinations, b.dropped)


def test_sibling_order_does_not_change_cohort():
    survivors = seed_population()
    forward = evolve_survivor(survivors[3], siblings=survivors, seed=7)
    reverse = evolve_survivor(survivors[3], siblings=list(reversed(survivors)), seed=7)
    assert [s.name for s in forward.specs] == [s.name for s in reverse.specs]


def test_max_specs_caps_cohort():
    survivors = seed_population()
    cohort = evolve_survivor(survivors[0], siblings=survivors, seed=7, max_specs=4)
    assert len(cohort.specs) <= 4


# ---------------------------------------------------------------- routed through the EXISTING gate

def test_cohort_reaches_the_gate_via_farmloop(tmp_path):
    # The evolved cohort enters FarmLoop.run_cohort as extra_seeds and is judged by the SAME deterministic
    # screen -> score() -> FDR path. We assert it was screened (generated == cohort size) and that the gate —
    # not this code — decided survival (every graveyard row carries a kill reason).
    store = _store(tmp_path)
    loop = FarmLoop(settings=store.settings, store=store, market_data=FixtureProvider(_fixture_bars()))
    survivor = seed_momentum_spec()
    siblings = seed_population()
    cohort = evolve_survivor(survivor, siblings=siblings, seed=7)
    assert cohort.specs

    summary = run_evolution_cohort(loop, survivor, siblings=siblings, seed=7)
    # FarmLoop screens the standard seed population PLUS our evolved extra_seeds — the evolved family reaches the
    # gate alongside the seeds, never injected past it. So the screened count includes both.
    assert summary.generated == len(seed_population()) + len(cohort.specs)
    assert summary.lanes["chat"] == len(cohort.specs)  # evolved specs enter via the extra_seeds (chat) lane
    assert summary.lanes["explore"] == 0  # explore_pct=0.0 — no noise wildcards diluting the family
    for dead in summary.graveyard:
        assert dead.reasons  # the gate killed it with a reason; this code never judged edge


def test_fdr_can_demote_a_volume_inflated_evolution_cohort(tmp_path):
    # Volume can't manufacture a winner: routing a large evolved family still runs Benjamini-Hochberg FDR over
    # the WHOLE cohort. Most candidates on this fixture die at the gate — exactly the multiple-testing brake.
    store = _store(tmp_path)
    loop = FarmLoop(settings=store.settings, store=store, market_data=FixtureProvider(_fixture_bars()))
    survivors = seed_population()
    summary = run_evolution_cohort(loop, survivors[0], siblings=survivors, seed=7, max_specs=16)
    assert summary.generated > 0
    assert summary.killed >= summary.passed  # the gate, not authoring volume, decides — most die
