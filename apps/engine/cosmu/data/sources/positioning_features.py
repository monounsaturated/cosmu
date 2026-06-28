# intent: the PIT-honest FEATURES derived from the forward-hoarded Hyperliquid positioning snapshots
# (hyperliquid_positioning.py). Two features, both computed STRICTLY from values known at the capture instant:
#   (1) crowding_extreme_z — a z-score of NET positioning vs a trailing window (how stretched the crowd is, in
#       its own recent distribution). A large +z = crowded long (fade-down risk); large -z = crowded short
#       (squeeze risk). When the per-account net series is unavailable, it falls back to OI-notional × funding
#       sign as the aggregate crowding proxy (funding>0 ⇒ longs crowded), so the feature still computes from the
#       keyless aggregate poll alone.
#   (2) long_liq_density_norm — the long-side liquidation notional within the band, NORMALIZED by OI-notional
#       (so a thin coin with a small absolute number but a large share of its book at risk still ranks). This is
#       the "fuel for a down-cascade as a fraction of the whole book" read.
#
# invariants: PIT by construction — every input AltDataPoint already carries available_at == its capture
# instant, and a z-score at instant t uses ONLY the trailing window of points whose available_at <= t (the
# `align`/`read_asof` discipline the rest of the data layer uses). Pure (no I/O, no DB, no settings); offline
# unit-tested on synthetic snapshots. PROPOSE-ONLY: these are correlatable numeric series the Gate may score —
# never an edge by themselves. No look-ahead: the trailing window is strictly past-or-present.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from cosmu.data.providers._types import AltDataPoint

# Pinned transform versions — bump when the z-window or normalization changes so a gate-passed survivor that
# depends on these features stays re-runnable byte-for-byte (mirrors feature_registry's transform_version contract).
CROWDING_TRANSFORM_VERSION = "hl-positioning-crowding-v1"
LIQ_DENSITY_TRANSFORM_VERSION = "hl-positioning-liqdensity-v1"

# Minimum trailing observations before a z-score is defined (a window shorter than this yields no point — honest
# "not enough history yet", never a fabricated 0). At ~10-min cadence, 12 = ~2h of capture history.
DEFAULT_MIN_WINDOW = 12


@dataclass(frozen=True)
class FeaturePoint:
    """One derived feature value at a capture instant. ts == available_at == the instant it could be computed
    (the capture time of the LATEST input point), so it inherits the source snapshots' PIT honesty exactly."""

    ts: AltDataPoint  # carried as the underlying point so callers reuse the existing PIT (ts/available_at) stamps

    @property
    def value(self) -> float:
        return self.ts.value


def _rolling_z(values: list[float], *, min_window: int) -> list[float | None]:
    """For each index i, the z-score of values[i] against the trailing window values[:i+1] — STRICTLY past-or-
    present (the value at i is included; nothing future is). None until `min_window` points exist or when the
    trailing window has zero variance (an honest 'undefined', never a fabricated 0). Pure + deterministic."""
    out: list[float | None] = []
    for i in range(len(values)):
        window = values[: i + 1]
        if len(window) < min_window:
            out.append(None)
            continue
        mean = statistics.fmean(window)
        # population stdev over the trailing window; 0 variance → undefined z (None)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        sd = math.sqrt(var)
        out.append((values[i] - mean) / sd if sd > 0 else None)
    return out


def crowding_extreme_z(
    net_points: list[AltDataPoint],
    *,
    min_window: int = DEFAULT_MIN_WINDOW,
) -> list[AltDataPoint]:
    """The crowding-extreme feature: a trailing z-score of NET positioning. Each output point keeps the INPUT
    point's (ts, available_at) stamps — so the z computed at capture instant t is itself knowable at t (PIT).
    Returns one AltDataPoint per input instant that has enough trailing history (others are dropped, an honest
    gap). Input is one coin's hl_net_position_usd series (ascending by ts); for the aggregate-only fallback the
    caller passes the OI-notional × funding-sign proxy series (built by `aggregate_crowding_proxy`)."""
    pts = sorted(net_points, key=lambda p: p.available_at)
    zs = _rolling_z([p.value for p in pts], min_window=min_window)
    return [
        AltDataPoint(ts=p.ts, available_at=p.available_at, value=z)
        for p, z in zip(pts, zs, strict=True)
        if z is not None
    ]


def aggregate_crowding_proxy(
    oi_notional_points: list[AltDataPoint],
    funding_points: list[AltDataPoint],
) -> list[AltDataPoint]:
    """The keyless-aggregate crowding proxy when no per-account net series exists: signed crowd $ ≈ OI-notional ×
    sign(funding). funding > 0 ⇒ longs pay ⇒ crowd is net long ⇒ +ve; funding < 0 ⇒ crowd net short ⇒ -ve. Pairs
    the two series on identical capture instants (available_at), so the proxy is PIT (both inputs known at t).
    The z-score of THIS proxy is then the aggregate crowding-extreme signal."""
    fund_by_ts = {p.available_at: p.value for p in funding_points}
    out: list[AltDataPoint] = []
    for oi in sorted(oi_notional_points, key=lambda p: p.available_at):
        f = fund_by_ts.get(oi.available_at)
        if f is None:
            continue
        signed = oi.value * (1.0 if f > 0 else (-1.0 if f < 0 else 0.0))
        out.append(AltDataPoint(ts=oi.ts, available_at=oi.available_at, value=signed))
    return out


def long_liq_density_norm(
    long_liq_points: list[AltDataPoint],
    oi_notional_points: list[AltDataPoint],
) -> list[AltDataPoint]:
    """The long-side liquidation-density feature: long_liq_density_usd / oi_notional_usd at each capture instant —
    the share of the book that is long fuel within the liquidation band. Pairs the two series on identical capture
    instants (PIT: both known at t). A non-positive OI-notional denominator yields no point (honest skip). Output
    points keep the numerator point's (ts, available_at) stamps."""
    oi_by_ts = {p.available_at: p.value for p in oi_notional_points}
    out: list[AltDataPoint] = []
    for liq in sorted(long_liq_points, key=lambda p: p.available_at):
        denom = oi_by_ts.get(liq.available_at)
        if denom is None or denom <= 0:
            continue
        out.append(AltDataPoint(ts=liq.ts, available_at=liq.available_at, value=liq.value / denom))
    return out


__all__ = [
    "CROWDING_TRANSFORM_VERSION",
    "LIQ_DENSITY_TRANSFORM_VERSION",
    "DEFAULT_MIN_WINDOW",
    "crowding_extreme_z",
    "aggregate_crowding_proxy",
    "long_liq_density_norm",
]
