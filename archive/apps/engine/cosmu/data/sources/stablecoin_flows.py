# intent: Stablecoin FLOWS — a FREE, no-key, market-wide point-in-time DataSource for the on-chain
# dry-powder lens. DefiLlama already exposes the stablecoin market-cap LEVEL (defillama.stablecoin_mcap);
# this module exposes the daily FLOW (the day-over-day CHANGE) plus the chain DOMINANCE split, which is an
# orthogonal axis: minting (positive net flow) is fresh fiat entering crypto = risk-on fuel; redemptions
# (negative net flow) are capital leaving. The level can sit flat for weeks while flow flips sign first —
# the derivative leads the level.
#
# Two market-wide metrics, both from the SAME free DefiLlama endpoint (no key, generous rate limit):
#   stablecoin_net_flow_usd  — day-T total stablecoin mcap MINUS day-(T-1) mcap, in USD (signed)
#   stablecoin_eth_share     — fraction of total stablecoin float that sits on Ethereum [0,1]
#                              (a risk-appetite / chain-rotation read: a falling ETH share = float
#                              rotating to higher-throughput / lower-fee chains)
#
# Source endpoint:
#   https://stablecoins.llama.fi/stablecoincharts/all          (total float per day, peg-typed)
#   https://stablecoins.llama.fi/stablecoincharts/Ethereum     (Ethereum-only float per day)
#
# PIT CONTRACT (the machine that never lies — read before touching):
#   ts           = midnight UTC of the observation day.
#   available_at = ts + 1 day. A daily aggregate is finalized after the UTC day closes, so the EARLIEST
#                  day-T's value is knowable is day T+1 (00:00 UTC). For the NET FLOW we additionally
#                  require day-(T-1) to exist; the flow point inherits day-T's +1d availability (both
#                  inputs are knowable by then). A conservative floor — never look-ahead.
#   gaps         = a missing day is ABSENT (never zero-fabricated). A net-flow point is ABSENT whenever
#                  the immediately-preceding day is missing (we never invent a delta across a gap).
#   revisions    = DefiLlama may re-state very recent days as chains re-sync; the +1d floor absorbs late
#                  settlement and the store's append-only contract surfaces revisions, never hides them.
#
# Offline testability: inject `_fetcher(url) -> list` so the ENTIRE HTTP path is mockable; tests are fully
# deterministic with no network and no key. A network / shape failure degrades to a None-valued
# SourceFeature, NEVER raises (never aborts a gate pass).
#
# Confidence is low/exploratory (the Gate is the disposal layer) but above pure noise — stablecoin flow is
# a genuine liquidity signal for crypto.

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the parse / availability / flow convention changes so a gate-passed
# survivor stays byte-for-byte re-runnable.
TRANSFORM_VERSION = "stablecoin-flows-v1"

# A daily aggregate is finalized after the UTC day closes → knowable next day. Conservative; never early.
_AVAILABILITY_LAG = timedelta(days=1)

# Free, no-key DefiLlama stablecoins endpoints.
_CHART_ALL_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
_CHART_ETH_URL = "https://stablecoins.llama.fi/stablecoincharts/Ethereum"

# The market-wide metrics this module owns.
STABLECOIN_FLOW_METRICS: tuple[str, ...] = ("stablecoin_net_flow_usd", "stablecoin_eth_share")

# Per-metric declared priors — why an agent might care (low-confidence until OOS proves it).
_PRIORS: dict[str, str] = {
    "stablecoin_net_flow_usd": (
        "Net daily stablecoin minting (today's total float minus yesterday's) is fresh fiat ENTERING "
        "crypto when positive (risk-on fuel) and capital REDEEMING out when negative. The flow leads the "
        "level: the derivative flips sign before the slow-moving market-cap level moves. Daily, free, "
        "knowable day T+1. Low-confidence until validated OOS — the Gate is the disposal layer."
    ),
    "stablecoin_eth_share": (
        "Share of total stablecoin float that sits on Ethereum. A falling ETH share is float rotating to "
        "cheaper / higher-throughput chains (a risk-appetite + chain-rotation read); a rising share is "
        "consolidation back onto the settlement layer. Daily, free, knowable day T+1. Low-confidence "
        "until validated OOS — the Gate is the disposal layer."
    ),
}


def _extract_total_circulating(row: dict) -> float | None:
    """Pull the total circulating USD from a stablecoincharts row, tolerating DefiLlama's nested shapes.

    Preferred: row["totalCirculatingUSD"] as a dict of {peg_type: usd} → sum the values.
    Fallbacks: a flat numeric totalCirculatingUSD, or totalCirculating (dict or numeric)."""
    for key in ("totalCirculatingUSD", "totalCirculating"):
        val = row.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            try:
                s = sum(float(v) for v in val.values() if v is not None)
            except (ValueError, TypeError):
                continue
            return s if s > 0 else None
        try:
            f = float(val)
        except (ValueError, TypeError):
            continue
        return f if f > 0 else None
    return None


def _daily_totals(payload: Any) -> list[tuple[datetime, float]]:
    """Parse a stablecoincharts payload into ascending (midnight-UTC ts, total_usd) pairs.

    A row with a missing / non-positive total is dropped (absent, never zero-fabricated)."""
    if not isinstance(payload, list):
        return []
    out: list[tuple[datetime, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        if raw_date is None:
            continue
        try:
            raw = datetime.fromtimestamp(int(raw_date), tz=UTC)
        except (ValueError, TypeError, OSError, OverflowError):
            continue
        ts = datetime(raw.year, raw.month, raw.day, tzinfo=UTC)  # normalize to midnight UTC
        total = _extract_total_circulating(row)
        if total is None or total <= 0:
            continue
        out.append((ts, total))
    out.sort(key=lambda p: p[0])
    return out


def _parse_net_flow(payload: Any) -> list[AltDataPoint]:
    """Build signed daily NET-FLOW points: value = total(T) - total(T-1).

    A flow point is ABSENT whenever the immediately-preceding calendar day is missing — we never invent a
    delta across a gap. available_at = ts(T) + 1 day (both inputs are knowable by then)."""
    totals = _daily_totals(payload)
    out: list[AltDataPoint] = []
    prev_ts: datetime | None = None
    prev_val: float | None = None
    for ts, val in totals:
        if prev_ts is not None and prev_val is not None and ts - prev_ts == timedelta(days=1):
            out.append(AltDataPoint(ts=ts, available_at=ts + _AVAILABILITY_LAG, value=val - prev_val))
        prev_ts, prev_val = ts, val
    return out


def _parse_eth_share(all_payload: Any, eth_payload: Any) -> list[AltDataPoint]:
    """Build the Ethereum-share series: value = total_eth(T) / total_all(T), clamped to [0,1].

    Only days present in BOTH series produce a point (a gap on either side → absent, never fabricated).
    available_at = ts + 1 day."""
    all_totals = dict(_daily_totals(all_payload))
    eth_totals = dict(_daily_totals(eth_payload))
    out: list[AltDataPoint] = []
    for ts, eth in eth_totals.items():
        whole = all_totals.get(ts)
        if whole is None or whole <= 0:
            continue
        share = eth / whole
        if share < 0:
            share = 0.0
        elif share > 1:
            share = 1.0
        out.append(AltDataPoint(ts=ts, available_at=ts + _AVAILABILITY_LAG, value=share))
    out.sort(key=lambda p: p.ts)
    return out


class StablecoinFlowsSource:
    """DefiLlama stablecoin FLOW + chain-split as a named, point-in-time DataSource (free, no key).

    Two market-wide metrics (selected by the `metric` kwarg; `scope` is ignored — these describe the whole
    stablecoin float, not one trading pair):
      stablecoin_net_flow_usd — signed day-over-day change in total stablecoin mcap (USD)
      stablecoin_eth_share    — fraction of total float on Ethereum [0,1]

    PIT contract: available_at = ts + 1 day (a daily aggregate is finalized after the UTC day closes; the
    earliest day-T is knowable is day T+1). Net-flow points are absent across a missing day (no delta
    across a gap). Gaps are absent AltDataPoints (never zero-fabricated). A network / shape failure returns
    a None-valued SourceFeature — NEVER raises, NEVER fabricates.

    Offline testability: inject `_fetcher(url) -> list` in the constructor. All HTTP is isolated behind that
    single callable, so tests are fully deterministic with no network and no key."""

    name: str = "stablecoin_net_flow_usd"
    kind: SourceKind = "macro"
    metric: str = "stablecoin_net_flow_usd"
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.42  # low / exploratory — must earn its place via OOS

    def __init__(
        self,
        *,
        metric: str = "stablecoin_net_flow_usd",
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        if metric not in STABLECOIN_FLOW_METRICS:
            raise ValueError(
                f"unknown stablecoin-flow metric {metric!r}; expected one of {STABLECOIN_FLOW_METRICS}"
            )
        self.metric = metric
        self.name = metric  # the metric IS the discoverable feature name (consistent with feature_registry)
        self.prior = _PRIORS[metric]
        self._fetcher: Callable[[str], Any] = _fetcher or self._live_fetch

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _live_fetch(self, url: str) -> Any:
        req = urllib.request.Request(
            url, headers={"User-Agent": "cosmu-engine/0.1 (contact.moncory@gmail.com)"}
        )
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 — fixed host
            return json.loads(resp.read().decode("utf-8"))

    def _build_series(self) -> list[AltDataPoint]:
        """Fetch + parse the full series for this metric. Returns [] on any failure (never raises)."""
        try:
            if self.metric == "stablecoin_net_flow_usd":
                return _parse_net_flow(self._fetcher(_CHART_ALL_URL))
            return _parse_eth_share(self._fetcher(_CHART_ALL_URL), self._fetcher(_CHART_ETH_URL))
        except Exception:  # noqa: BLE001 — network / 404 / shape → absent series, never crash the pass
            return []

    def fetch_raw_series(self, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch the market-wide daily series whose available_at <= as_of (strict point-in-time).

        A gap is ABSENT from the returned list — never zero-fabricated. Returns [] on any failure."""
        pts = [p for p in self._build_series() if p.available_at <= as_of]
        return pts[-limit:] if limit and len(pts) > limit else pts

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest market-wide value whose available_at <= as_of (point-in-time, no look-ahead).

        `scope` is part of the DataSource protocol but unused (this is a market-wide series).
        Returns a None-valued SourceFeature if the API is unreachable or nothing is knowable yet."""
        del scope  # market-wide; reported scope is fixed to "MARKET"
        raw = self.fetch_raw_series(as_of, limit=limit)
        latest: AltDataPoint | None = raw[-1] if raw else None
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(latest.value) if latest else None,
            available_at=latest.available_at if latest else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


def make_stablecoin_flow_sources() -> list[StablecoinFlowsSource]:
    """Build one StablecoinFlowsSource per owned metric — the convenience seam the registry registers."""
    return [StablecoinFlowsSource(metric=m) for m in STABLECOIN_FLOW_METRICS]


__all__ = [
    "STABLECOIN_FLOW_METRICS",
    "TRANSFORM_VERSION",
    "StablecoinFlowsSource",
    "_daily_totals",
    "_extract_total_circulating",
    "_parse_eth_share",
    "_parse_net_flow",
    "make_stablecoin_flow_sources",
]
