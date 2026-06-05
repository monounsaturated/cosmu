# intent: prove the normalized social derivations (cosmu/research/social_norm.py) are point-in-time honest —
# every derived point's available_at is inherited from the latest RAW point it consumes, so the backtest's
# as-of join can never read a normalized value before we'd have known it. Also pins the math (log-change, z).

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar
from cosmu.research.social_norm import _accel, _rolling_z, derive_social_alt


def _pt(day: int, value: float) -> AltDataPoint:
    ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=value)


def test_accel_is_log_change_with_later_availability():
    pts = [_pt(0, 100.0), _pt(1, 200.0), _pt(2, 100.0)]
    out = _accel(pts)
    assert [round(p.value, 6) for p in out] == [round(math.log(2), 6), round(math.log(0.5), 6)]
    # each derived point is stamped with the LATER raw point's availability (no look-ahead)
    assert out[0].available_at == pts[1].available_at
    assert out[1].available_at == pts[2].available_at


def test_accel_skips_nonpositive():
    assert _accel([_pt(0, 0.0), _pt(1, 100.0)]) == []  # cannot take log of a zero/neg base


def test_rolling_z_uses_only_trailing_window():
    # constant then a jump: the z of the jump must be computed from the trailing window incl. itself, never future
    pts = [_pt(i, 10.0) for i in range(12)] + [_pt(12, 20.0)]
    out = _rolling_z(pts)
    # first 9 are undefined (need >= 10 points); the constant run has zero std -> skipped; the jump is the first
    # point with non-zero std in its window
    last = out[-1]
    assert last.ts == pts[-1].ts
    assert last.value > 0  # the jump is ABOVE its trailing mean
    assert last.available_at == pts[-1].available_at  # PIT: known when the jumping day closes


def test_rolling_z_no_lookahead_monotonic_availability():
    pts = [_pt(i, float(i * i + 1)) for i in range(40)]  # strictly varying so std>0
    out = _rolling_z(pts)
    avail = [p.available_at for p in out]
    assert avail == sorted(avail)  # availabilities are non-decreasing in ts — never reordered from the future


def _bars(n: int) -> list[Bar]:
    base = datetime(2024, 1, 2, tzinfo=UTC)  # one day AFTER the first social ts -> first social is available
    out = []
    for i in range(n):
        ts = base + timedelta(days=i)
        one = Decimal("1")
        out.append(Bar(ts=ts, open=one, high=one, low=one, close=one, volume=one))
    return out


def test_derive_social_alt_emits_features_and_broadcasts_btc():
    class P:
        def __init__(self, vol, gal):
            self.vol, self.gal = vol, gal

        def fetch_series(self, symbol, metric, *, limit):  # noqa: ARG002
            base = 1000.0 if symbol == "BTCUSDT" else 500.0
            if metric == "social_volume":
                return [_pt(i, base * (1.0 + 0.1 * i)) for i in range(40)]
            if metric == "galaxy_score":
                return [_pt(i, 40.0 + (i % 7)) for i in range(40)]
            return []

    market = {"BTCUSDT": _bars(40), "ETHUSDT": _bars(40)}
    out = derive_social_alt(market, P(None, None))
    assert "social_volume_accel" in out["ETHUSDT"]
    assert "social_attention_z" in out["ETHUSDT"]
    assert "social_excess_attention_z" in out["ETHUSDT"]
    assert "galaxy_score_z" in out["ETHUSDT"]
    # BTC contagion feature is present on the ALT (broadcast), and identical to BTC's own accel series
    assert "btc_social_accel" in out["ETHUSDT"]
    assert out["ETHUSDT"]["btc_social_accel"] == out["BTCUSDT"]["btc_social_accel"]
