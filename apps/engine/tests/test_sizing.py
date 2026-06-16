# Parity contract tests for cosmu.master.sizing.
# Every later tier (T1 vol-target, T2 Kelly) MUST preserve the backtest==forward numeric equality
# asserted in test_backtest_paper_live_parity — that is the audit #7 invariant.
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cosmu.master.sizing import size_fraction
from cosmu.data.backtest import _entry_notional


def _spec(max_position_pct: float, conviction: float = 1.0):
    """Duck-typed StrategySpec stub — decoupled from schema churn."""
    return SimpleNamespace(risk=SimpleNamespace(max_position_pct=max_position_pct, conviction=conviction))


def test_default_fraction():
    # RiskRules defaults: max_position_pct=0.05, conviction=0.5 → 2.5%
    assert size_fraction(_spec(0.05, 0.5)) == 0.025


def test_spot_cap_clamps_at_one():
    assert size_fraction(_spec(2.0, 1.0)) == 1.0
    assert size_fraction(_spec(1.0, 2.0)) == 1.0
    assert size_fraction(_spec(5.0, 5.0)) == 1.0


def test_negative_inputs_floor_to_zero():
    assert size_fraction(_spec(-1.0, 0.5)) == 0.0
    assert size_fraction(_spec(0.5, -1.0)) == 0.0
    assert size_fraction(_spec(-1.0, -1.0)) == 0.0


def test_backtest_paper_live_parity():
    """THE audit #7 invariant: backtest and forward must compute the exact same notional."""
    for max_pos, conv in [(0.05, 0.5), (0.1, 0.8), (1.0, 1.0), (0.2, 0.3)]:
        spec = _spec(max_pos, conv)
        cash = 1000.0
        bt_notional = _entry_notional(cash, spec, 1.0)
        fwd_notional = cash * size_fraction(spec)
        assert bt_notional == fwd_notional, f"parity broken for max_pos={max_pos} conv={conv}"


def test_size_multiplier_is_tilt_on_top():
    """size_multiplier (backtest-only) multiplies the shared fraction — not a replacement."""
    spec = _spec(0.1, 0.5)
    cash = 1000.0
    base = _entry_notional(cash, spec, 1.0)
    half = _entry_notional(cash, spec, 0.5)
    assert half == base * 0.5


def test_gate_isolation():
    """size_fraction is pure — identical inputs always return identical outputs (gate can't drift)."""
    spec = _spec(0.05, 0.5)
    assert size_fraction(spec) == size_fraction(spec)
    assert size_fraction(spec) == 0.025


def test_forward_qty_arithmetic():
    """Paper-step qty computation: per_track_capital × frac / mark, rounded down to 8dp."""
    from decimal import ROUND_DOWN
    spec = _spec(1.0, 0.5)  # size_fraction = 0.5
    per_track_capital = Decimal("1000")
    mark = Decimal("30000")
    frac = Decimal(str(size_fraction(spec)))
    qty = (per_track_capital * frac / mark).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    assert qty == Decimal("0.01666666")  # floor(1000*0.5/30000) truncated at 8dp
