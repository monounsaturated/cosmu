# Deterministic offline unit tests for the PAA / DAA SIGNAL math (no cache, no network) — synthetic monthly series.
#
# These pin the documented rules independent of market data:
#   PAA: breadth-driven protective bond fraction BF=(N-n)/(N-n1) into the SAFE asset; top-6 above-trend risk basket.
#   DAA: canary breadth cash fraction b/B into the best defensive asset; top-6 momentum risk basket; weights sum ~1.
# We build MonthlySeries by hand so the test is fully deterministic and offline (the strategy modules only touch the
# cache via load_monthly, which we never call here).

from __future__ import annotations

from cosmu.research import equity_daa as daa
from cosmu.research import equity_paa as paa


def _series(mod, symbol: str, start: tuple[int, int], monthly_growth: float, n: int):
    """A MonthlySeries that compounds at a fixed monthly growth from 100 over `n` months (deterministic, no I/O)."""
    months: list[tuple[int, int]] = []
    close: dict[tuple[int, int], float] = {}
    px = 100.0
    m = start
    for _ in range(n):
        months.append(m)
        close[m] = px
        px *= 1.0 + monthly_growth
        m = mod._add_months(m, 1)
    return mod.MonthlySeries(symbol, months, close)


# --------------------------------------------------------------------------- PAA signal math


def test_paa_all_uptrend_no_bond_fraction():
    """Every risk asset above its 12m SMA (steady uptrend) -> breadth n=N -> BF=0 -> fully in the top-6 risk basket,
    zero in the safe asset; weights sum to ~1."""
    asof = (2010, 12)
    n_months = 40
    start = paa._add_months(asof, -(n_months - 1))
    series = {sym: _series(paa, sym, start, 0.01, n_months) for sym in paa.PAA_SERIES}
    w = paa._target_weights(series, asof, paa.SMA_MONTHS)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w.get(paa.SAFE, 0.0) < 1e-9, "no protective bond fraction when breadth is full"
    held = [s for s, ww in w.items() if ww > 0]
    assert len(held) == paa.TOP_N, "PAA holds the top-6 above-trend risk assets when fully risk-on"


def test_paa_all_downtrend_fully_defensive():
    """Every risk asset below its 12m SMA (steady downtrend) -> breadth n=0 -> BF clamps to 1 -> fully in the safe
    asset; weights sum to ~1."""
    asof = (2010, 12)
    n_months = 40
    start = paa._add_months(asof, -(n_months - 1))
    # Risk assets decline; the SAFE asset is held but its own trend is irrelevant to BF (BF is breadth of RISK assets).
    series = {}
    for sym in paa.PAA_SERIES:
        growth = -0.01 if sym in paa.RISK_UNIVERSE else 0.001
        series[sym] = _series(paa, sym, start, growth, n_months)
    w = paa._target_weights(series, asof, paa.SMA_MONTHS)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w.get(paa.SAFE, 0.0) - 1.0) < 1e-9, "fully defensive when no risk asset is above trend"


def test_paa_missing_history_fails_closed():
    """A risk asset without its full 12m SMA window -> _target_weights returns None (no synthetic fill, no look-ahead)."""
    asof = (2010, 12)
    series = {sym: _series(paa, sym, paa._add_months(asof, -39), 0.01, 40) for sym in paa.PAA_SERIES}
    # Truncate one risk asset's history so its 12m SMA is unavailable at `asof`.
    short = paa.RISK_UNIVERSE[0]
    series[short] = _series(paa, short, paa._add_months(asof, -3), 0.01, 4)
    assert paa._target_weights(series, asof, paa.SMA_MONTHS) is None


# --------------------------------------------------------------------------- DAA signal math


def test_daa_both_canaries_good_full_risk():
    """Both canaries (EEM, AGG) with positive 13612W score -> cash fraction 0 -> fully in the top-6 risk basket,
    nothing in the defensive pool; weights sum to ~1."""
    asof = (2010, 12)
    n_months = 30
    start = daa._add_months(asof, -(n_months - 1))
    series = {sym: _series(daa, sym, start, 0.01, n_months) for sym in daa.DAA_SERIES}
    w = daa._target_weights(series, asof)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert sum(w.get(sym, 0.0) for sym in daa.DEFENSIVE) < 1e-9, "no protective cash when both canaries are good"
    held_risk = [s for s in daa.RISK_UNIVERSE if w.get(s, 0.0) > 0]
    assert len(held_risk) == daa.TOP_N, "DAA holds the top-6 risk assets when fully risk-on"


def test_daa_both_canaries_bad_fully_defensive():
    """Both canaries with non-positive score -> cash fraction 1 (b/B = 2/2) -> fully in the best defensive asset;
    weights sum to ~1 and the entire book is in the defensive pool."""
    asof = (2010, 12)
    n_months = 30
    start = daa._add_months(asof, -(n_months - 1))
    series = {}
    for sym in daa.DAA_SERIES:
        # Canaries decline (score<=0); defensive pool rises; risk universe irrelevant when fully defensive.
        if sym in daa.CANARY:
            growth = -0.02
        elif sym in daa.DEFENSIVE:
            growth = 0.005
        else:
            growth = 0.01
        series[sym] = _series(daa, sym, start, growth, n_months)
    w = daa._target_weights(series, asof)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(sum(w.get(sym, 0.0) for sym in daa.DEFENSIVE) - 1.0) < 1e-9, "fully defensive when both canaries are bad"


def test_daa_one_canary_bad_half_defensive():
    """Exactly one canary bad -> protective cash fraction 1/2, parked in the single best defensive asset. We make SHY
    (a defensive-ONLY asset, not in the risk universe) the strongest defensive so the protective fraction is
    unambiguously attributable: SHY's weight must equal exactly 0.5 (no overlap with the risk basket). The risk
    fraction (the other 0.5) fills the top-6 risk assets; weights sum to ~1."""
    asof = (2010, 12)
    n_months = 30
    start = daa._add_months(asof, -(n_months - 1))
    # SHY is in DEFENSIVE but NOT in RISK_UNIVERSE -> its weight can only come from the protective fraction.
    assert "SHY" in daa.DEFENSIVE and "SHY" not in daa.RISK_UNIVERSE
    series = {}
    for sym in daa.DAA_SERIES:
        if sym == daa.CANARY[0]:        # exactly one canary declines (b=1 -> cash fraction 1/2)
            growth = -0.02
        elif sym == "SHY":              # make SHY the strongest defensive asset
            growth = 0.03
        else:
            growth = 0.01
        series[sym] = _series(daa, sym, start, growth, n_months)
    w = daa._target_weights(series, asof)
    assert w is not None
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w.get("SHY", 0.0) - 0.5) < 1e-9, f"one bad canary -> 0.5 into the best defensive (SHY), got {w.get('SHY')}"


def test_daa_missing_history_fails_closed():
    """An asset without its full 12m trailing return -> _target_weights returns None (fail closed)."""
    asof = (2010, 12)
    series = {sym: _series(daa, sym, daa._add_months(asof, -29), 0.01, 30) for sym in daa.DAA_SERIES}
    short = daa.RISK_UNIVERSE[0]
    series[short] = _series(daa, short, daa._add_months(asof, -3), 0.01, 4)
    assert daa._target_weights(series, asof) is None
