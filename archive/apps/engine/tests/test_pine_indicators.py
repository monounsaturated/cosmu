# Tests for cosmu/research/pine_indicators — the Pine-indicator -> computed-data-source mode.
# All offline (deterministic fixture bars). Invariants checked:
#   - the confidence number is bounded [0, 100] (or None during warm-up)
#   - the series is CAUSAL / non-repainting: computing on a truncated prefix yields identical past values
#   - latest() returns an actionable number; as_altdata() is point-in-time (available_at == bar close)
#   - the correlation harness aligns on the overlap and reports sane stats
#   - HTF alignment is neutral (0.5) before the first closed HTF block (no look-ahead warm-up leak)

from __future__ import annotations

from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.research.pine_indicators import INDICATORS, IndicatorResult, correlate, forward_abs_return
from cosmu.research.pine_indicators import ml_liquidity_zone as lzc


def _bars(n: int = 600):
    _, bars = next(iter(edge_bearing_screen_market(seed=3, n=n).items()))
    return bars


def test_registry_exposes_indicator():
    assert lzc.name in INDICATORS
    assert INDICATORS[lzc.name] is lzc.compute


def test_confidence_is_bounded_or_none():
    res = lzc.compute(_bars())
    assert isinstance(res, IndicatorResult)
    for value in res.series["confidence"]:
        assert value is None or 0.0 <= value <= 100.0


def test_component_features_in_unit_range():
    res = lzc.compute(_bars())
    for key in ("f1_volume", "f2_htf_align", "f3_displacement"):
        for value in res.series[key]:
            assert value is None or 0.0 <= value <= 1.0


def test_causal_non_repainting():
    """The strongest property: a truncated prefix must reproduce every past value byte-for-byte."""
    bars = _bars()
    full = lzc.compute(bars).series["confidence"]
    for cut in (300, 450):
        part = lzc.compute(bars[:cut]).series["confidence"]
        assert part == full[:cut], f"look-ahead detected at cut={cut}"


def test_latest_returns_a_number():
    res = lzc.compute(_bars())
    latest = res.latest()
    assert latest is not None and 0.0 <= latest <= 100.0


def test_as_altdata_is_point_in_time():
    bars = _bars()
    res = lzc.compute(bars)
    points = res.as_altdata(bars)
    assert points, "expected some computed points"
    # An indicator computed on the confirmed bar is known at that bar's close — no look-ahead.
    assert all(p.available_at == p.ts for p in points)
    assert len(points) == sum(1 for v in res.series["confidence"] if v is not None)


def test_htf_alignment_neutral_during_warmup():
    bars = _bars()
    res = lzc.compute(bars, htf_mult=12.0)
    # Before the first fully-closed 12-bar HTF block, alignment is the neutral 0.5 (no warm-up leak).
    assert res.series["f2_htf_align"][0] == 0.5
    assert res.series["f2_htf_align"][5] == 0.5


def test_analyze_reports_correlation():
    bars = _bars()
    _, report, horizon = lzc.analyze(bars)
    assert horizon == int(lzc.DEFAULTS["eval_window"])
    assert report.n > 100
    # On purely synthetic bars the edge should be ~0 — the harness must not manufacture one.
    assert report.pearson is None or -1.0 <= report.pearson <= 1.0


def test_correlate_handles_thin_overlap():
    report = correlate([1.0, 2.0, None], [None, 1.0, 2.0])
    assert report.n < 8 and report.pearson is None and "insufficient" in report.note


def test_empty_bars_safe():
    res = lzc.compute([])
    assert res.latest() is None
    assert forward_abs_return([], 10) == []
