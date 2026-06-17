"""Leakage tripwire — point-in-time audit on the FEATURE side (item 1).

The deterministic Gate validates whether a STRATEGY has edge after costs; it does NOT verify that the
FEATURE PIPELINE that fed it was point-in-time honest. A look-ahead bug UPSTREAM of the Gate produces a
survivor that is genuinely real on paper and zero/negative live — Gate-invisible. These tests assert the
single PIT invariant at every feature-side join + bridge: no value is ever used before its `available_at`.

Surfaces covered (the leakage-critical joins AI-written research code touches):
  - align_asof            (cosmu.data.backtest)         — the central per-bar as-of join
  - sum_funding_per_bar   (cosmu.data.backtest)         — the funding-carry accrual join
  - AltDataStore.read_asof / PgAltDataStore.read_asof   — the store-level PIT read (incl. sub-second boundary)
  - _snapshot             (cosmu.data.sources.altdata_bridges) — every managed alt-source bridge
  - FEATURE_REGISTRY                                    — every enabled feature declares as-of semantics

These run offline on deterministic fixtures (no network, no DB beyond an in-memory JSONL store).
A PASS here is NECESSARY, not sufficient: the disconfirmer harness (test_disconfirmer_harness) covers the
spurious/memorized class; this module covers look-ahead.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.data.backtest import align_asof, sum_funding_per_bar
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import AltDataStore

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(n: int, *, start: datetime = _T0, step: timedelta = timedelta(days=1)) -> list[Bar]:
    out = []
    for i in range(n):
        px = Decimal(100 + i)
        out.append(Bar(ts=start + i * step, open=px, high=px, low=px, close=px, volume=Decimal(1000)))
    return out


def _pt(ts: datetime, available_at: datetime, value: float) -> AltDataPoint:
    return AltDataPoint(ts=ts, available_at=available_at, value=value)


# --------------------------------------------------------------------------- align_asof (the central join)


def test_align_asof_never_uses_a_value_before_its_available_at():
    """A point whose `available_at` is AFTER a bar must never land on that bar — the core look-ahead guard."""
    bars = _bars(5)  # ts = day 0..4
    # value 42 is OBSERVED on day 0 but only AVAILABLE on day 3 (a 3-day publication lag).
    pts = [_pt(ts=bars[0].ts, available_at=bars[3].ts, value=42.0)]
    joined = align_asof(pts, bars)
    # Bars 0..2 (before available_at) must have NO entry; bars 3..4 (>= available_at) carry the value.
    assert bars[0].ts.isoformat() not in joined
    assert bars[1].ts.isoformat() not in joined
    assert bars[2].ts.isoformat() not in joined
    assert joined[bars[3].ts.isoformat()] == 42.0
    assert joined[bars[4].ts.isoformat()] == 42.0


def test_align_asof_boundary_is_knowable_at_bar_close():
    """available_at == bar.ts is ALLOWED (knowable at that bar's close) — the inclusive PIT boundary."""
    bars = _bars(3)
    pts = [_pt(ts=bars[1].ts, available_at=bars[1].ts, value=7.0)]
    joined = align_asof(pts, bars)
    assert bars[0].ts.isoformat() not in joined
    assert joined[bars[1].ts.isoformat()] == 7.0


def test_align_asof_carries_latest_available_revision_only():
    """When two revisions of the same observation exist, each bar sees only the revision available by then."""
    bars = _bars(6)
    pts = [
        _pt(ts=bars[0].ts, available_at=bars[1].ts, value=10.0),   # first print, available day 1
        _pt(ts=bars[0].ts, available_at=bars[4].ts, value=99.0),   # revision, available day 4
    ]
    joined = align_asof(pts, bars)
    assert bars[0].ts.isoformat() not in joined        # nothing available yet at day 0
    assert joined[bars[1].ts.isoformat()] == 10.0       # day 1..3 see the first print
    assert joined[bars[3].ts.isoformat()] == 10.0
    assert joined[bars[4].ts.isoformat()] == 99.0       # day 4+ see the revision


@pytest.mark.parametrize("seed", range(8))
def test_align_asof_property_no_value_predates_availability(seed):
    """Property sweep: across random stamps, EVERY joined value must come from a point whose available_at
    is <= the bar it landed on. Brute-force-verify the as-of contract holds universally."""
    rng = random.Random(f"align-asof-property-{seed}")
    bars = _bars(40)
    pts = []
    for idx in range(60):
        obs_i = rng.randint(0, 39)
        lag = rng.randint(0, 10)  # availability lag in days (>= 0; a real feed never knows before it observes)
        # A unique microsecond offset per point makes available_at distinct, so align_asof's forward-fill
        # winner is unambiguous (no tie-break to reason about) while staying within the same day.
        avail = bars[obs_i].ts + timedelta(days=lag, microseconds=idx)
        pts.append(_pt(ts=bars[obs_i].ts, available_at=avail, value=rng.uniform(-5, 5)))
    joined = align_asof(pts, bars)
    for bar in bars:
        key = bar.ts.isoformat()
        if key not in joined:
            continue
        # The joined value must be reproducible from ONLY the points available by this bar.
        avail_pts = [p for p in pts if p.available_at <= bar.ts]
        assert avail_pts, f"value present at {key} with no point available by then = LOOK-AHEAD"
        expected = max(avail_pts, key=lambda p: p.available_at).value
        assert joined[key] == expected


# --------------------------------------------------------------------------- sum_funding_per_bar (carry join)


def test_sum_funding_per_bar_excludes_future_settlements():
    """The funding-carry accrual join sums settlements in (prev_bar, bar.ts] only — never a future print."""
    bars = _bars(4)
    pts = [
        _pt(ts=bars[1].ts, available_at=bars[1].ts, value=0.01),   # lands on bar 1
        _pt(ts=bars[3].ts, available_at=bars[3].ts, value=0.02),   # lands on bar 3 — must NOT leak into bar 1/2
    ]
    accrued = sum_funding_per_bar(pts, bars)
    assert accrued.get(bars[1].ts.isoformat()) == pytest.approx(0.01)
    assert bars[2].ts.isoformat() not in accrued                  # no settlement in (bar1, bar2]
    assert accrued.get(bars[3].ts.isoformat()) == pytest.approx(0.02)


# --------------------------------------------------------------------------- store.read_asof (PIT read)


def test_read_asof_excludes_rows_available_after_as_of(tmp_path):
    """The store-level PIT read filters available_at <= as_of: a row that becomes available one microsecond
    after the as_of cut must NOT be returned (the sub-second look-ahead boundary the COLLATE "C" guard protects
    in Postgres; this asserts the same contract on the canonical in-memory store)."""
    store = AltDataStore(root=tmp_path)
    as_of = _T0 + timedelta(days=2)
    store.append("p", "BTCUSDT", "m", [
        _pt(ts=_T0, available_at=as_of - timedelta(microseconds=1), value=1.0),   # just before — included
        _pt(ts=_T0 + timedelta(days=1), available_at=as_of, value=2.0),           # exactly at — included
        _pt(ts=_T0 + timedelta(days=2), available_at=as_of + timedelta(microseconds=1), value=3.0),  # just after — EXCLUDED
    ])
    rows = store.read_asof("p", "BTCUSDT", "m", as_of)
    values = {r.value for r in rows}
    assert 1.0 in values
    assert 2.0 in values
    assert 3.0 not in values, "a row available AFTER as_of leaked into the PIT read = LOOK-AHEAD"


# --------------------------------------------------------------------------- bridges (_snapshot PIT invariant)


class _FakeFeat:
    def __init__(self, value, observed_ts, available_at):
        self.value = value
        self.observed_ts = observed_ts
        self.available_at = available_at


class _FakeSource:
    def __init__(self, feat):
        self._feat = feat

    def query(self, scope, as_of):  # noqa: ARG002 — bridges call query(scope, now)
        return self._feat


def test_snapshot_bridge_uses_source_available_at_and_never_back_dates():
    """`_snapshot` (every managed alt-source bridge) must stamp the point with the SOURCE's own available_at
    and never produce available_at < ts (you cannot know a reading before it was observed)."""
    from cosmu.data.sources.altdata_bridges import _snapshot

    observed = _T0
    avail = _T0 + timedelta(days=1)  # a 1-day publication lag
    src = _FakeSource(_FakeFeat(value=3.14, observed_ts=observed, available_at=avail))
    pts = _snapshot(src, "MARKET")
    assert len(pts) == 1
    assert pts[0].available_at == avail            # the source's OWN availability stamp, not now()
    assert pts[0].ts == observed
    assert pts[0].available_at >= pts[0].ts, "bridge produced available_at < ts = LOOK-AHEAD"


def test_snapshot_bridge_none_value_is_honest_gap_never_fabricated_zero():
    """A None reading yields [] (an honest gap), never a fabricated 0.0 — a gap masquerading as a real value
    is its own quiet leak (it injects a knowable-looking number where none existed)."""
    from cosmu.data.sources.altdata_bridges import _snapshot

    src = _FakeSource(_FakeFeat(value=None, observed_ts=_T0, available_at=_T0))
    assert _snapshot(src, "MARKET") == []


def test_every_real_bridge_emits_pit_honest_points_offline():
    """Drive every concrete bridge offline and assert any point it emits satisfies available_at >= ts. A
    bridge that degrades to [] (no key / no network) is fine; one that emits a back-dated point is a leak."""
    from cosmu.data.sources import altdata_bridges as br

    # (provider, a metric it owns, a scope). The conftest socket guard turns any live fetch into an exception
    # that _snapshot swallows to [] — so a provider with no `offline` kwarg is still network-free here; the ones
    # that DO carry `offline` may emit deterministic fixture points, which is where the invariant has teeth.
    cases = [
        (br.WeatherOpenMeteoIngestProvider(offline=True), "weather_hub_stress", "MARKET"),
        (br.OpenSkyDailyIngestProvider(offline=True), "opensky_daily_flights", "MARKET"),
        (br.OnchainBlockchainIngestProvider(), "btc_hashrate", "MARKET"),
        (br.ExoticControlsIngestProvider(offline=True), "usgs_earthquake_count", "MARKET"),
        (br.JetColocationIngestProvider(offline=True), "jet_colocation", "AAPL"),
        (br.SecEdgarIngestProvider(offline=True), "insider_buy_ratio", "AAPL"),
    ]
    for provider, metric, scope in cases:
        pts = provider.fetch_series(scope, metric, limit=10)
        for p in pts:
            assert p.available_at >= p.ts, (
                f"{type(provider).__name__} emitted a back-dated point (available_at < ts) = LOOK-AHEAD"
            )


# --------------------------------------------------------------------------- feature registry (declared PIT)


def test_every_enabled_feature_declares_asof_semantics_and_prior():
    """Every ENABLED feature must declare non-empty as-of semantics + a prior hypothesis. An enabled feature
    with no declared availability story is an un-auditable leakage surface — the registry is the contract a
    reviewer reads to know WHEN each value becomes knowable."""
    from cosmu.config.feature_registry import FEATURE_REGISTRY

    for f in FEATURE_REGISTRY:
        if not f.enabled:
            continue
        assert f.asof_semantics and f.asof_semantics.strip(), f"{f.name}: enabled feature with no asof_semantics"
        assert f.prior and f.prior.strip(), f"{f.name}: enabled feature with no prior"
