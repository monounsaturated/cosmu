# Parity contract tests for cosmu.master.sizing.
# Every later tier (T1 vol-target, T2 Kelly) MUST preserve the backtest==forward numeric equality
# asserted in test_backtest_paper_live_parity — that is the audit #7 invariant.
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cosmu.master.sizing import compute_target_vol, size_fraction
from cosmu.data.backtest import _entry_notional


def _spec(max_position_pct: float, conviction: float = 1.0, max_concurrent: int = 1):
    """Duck-typed StrategySpec stub — decoupled from schema churn."""
    return SimpleNamespace(
        risk=SimpleNamespace(
            max_position_pct=max_position_pct,
            conviction=conviction,
            max_concurrent_positions=max_concurrent,
        )
    )


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


# ── T1 vol-target tests ──────────────────────────────────────────────────────


def test_compute_target_vol_returns_none_short_series():
    assert compute_target_vol([0.01] * 5) is None
    assert compute_target_vol([]) is None


def test_compute_target_vol_positive_for_real_series():
    import math
    returns = [0.01 * ((-1) ** i) for i in range(50)]  # alternating ±1%
    tv = compute_target_vol(returns)
    assert tv is not None and tv > 0 and math.isfinite(tv)


def test_t1_path_activates_only_when_both_provided():
    spec = _spec(0.05, 0.5)
    t0 = size_fraction(spec)
    # Neither closes nor target_vol → T0
    assert size_fraction(spec, closes=None, target_vol=None) == t0
    # Only one → T0
    closes = [100.0 + i * 0.1 for i in range(50)]
    assert size_fraction(spec, closes=closes, target_vol=None) == t0
    assert size_fraction(spec, closes=None, target_vol=0.01) == t0


def test_t1_scales_down_in_high_vol():
    """When current realized vol >> target_vol, position is smaller than T0."""
    spec = _spec(0.5, 1.0)  # T0 fraction = 0.5
    # Build a low-vol reference level (target_vol)
    target_vol = 0.005  # 0.5% per bar
    # High-vol closes: large swings → EWMA vol >> target_vol → fraction < 0.5
    import math
    closes = [1000.0 * (1 + 0.05 * ((-1) ** i)) for i in range(50)]  # ±5% swings
    f_t1 = size_fraction(spec, closes=closes, target_vol=target_vol)
    f_t0 = size_fraction(spec)
    assert f_t1 < f_t0, f"expected T1 to downsize in high vol; T1={f_t1:.4f} T0={f_t0:.4f}"


def test_t1_scales_up_in_low_vol_capped_by_cap():
    """When current realized vol << target_vol, fraction is capped at max_position_pct/max_concurrent."""
    spec = _spec(0.3, 1.0)  # T0 fraction = 0.3, cap = min(0.3, 1/1) = 0.3
    target_vol = 0.05  # large target
    # Very flat closes → near-zero realized vol → formula wants to deploy hugely → capped at 0.3
    closes = [1000.0 + i * 0.0001 for i in range(50)]
    f_t1 = size_fraction(spec, closes=closes, target_vol=target_vol)
    assert f_t1 <= 0.3 + 1e-9, f"must be capped at max_position_pct; got {f_t1}"


def test_t1_floor_prevents_zero_fraction():
    from cosmu.master.sizing import _SIZING_FLOOR
    spec = _spec(0.5, 1.0)
    target_vol = 1e-8  # tiny target
    closes = [1000.0 * (1 + 0.1 * ((-1) ** i)) for i in range(50)]  # ±10% swings → huge realized vol
    f_t1 = size_fraction(spec, closes=closes, target_vol=target_vol)
    assert f_t1 >= _SIZING_FLOOR - 1e-12


def test_t1_falls_back_to_t0_when_closes_too_short():
    spec = _spec(0.05, 0.5)
    t0 = size_fraction(spec)
    short_closes = [100.0, 101.0, 99.0]  # < warmup+2
    # Should fall back to T0 since realized_vol can't be computed
    f = size_fraction(spec, closes=short_closes, target_vol=0.01)
    assert f == t0
