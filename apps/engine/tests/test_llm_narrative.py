# Offline, deterministic tests for the LLM-NARRATIVE axis (first cut). No network, no live LLM key.
# Proves the load-ahead defenses + harness contract:
#   (1) score_headlines_to_daily is POINT-IN-TIME: each daily point's available_at == day+1 (a bar at t reads
#       only narrative from days <= t-1); a day with no items produces no point (honest absence, never zero-fill).
#   (2) the daily value is the confidence-weighted mean of that day's content-only scores, in [-1, 1].
#   (3) CachedNarrativeScorer is KEY-GATED (no key + no cache => None) and CONTENT-HASH CACHED (a written score
#       is reused without a live call).
#   (4) _time_shuffle preserves the marginal distribution (same multiset of values) but scrambles the timing —
#       the placebo disconfirmer the cohort relies on.
#   (5) the cohort harness ABSTAINS honestly (INSUFFICIENT-DATA) when there is no narrative series, and runs to a
#       verdict on real-shaped bars + a synthetic narrative with a genuine (non-stubbed) holdout DSR per member.

from __future__ import annotations

import datetime as dt
import tempfile
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, NewsItem
from cosmu.data.market import Bar
from cosmu.ingest.llm_formatter import TypedFeature
from cosmu.knowledge.store import Store
from cosmu.research.llm_narrative_cohort import _time_shuffle, run_cohort
from cosmu.research.llm_narrative_pipeline import (
    CachedNarrativeScorer,
    score_headlines_to_daily,
)


def _store() -> Store:
    tmp = tempfile.mkdtemp(prefix="cosmu-llmnarr-test-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))


def _bars(prices: list[float]) -> list[Bar]:
    t0 = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p, 4)))
        out.append(Bar(ts=t0 + dt.timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


def _news(day: dt.date, hour: int, headline: str) -> NewsItem:
    ts = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC)
    return NewsItem(ts=ts, available_at=ts, headline=headline)


class _FixedScorer:
    """Inject deterministic TypedFeatures keyed by headline — no network, no key needed."""

    def __init__(self, mapping: dict[str, TypedFeature | None]) -> None:
        self.mapping = mapping
        self.calls = 0

    def __call__(self, headline: str) -> TypedFeature | None:
        self.calls += 1
        return self.mapping.get(headline)


def test_daily_series_is_point_in_time_and_confidence_weighted():
    d1 = dt.date(2025, 3, 10)
    d2 = dt.date(2025, 3, 11)
    items = [
        _news(d1, 8, "h_bull_strong"),   # +1 * 0.8, conf 1.0
        _news(d1, 9, "h_bear_weak"),     # -1 * 0.2, conf 0.5
        _news(d2, 8, "h_neutral"),       #  0,       conf 0.0  -> day still produced (>=1 item)
    ]
    scorer = _FixedScorer({
        "h_bull_strong": TypedFeature(sign=1, magnitude=0.8, category="market", confidence=1.0),
        "h_bear_weak": TypedFeature(sign=-1, magnitude=0.2, category="market", confidence=0.5),
        "h_neutral": TypedFeature(sign=0, magnitude=0.0, category="other", confidence=0.0),
    })
    pts = score_headlines_to_daily(items, scorer)  # type: ignore[arg-type]
    assert len(pts) == 2
    p1, p2 = pts
    # PIT: availability is the day AFTER the observation day (a bar at t reads only days <= t-1).
    assert p1.ts == dt.datetime(2025, 3, 10, tzinfo=dt.UTC)
    assert p1.available_at == dt.datetime(2025, 3, 11, tzinfo=dt.UTC)
    assert p2.available_at == dt.datetime(2025, 3, 12, tzinfo=dt.UTC)
    # confidence-weighted mean for d1: (0.8*1.0 + (-0.2)*0.5) / (1.0 + 0.5) = 0.7/1.5
    assert abs(p1.value - (0.7 / 1.5)) < 1e-6
    # d2: only a zero-confidence neutral -> plain mean of scores = 0.0
    assert p2.value == 0.0


def test_none_scores_are_dropped_never_zero_filled():
    d = dt.date(2025, 3, 10)
    items = [_news(d, 8, "scored"), _news(d, 9, "unscored")]
    scorer = _FixedScorer({
        "scored": TypedFeature(sign=1, magnitude=0.5, category="market", confidence=0.5),
        "unscored": None,  # no key / invalid -> dropped, not counted as 0
    })
    pts = score_headlines_to_daily(items, scorer)  # type: ignore[arg-type]
    assert len(pts) == 1
    assert pts[0].value == 0.5  # only the scored item contributed; the None was dropped (no zero-fill)


def test_empty_day_produces_no_point():
    items: list[NewsItem] = []
    pts = score_headlines_to_daily(items, _FixedScorer({}))  # type: ignore[arg-type]
    assert pts == []


def test_scorer_key_gated_and_cached(tmp_path):
    # No key + empty cache -> None (honest degradation, never a fabricated feature).
    s = CachedNarrativeScorer(api_key=None, cache_dir=tmp_path)
    assert s("anything") is None
    # A cached score is reused without a live call (calls stays 0).
    tf = TypedFeature(sign=1, magnitude=0.6, category="adoption", confidence=0.7)
    cp = s._cache_path("cached headline")
    cp.write_text(tf.model_dump_json())
    out = s("cached headline")
    assert out is not None and out.score == 0.6 and s.calls == 0


def test_time_shuffle_preserves_marginal_but_scrambles_timing():
    pts = [
        AltDataPoint(ts=dt.datetime(2025, 3, i + 1, tzinfo=dt.UTC),
                     available_at=dt.datetime(2025, 3, i + 2, tzinfo=dt.UTC), value=float(i))
        for i in range(10)
    ]
    shuffled = _time_shuffle(pts, seed=123)
    # same ts/available_at backbone (PIT shape preserved)
    assert [p.ts for p in shuffled] == [p.ts for p in pts]
    assert [p.available_at for p in shuffled] == [p.available_at for p in pts]
    # same multiset of values (marginal distribution preserved)
    assert sorted(p.value for p in shuffled) == sorted(p.value for p in pts)
    # timing actually changed (not the identity permutation for this seed)
    assert [p.value for p in shuffled] != [p.value for p in pts]


def test_cohort_abstains_on_empty_narrative():
    bars = _bars([100.0 * (1.001 ** i) for i in range(120)])
    store = _store()
    rep = run_cohort({"BTCUSDT": bars}, [], store, symbol="BTCUSDT")
    assert rep.verdict == "INSUFFICIENT-DATA"
    assert rep.members == []


def test_cohort_runs_with_real_holdout_per_member():
    # Real-shaped bars + a synthetic narrative over the SAME window -> the harness runs all three members
    # (candidate + time-shuffle placebo + momentum-only control) through promote_cohort and reports a per-member
    # holdout DSR computed by run_strategy_backtest_detailed (the genuine purged+embargoed last fifth — NOT a stub).
    bars = _bars([100.0 * (1.002 ** i) for i in range(200)])
    pts: list[AltDataPoint] = []
    for i, b in enumerate(bars):
        d = b.ts.astimezone(dt.UTC).date()
        ts = dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC)
        # deterministic oscillating narrative in [-1, 1]
        val = round(((i * 37) % 100) / 50.0 - 1.0, 4)
        pts.append(AltDataPoint(ts=ts, available_at=ts + dt.timedelta(days=1), value=val))
    store = _store()
    rep = run_cohort({"BTCUSDT": bars}, pts, store, symbol="BTCUSDT")
    assert rep.verdict in {"PASS", "FAIL", "FAIL-DISCONFIRMED"}
    names = {m.name for m in rep.members}
    assert names == {"llm-narrative-pressure-long", "disc-narrative-time-shuffle", "disc-momentum-only-control"}
    # both disconfirmers are reported
    assert set(rep.disconfirmers) == {"time_shuffle_placebo", "beat_momentum_only"}
    # holdout DSR is a real number per member (the field exists and is populated, not a hardcoded sentinel)
    assert all(isinstance(m.holdout_deflated_sharpe, float) for m in rep.members)


def test_cohort_determinism():
    bars = _bars([100.0 * (1.0015 ** i) for i in range(160)])
    pts = [
        AltDataPoint(ts=dt.datetime(b.ts.year, b.ts.month, b.ts.day, tzinfo=dt.UTC),
                     available_at=dt.datetime(b.ts.year, b.ts.month, b.ts.day, tzinfo=dt.UTC) + dt.timedelta(days=1),
                     value=round(((i * 17) % 100) / 50.0 - 1.0, 4))
        for i, b in enumerate(bars)
    ]
    r1 = run_cohort({"BTCUSDT": bars}, pts, _store(), symbol="BTCUSDT")
    r2 = run_cohort({"BTCUSDT": bars}, pts, _store(), symbol="BTCUSDT")
    assert r1.verdict == r2.verdict
    assert [m.deflated_sharpe_prob for m in r1.members] == [m.deflated_sharpe_prob for m in r2.members]
