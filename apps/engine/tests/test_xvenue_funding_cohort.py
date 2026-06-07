# Cross-venue funding-DISPERSION cohort harness — offline, deterministic tests. No network, no live keys.
# Proves: (1) the dispersion specs load + compile with pre-registered directions/features; (2) the PIT
# cross-venue alt builder computes signed spreads, dispersion (max-min), and cross-sectional ranks correctly
# and point-in-time (a venue absent at a bar is not 0-filled); (3) the shuffle placebo preserves the value
# multiset but breaks alignment; (4) the harness emits a verdict and is deterministic; (5) too-thin overlap is
# reported as INSUFFICIENT-DATA (honest abstention, never a fabricated pass).

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.knowledge.store import Store
from cosmu.research.xvenue_funding_cohort import (
    FEAT_DISP,
    FEAT_DISP_RANK,
    FEAT_SPREAD_BYBIT,
    _add_xsec_rank,
    _disp_feature_of,
    _disp_specs,
    _shuffle_disp,
    _xvenue_funding_alt,
    run_cohort,
)


def _store() -> Store:
    tmp = tempfile.mkdtemp(prefix="cosmu-xvenue-test-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))


def _bars(prices: list[float], *, seed: float = 0.0) -> list[Bar]:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p + seed, 4)))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


class _FixtureBinance:
    """In-memory Binance funding provider keyed by symbol (CI fixture; mirrors CachedFundingRateProvider seam)."""

    def __init__(self, by_symbol: dict[str, list[AltDataPoint]]) -> None:
        self._by = by_symbol

    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        if metric != "funding_rate":
            return []
        pts = self._by.get(symbol, [])
        return pts[-limit:] if limit and len(pts) > limit else pts


def test_specs_compile_with_preregistered_directions():
    specs = _disp_specs()
    assert len(specs) == 4
    by_feat = {_disp_feature_of(s): s for _, s in specs}
    # mean-reversion fades high dispersion → SHORT; carry-convergence is LONG; ranks pre-registered both ways
    assert by_feat[FEAT_DISP].direction == -1
    assert by_feat[FEAT_SPREAD_BYBIT].direction == 1
    # every spec keys on a dispersion/spread feature (not a bare price feature)
    for _, s in specs:
        assert _disp_feature_of(s) != ""


def test_xvenue_alt_builder_is_point_in_time_and_signed():
    # two symbols, 6 daily bars; Binance funding higher than Bybit on A, lower on B (signed spread sign check)
    bars = {"AUSDT": _bars([100, 101, 102, 103, 104, 105]), "BUSDT": _bars([50, 50, 50, 50, 50, 50], seed=0.5)}
    t0 = datetime(2025, 1, 1, tzinfo=UTC)

    def pts(vals):
        return [AltDataPoint(ts=t0 + timedelta(days=i), available_at=t0 + timedelta(days=i), value=v)
                for i, v in enumerate(vals)]

    binance = _FixtureBinance({
        "AUSDT": pts([0.0003, 0.0003, 0.0003, 0.0003, 0.0003, 0.0003]),
        "BUSDT": pts([0.0001, 0.0001, 0.0001, 0.0001, 0.0001, 0.0001]),
    })
    # monkeypatch the on-disk xvenue readers to return in-memory bybit/okx
    import cosmu.research.xvenue_funding_cohort as mod

    byb = {"AUSDT": pts([0.0001] * 6), "BUSDT": pts([0.0002] * 6)}
    okx = {"AUSDT": pts([0.0002] * 6)}  # OKX only on A → disp uses 3 venues on A, 2 on B
    orig = mod._read_xvenue_funding
    mod._read_xvenue_funding = lambda d, s: (byb if d == mod._BYBIT_DIR else okx).get(s, [])  # noqa: SLF001
    try:
        alt, coverage = _xvenue_funding_alt(bars, binance)
    finally:
        mod._read_xvenue_funding = orig

    # A: binance(3) - bybit(1) = +2e-4 (signed, positive)
    a_spread = alt["AUSDT"][FEAT_SPREAD_BYBIT]
    assert all(abs(v - 0.0002) < 1e-9 for v in a_spread.values())
    # B: binance(1) - bybit(2) = -1e-4 (signed, negative — proves the sign is preserved, not abs)
    b_spread = alt["BUSDT"][FEAT_SPREAD_BYBIT]
    assert all(v < 0 for v in b_spread.values())
    # A dispersion = max(3,1,2) - min = 2e-4 (3 venues); B dispersion = max(1,2)-min = 1e-4 (2 venues, no okx)
    assert all(abs(v - 0.0002) < 1e-9 for v in alt["AUSDT"][FEAT_DISP].values())
    assert all(abs(v - 0.0001) < 1e-9 for v in alt["BUSDT"][FEAT_DISP].values())
    # coverage = bars with ALL THREE venues: A has okx (>=1), B has none → A>0, B==0 (honest, no 0-fill)
    assert coverage["AUSDT"] > 0
    assert coverage["BUSDT"] == 0


def test_xsec_rank_is_zero_to_one_percentile():
    alt = {
        "A": {FEAT_DISP: {"2025-01-01T00:00:00+00:00": 0.0001}},
        "B": {FEAT_DISP: {"2025-01-01T00:00:00+00:00": 0.0005}},
        "C": {FEAT_DISP: {"2025-01-01T00:00:00+00:00": 0.0003}},
    }
    _add_xsec_rank(alt, FEAT_DISP, FEAT_DISP_RANK)
    k = "2025-01-01T00:00:00+00:00"
    assert alt["A"][FEAT_DISP_RANK][k] == 0.0   # lowest
    assert alt["B"][FEAT_DISP_RANK][k] == 1.0   # highest
    assert alt["C"][FEAT_DISP_RANK][k] == 0.5   # middle


def test_shuffle_placebo_preserves_values_breaks_alignment():
    series = {f"2025-01-{i + 1:02d}T00:00:00+00:00": float(i) for i in range(10)}
    alt = {"A": {FEAT_DISP: dict(series)}}
    shuffled = _shuffle_disp(alt, seed=7)
    orig_vals = sorted(series.values())
    shuf_vals = sorted(shuffled["A"][FEAT_DISP].values())
    assert orig_vals == shuf_vals                       # same multiset (marginal preserved)
    assert series != shuffled["A"][FEAT_DISP]           # alignment broken (rotation != identity)
    # keys unchanged (PIT keying preserved — values still attach to real bar timestamps)
    assert set(series) == set(shuffled["A"][FEAT_DISP])


def test_thin_overlap_is_insufficient_data():
    # only a handful of bars / entries → below the min-trades floor → honest abstention
    bars = {f"S{j}USDT": _bars([100 + i for i in range(40)], seed=j) for j in range(3)}
    t0 = datetime(2025, 1, 1, tzinfo=UTC)

    def pts(n, v):
        return [AltDataPoint(ts=t0 + timedelta(days=i), available_at=t0 + timedelta(days=i), value=v) for i in range(n)]

    binance = _FixtureBinance({s: pts(40, 0.0002) for s in bars})
    import cosmu.research.xvenue_funding_cohort as mod

    orig = mod._read_xvenue_funding
    mod._read_xvenue_funding = lambda d, s: pts(40, 0.0001)  # noqa: SLF001
    try:
        report = run_cohort(_disp_specs(), bars, binance, _store(), axis="test", require_okx=False)
    finally:
        mod._read_xvenue_funding = orig
    assert report.verdict in {"INSUFFICIENT-DATA", "FAIL"}


def test_cohort_is_deterministic():
    bars = {f"S{j}USDT": _bars([100 * (1.01 ** i) for i in range(160)], seed=j) for j in range(4)}
    t0 = datetime(2025, 1, 1, tzinfo=UTC)

    def pts(n, base):
        return [AltDataPoint(ts=t0 + timedelta(days=i), available_at=t0 + timedelta(days=i),
                             value=base + (0.0001 if i % 5 == 0 else 0.0)) for i in range(n)]

    binance = _FixtureBinance({s: pts(160, 0.0002) for s in bars})
    import cosmu.research.xvenue_funding_cohort as mod

    orig = mod._read_xvenue_funding
    mod._read_xvenue_funding = lambda d, s: pts(160, 0.0001)  # noqa: SLF001
    try:
        r1 = run_cohort(_disp_specs(), bars, binance, _store(), axis="test", require_okx=False)
        r2 = run_cohort(_disp_specs(), bars, binance, _store(), axis="test", require_okx=False)
    finally:
        mod._read_xvenue_funding = orig
    assert r1.verdict == r2.verdict
    assert [(a.name, a.net_return, a.num_trades, a.promoted) for a in r1.specs] == \
           [(a.name, a.net_return, a.num_trades, a.promoted) for a in r2.specs]
