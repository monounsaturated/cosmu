# Deterministic offline unit tests for the HAA (Hybrid Asset Allocation, Keller 2023) SIGNAL math — no cache, no
# network. Synthetic monthly series pin the documented rules: single TIP canary gates risk-on/off; top-T offensive
# by simple-average momentum; per-slot absolute-momentum filter bleeds losers to the best cash asset.

from __future__ import annotations

from cosmu.research import equity_daa as daa
from cosmu.research import equity_haa as haa


def _series(symbol: str, start: tuple[int, int], monthly_growth: float, n: int):
    months, close, px, m = [], {}, 100.0, start
    for _ in range(n):
        months.append(m)
        close[m] = px
        px *= 1.0 + monthly_growth
        m = daa._add_months(m, 1)
    return daa.MonthlySeries(symbol, months, close)


def test_haa_canary_negative_goes_fully_cash():
    """TIP canary with non-positive momentum -> risk-OFF -> 100% in the best cash asset; weights sum to ~1."""
    asof = (2012, 12)
    n = 30
    start = daa._add_months(asof, -(n - 1))
    series = {}
    for sym in haa.HAA_SERIES:
        growth = -0.02 if sym == haa.CANARY else (0.01 if sym in haa.RISK_UNIVERSE else 0.002)
        series[sym] = _series(sym, start, growth, n)
    w = haa._target_weights(series, asof)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # all weight sits in one of the cash proxies, nothing in the offensive sleeve
    assert sum(w.get(s, 0.0) for s in haa.RISK_UNIVERSE if s not in haa.CASH) < 1e-9
    assert abs(sum(w.get(s, 0.0) for s in haa.CASH) - 1.0) < 1e-9


def test_haa_risk_on_holds_top_t_equal_weight():
    """Canary positive + every offensive asset trending up -> hold exactly TOP_T offensive names, equal weight."""
    asof = (2012, 12)
    n = 30
    start = daa._add_months(asof, -(n - 1))
    # give the offensive universe distinct positive growth so the top-T is unambiguous
    rates = {sym: 0.005 + 0.001 * i for i, sym in enumerate(haa.RISK_UNIVERSE)}
    series = {}
    for sym in haa.HAA_SERIES:
        if sym == haa.CANARY:
            growth = 0.02            # canary positive -> risk-on
        elif sym in rates:
            growth = rates[sym]
        else:
            growth = 0.001
        series[sym] = _series(sym, start, growth, n)
    w = haa._target_weights(series, asof)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    held = [s for s, ww in w.items() if ww > 0]
    assert len(held) == haa.TOP_T
    for ww in w.values():
        assert abs(ww - 1.0 / haa.TOP_T) < 1e-9


def test_haa_missing_history_fails_closed():
    """An asset without its full 12m trailing window -> _target_weights returns None (no synthetic fill)."""
    asof = (2012, 12)
    series = {sym: _series(sym, daa._add_months(asof, -29), 0.01, 30) for sym in haa.HAA_SERIES}
    short = haa.RISK_UNIVERSE[0]
    series[short] = _series(short, daa._add_months(asof, -3), 0.01, 4)
    assert haa._target_weights(series, asof) is None
