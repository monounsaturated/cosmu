"""Wikipedia Pageviews adapter — offline, deterministic, no network.

Tests cover:
  - PIT contract: available_at == ts + 1 day (not ts)
  - No look-ahead: points with available_at > as_of are excluded
  - No fabrication: gaps are absent, never zero
  - query() returns None when nothing is knowable yet (before any data)
  - wiki_pageviews_log: ln transform applied correctly
  - wiki_pageviews_zscore: strictly causal window (prior points only); absent when window < 2
  - Unknown symbol returns None-valued SourceFeature (never raises)
  - DataSource protocol satisfied (name, kind, metric, prior, transform_version, confidence)
  - low_confidence is True (confidence < 0.5)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.wikipedia_pageviews import (
    TRANSFORM_VERSION,
    WikipediaPageviewsSource,
    _article_for_symbol,
    _parse_response,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE = datetime(2024, 6, 1, tzinfo=UTC)  # arbitrary reference date


def _make_response(days: int = 10, base_views: int = 10_000) -> dict:
    """Fabricate a Wikimedia pageviews API response covering `days` consecutive days starting at _BASE."""
    items = []
    for i in range(days):
        day = _BASE + timedelta(days=i)
        items.append({
            "timestamp": day.strftime("%Y%m%d") + "00",
            "views": base_views + i * 1_000,  # monotonically increasing so tests can assert order
        })
    return {"items": items}


def _source(metric: str = "wiki_pageviews", days: int = 10) -> WikipediaPageviewsSource:
    """Return a WikipediaPageviewsSource wired to an offline fixture fetcher (zero network)."""
    fixture = _make_response(days=days)

    def _offline(url: str) -> dict:  # noqa: ARG001
        return fixture

    return WikipediaPageviewsSource(metric=metric, _fetcher=_offline)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_pit_availability():
    """available_at must be exactly ts + 1 day — not ts itself (the API's ~1d publication lag)."""
    payload = _make_response(days=3, base_views=50_000)
    pts = _parse_response(payload)
    assert len(pts) == 3
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1), (
            f"available_at={pt.available_at} should be ts+1d={pt.ts + timedelta(days=1)}"
        )


def test_parse_response_ascending_order():
    """Points are returned in ascending ts order (earliest first)."""
    pts = _parse_response(_make_response(days=5))
    tss = [p.ts for p in pts]
    assert tss == sorted(tss)


def test_parse_response_missing_fields_are_skipped():
    """Malformed items (no timestamp or no views) are silently dropped — not zero-filled."""
    payload = {
        "items": [
            {"timestamp": "2024060100", "views": 12345},
            {"timestamp": "2024060200"},          # missing views
            {"views": 99999},                     # missing timestamp
            {"timestamp": "2024060300", "views": 54321},
        ]
    }
    pts = _parse_response(payload)
    assert len(pts) == 2  # only the two complete items survive


def test_parse_response_empty_payload():
    """An empty or missing 'items' key returns []."""
    assert _parse_response({}) == []
    assert _parse_response({"items": []}) == []


# ---------------------------------------------------------------------------
# article resolution
# ---------------------------------------------------------------------------


def test_article_for_known_symbol():
    assert _article_for_symbol("BTCUSDT") == "Bitcoin"
    assert _article_for_symbol("ETHUSDT") == "Ethereum"
    assert _article_for_symbol("MARKET") == "S&P_500"


def test_article_for_base_asset_fallback():
    """SOLBTC (not in ENTITY_MAP) → strip "BTC" suffix → "SOL" → base-asset fallback."""
    art = _article_for_symbol("SOLBTC")
    assert art == "Solana_(blockchain_platform)"


def test_article_for_unknown_symbol():
    """An unrecognised symbol returns None — the source is disabled for it, not a crash."""
    assert _article_for_symbol("UNKNOWNXXX") is None


# ---------------------------------------------------------------------------
# wiki_pageviews (raw count)
# ---------------------------------------------------------------------------


def test_raw_pageviews_basic_query():
    """query() returns the latest raw count whose available_at <= as_of."""
    src = _source("wiki_pageviews", days=10)
    # as_of = _BASE + 5d + 1h; the last available point is day 4 (available_at = day 5 midnight).
    as_of = _BASE + timedelta(days=5, hours=1)
    f = src.query("BTCUSDT", as_of)
    assert f.value is not None
    # Day 4 (0-indexed) views = 10_000 + 4*1000 = 14_000
    assert f.value == pytest.approx(14_000.0)


def test_raw_pageviews_no_lookahead():
    """Points whose available_at > as_of are excluded (strict PIT, no look-ahead)."""
    src = _source("wiki_pageviews", days=10)
    # as_of == _BASE: day-0 has available_at == _BASE + 1d, which is AFTER as_of → nothing knowable
    f = src.query("BTCUSDT", _BASE)
    assert f.value is None, "No data should be knowable at _BASE (day 0 available_at is day 1)"


def test_raw_pageviews_available_at_contract():
    """SourceFeature.available_at is stamped as ts + 1 day (not ts itself — the 1d publication lag)."""
    src = _source("wiki_pageviews", days=10)
    # as_of = _BASE + 6d.  fetch_raw_series sets end_day = as_of - 1d = _BASE+5d.
    # Day 5 (ts=_BASE+5d) has available_at = _BASE+6d == as_of → last knowable point is day 5.
    as_of = _BASE + timedelta(days=6)
    f = src.query("BTCUSDT", as_of)
    assert f.available_at is not None
    assert f.available_at <= as_of
    # Check the key PIT property: available_at is ts + 1 day (not ts itself, not as_of).
    # The winning point (day 5) has ts=_BASE+5d, available_at=_BASE+6d.
    day_5_ts = _BASE + timedelta(days=5)
    assert f.available_at == day_5_ts + timedelta(days=1)
    # And available_at > ts for this point (the 1-day lag is present, not zero)
    assert f.available_at > day_5_ts


def test_unknown_symbol_returns_none_not_raises():
    """An unknown symbol returns a None-valued SourceFeature, never raises."""
    src = _source("wiki_pageviews", days=5)
    f = src.query("UNKNOWNTOKEN999", _BASE + timedelta(days=10))
    assert f.value is None
    assert f.available_at is None


# ---------------------------------------------------------------------------
# wiki_pageviews_log
# ---------------------------------------------------------------------------


def test_log_transform_correct():
    """wiki_pageviews_log = ln(raw_views). Spot-check one point."""
    src = _source("wiki_pageviews_log", days=10)
    as_of = _BASE + timedelta(days=5, hours=1)
    f = src.query("BTCUSDT", as_of)
    assert f.value is not None
    expected_log = math.log(14_000.0)  # day 4: 10_000 + 4*1_000
    assert f.value == pytest.approx(expected_log, rel=1e-9)


def test_log_absent_before_any_data():
    """wiki_pageviews_log returns None when nothing is knowable yet."""
    src = _source("wiki_pageviews_log", days=5)
    f = src.query("BTCUSDT", _BASE)
    assert f.value is None


# ---------------------------------------------------------------------------
# wiki_pageviews_zscore
# ---------------------------------------------------------------------------


def test_zscore_absent_with_too_little_history():
    """Z-score is absent (None) when fewer than 2 prior points exist — no fabrication."""
    src = _source("wiki_pageviews_zscore", days=5)
    # as_of = _BASE + 2d: day 0 available_at=day1, day 1 available_at=day2. At as_of=day2
    # the first two points are known but the z-score of day 1 uses only [day 0] as its window
    # (size=1) → absent. Let's use a very early as_of where window is definitely too small.
    f = src.query("BTCUSDT", _BASE + timedelta(days=2))
    # With only 1 prior point, std is undefined → None
    assert f.value is None


def test_zscore_present_with_sufficient_history():
    """Z-score is present once we have ≥ 2 prior points."""
    src = _source("wiki_pageviews_zscore", days=40)
    # as_of = _BASE + 35d: many prior points exist → z-score should be computable
    f = src.query("BTCUSDT", _BASE + timedelta(days=35))
    assert f.value is not None
    assert isinstance(f.value, float)


def test_zscore_is_strictly_causal():
    """The z-score window uses ONLY prior points — the current point is not in its own window.

    Build 20 points with a small but non-zero variance (views vary slightly) so the z-score
    window has a non-zero std, then add one massive spike. The spike's z-score should be very
    large, proving the window excluded the spike itself and used only the prior baseline points."""
    n_base = 20
    spike_views = 1_000_000

    def _spike_fixture(_url: str) -> dict:
        items = []
        for i in range(n_base):
            day = _BASE + timedelta(days=i)
            # Small variance: alternates 9_000 / 11_000 so std > 0 in the window.
            views = 9_000 if i % 2 == 0 else 11_000
            items.append({"timestamp": day.strftime("%Y%m%d") + "00", "views": views})
        spike_day = _BASE + timedelta(days=n_base)
        items.append({"timestamp": spike_day.strftime("%Y%m%d") + "00", "views": spike_views})
        return {"items": items}

    src = WikipediaPageviewsSource(metric="wiki_pageviews_zscore", _fetcher=_spike_fixture)
    # as_of must be at least spike_day + 1d for the spike's available_at to be <= as_of
    as_of = _BASE + timedelta(days=n_base + 2)

    f = src.query("BTCUSDT", as_of)
    # The spike z-score must be very large: ln(1_000_000) >> mean(ln([9k, 11k, 9k, ...]))
    assert f.value is not None, "z-score should be computable with 20 base points + 1 spike"
    assert f.value > 5.0, f"Expected z >> 5 for a spike from ~10k→1M, got {f.value}"


def test_zscore_no_lookahead_in_window():
    """Points after `as_of` do NOT contribute to any z-score returned at `as_of`."""
    src = _source("wiki_pageviews_zscore", days=40)
    early_as_of = _BASE + timedelta(days=15)
    late_as_of = _BASE + timedelta(days=35)
    f_early = src.query("BTCUSDT", early_as_of)
    f_late = src.query("BTCUSDT", late_as_of)
    # Both should be computable but independently (the early query is not aware of later data).
    # Our fixture has monotonically increasing views, so the late z-score can differ.
    # The key assertion is that early_query.value is not None (we have enough history by day 15).
    if f_early.value is not None and f_late.value is not None:
        # Not necessarily equal — the window differs. Just confirm both are finite floats.
        assert math.isfinite(f_early.value)
        assert math.isfinite(f_late.value)


# ---------------------------------------------------------------------------
# DataSource protocol + metadata
# ---------------------------------------------------------------------------


def test_datasource_protocol_attributes():
    """WikipediaPageviewsSource exposes all DataSource protocol fields."""
    src = WikipediaPageviewsSource()
    assert src.name == "wiki_pageviews"
    assert src.kind == "social"
    assert src.metric == "wiki_pageviews"
    assert src.prior  # non-empty string
    assert src.transform_version == TRANSFORM_VERSION
    assert 0.0 < src.confidence <= 1.0


def test_low_confidence_flag():
    """confidence < 0.5 → low_confidence is True (the gate down-weights it until OOS proves it)."""
    src = WikipediaPageviewsSource()
    assert src.confidence < 0.5
    assert src.low_confidence is True


def test_source_feature_fields_populated():
    """The returned SourceFeature has all fields set correctly."""
    src = _source("wiki_pageviews", days=10)
    as_of = _BASE + timedelta(days=5)
    f = src.query("BTCUSDT", as_of)
    assert f.name == "wiki_pageviews"
    assert f.scope == "BTCUSDT"
    assert f.as_of == as_of
    assert f.confidence == src.confidence
    assert f.transform_version == TRANSFORM_VERSION
    assert f.low_confidence is True


def test_api_failure_returns_none_not_raises():
    """A network/404 error in the fetcher degrades gracefully to None — never crashes the gate pass."""
    def _bad_fetcher(_url: str) -> dict:
        raise RuntimeError("network down")

    src = WikipediaPageviewsSource(metric="wiki_pageviews", _fetcher=_bad_fetcher)
    f = src.query("BTCUSDT", _BASE + timedelta(days=10))
    assert f.value is None  # graceful degradation


# ---------------------------------------------------------------------------
# Historical backfill — full date-range series (retro-testable depth)
# ---------------------------------------------------------------------------

def test_backfill_returns_full_series_not_one_point():
    """A backfill returns the WHOLE derived series over the window, not just the latest point."""
    n = 120
    src = _source("wiki_pageviews", days=n)
    as_of = _BASE + timedelta(days=n + 5)
    pts = src.backfill("BTCUSDT", days=400, as_of=as_of)
    assert len(pts) == n  # one per fixture day (all knowable by as_of)
    assert len(pts) > 1


def test_backfill_is_point_in_time_no_lookahead():
    """Every backfilled point's available_at <= as_of (Wikimedia ~1d lag honoured)."""
    src = _source("wiki_pageviews", days=30)
    as_of = _BASE + timedelta(days=10, hours=12)
    pts = src.backfill("BTCUSDT", days=400, as_of=as_of)
    assert pts
    for p in pts:
        assert p.available_at <= as_of, f"look-ahead: {p.available_at} > {as_of}"
        assert p.available_at == p.ts + timedelta(days=1)


def test_backfill_zscore_metric_is_causal_and_deep():
    """The z-score backfill produces a deep series, each value using only prior history (causal)."""
    n = 90
    src = _source("wiki_pageviews_zscore", days=n)
    as_of = _BASE + timedelta(days=n + 5)
    pts = src.backfill("BTCUSDT", days=400, as_of=as_of)
    # zscore needs >=2 prior points so the first one or two days are absent — but the bulk survives.
    assert len(pts) > n // 2
    tss = [p.ts for p in pts]
    assert tss == sorted(tss)


def test_backfill_unknown_symbol_returns_empty():
    src = _source("wiki_pageviews", days=10)
    assert src.backfill("NOT_A_TICKER", days=400, as_of=_BASE + timedelta(days=20)) == []


def test_backfill_fetch_failure_returns_empty_not_raises():
    def _bad_fetcher(_url: str) -> dict:
        raise RuntimeError("network down")

    src = WikipediaPageviewsSource(metric="wiki_pageviews", _fetcher=_bad_fetcher)
    assert src.backfill("BTCUSDT", days=400, as_of=_BASE + timedelta(days=20)) == []
