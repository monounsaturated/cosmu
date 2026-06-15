"""The Gate and the StrategySpec backtest must share ONE cost model.

`research/gate.py::_simulate` used to charge a SOFTER cost than `data/backtest.py::run_strategy_backtest`:
a flat 5bps slippage with NO market impact, vs the backtest's half-spread PLUS participation-scaled impact.
That let the single-signal Gate bless a fill the live backtest could not trade at the same net-of-fee price.

These tests pin the unification: the Gate now prices every fill through the SAME `_slippage` curve and the
SAME bps defaults the backtest uses. Each test is written so it FAILS on the old flat-5bps-no-impact Gate.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.backtest import DEFAULT_IMPACT_BPS, DEFAULT_SLIPPAGE_BPS, _slippage
from cosmu.data.market import Bar
import cosmu.research.gate as gate
from cosmu.research.gate import _simulate

# The old softer Gate cost model: flat half-spread, no market impact. Recomputing a trade under this is the
# adversarial control — if `_simulate` still used it, the parity assertions below would fail.
_OLD_FLAT_SLIP = 0.0005


def _bar(ts: datetime, o: float, h: float, lo: float, c: float, vol: float) -> Bar:
    return Bar(
        ts=ts,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(lo)),
        close=Decimal(str(c)),
        volume=Decimal(str(vol)),
    )


def _one_trade_market() -> list[Bar]:
    """A deterministic single-symbol series where exactly one Gate trade opens then time-stops.

    Volume is deliberately thin (quote-volume on the order of the entry notional) so the participation-scaled
    impact term is the dominant cost — the exact regime where the old flat-5bps Gate and the backtest diverge.
    Prices drift gently up but never hit the +16% take or -8% stop, so the trade closes on the hold-bars
    time-stop and the realized exit price is `open * (1 - slip)` — a clean, hand-checkable fill.
    """
    base = datetime(2023, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 100.0
    for i in range(12):
        o = price
        c = price * 1.01  # +1% per bar: no stop, no take over the hold window
        h = c * 1.001
        lo = o * 0.999
        bars.append(_bar(base + timedelta(days=i), o, h, lo, c, vol=300.0))
        price = c
    return bars


def _recompute_one_trade_net_pnl(bars: list[Bar], entry_idx: int, exit_idx: int, slip_fn) -> float:
    """Independently recompute the single trade's net-of-fee P&L the way `_simulate` does, but with the
    slippage function supplied — used both for the shared model (must match) and the old flat model (must NOT).
    Entry fills on `entry_idx` open at `(1 + slip)`, the time-stop closes on `exit_idx` open at `(1 - slip)`.
    Fee falls back to the static catalog taker fee (no store), exactly like `_simulate`. Each bar's slip uses
    the SAME participation basis `_simulate` does — `cash * 0.2` — and `cash` drops by the entry notional after
    entry, so the exit bar's slip is computed on the post-entry cash (the subtle basis the old test missed)."""
    fee = gate._FEE_FALLBACK_BPS / 10000.0
    cash = 100000.0
    entry_bar = bars[entry_idx]
    exit_bar = bars[exit_idx]
    entry_slip = slip_fn(cash * 0.2, entry_bar)
    entry = float(entry_bar.open) * (1 + entry_slip)
    cash -= cash * 0.2  # cash settles down by the entry notional, exactly as in `_simulate`
    exit_slip = slip_fn(cash * 0.2, exit_bar)
    xp = float(exit_bar.open) * (1 - exit_slip)
    return (xp * (1 - fee) - entry * (1 + fee)) / entry


def test_gate_simulate_uses_shared_participation_scaled_cost_not_flat():
    """The Gate's realized net-of-fee trade P&L matches a recomputation through the SHARED `_slippage` curve,
    and is STRICTLY WORSE than the old flat-5bps-no-impact model would have priced it. On thin bars the impact
    term costs ~9x the old flat slip, so the two recomputations are far apart — the old Gate would fail here."""
    bars = _one_trade_market()
    # Signal True ONLY on bar 0: the Gate opens at bar 1 (reads signal[i-1]) and time-stops `hold_bars` later,
    # with no later signal to re-enter — so exactly one trade fills.
    signal = [i == 0 for i in range(len(bars))]
    params = gate.SignalParams(lookback=14, z_threshold=0.5, hold_bars=5)

    equity, trades = _simulate(bars, signal, params, symbol="BTCUSDT")
    assert len(trades) == 1, f"fixture must produce exactly one trade, got {len(trades)}"
    realized_net = trades[0][0]

    # Entry opens at bar 1 (signal[0] True, flat), time-stop fires `hold_bars` later at bar 6.
    entry_idx, exit_idx = 1, 1 + params.hold_bars

    def shared_slip(notional, bar):
        return _slippage(
            float(DEFAULT_SLIPPAGE_BPS) / 10000.0, float(DEFAULT_IMPACT_BPS) / 10000.0, notional, bar
        )

    def flat_slip(notional, bar):  # the OLD softer Gate cost model
        return _OLD_FLAT_SLIP

    expected_shared = _recompute_one_trade_net_pnl(bars, entry_idx, exit_idx, shared_slip)
    would_be_flat = _recompute_one_trade_net_pnl(bars, entry_idx, exit_idx, flat_slip)

    # 1) The Gate prices the trade through the SHARED cost model (parity).
    assert abs(realized_net - expected_shared) < 1e-9, (
        f"Gate net P&L {realized_net} != shared-cost recompute {expected_shared}"
    )
    # 2) That price is materially WORSE than the old flat-5bps model — this assertion FAILS on the old Gate.
    assert realized_net < would_be_flat - 1e-4, (
        f"Gate still pricing like the old flat model: realized={realized_net} flat={would_be_flat}"
    )


def test_gate_slippage_constants_are_the_backtest_defaults():
    """The Gate's slippage/impact fractions are derived from the SAME bps defaults `run_strategy_backtest`
    uses — the single source of truth. If someone forks the Gate back to a softer model this breaks."""
    assert gate._BASE_SLIP == float(DEFAULT_SLIPPAGE_BPS) / 10000.0
    assert gate._IMPACT == float(DEFAULT_IMPACT_BPS) / 10000.0
    # And the impact term is actually live (non-zero), so a thin bar costs strictly more than the half-spread.
    thin = _bar(datetime(2023, 1, 1, tzinfo=UTC), 100, 101, 99, 100, vol=300.0)
    slip = _slippage(gate._BASE_SLIP, gate._IMPACT, 20000.0, thin)
    assert slip > gate._BASE_SLIP, "impact term must add to the half-spread on a thin bar"
