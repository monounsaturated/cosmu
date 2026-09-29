# intent: blockchain.com Charts API — a FREE, no-key, market-wide BITCOIN on-chain DataSource. Pulls
# daily network fundamentals (hashrate, transaction count, mempool size, unique active addresses) from
# the public api.blockchain.info/charts endpoint and turns each into a named, point-in-time,
# availability-stamped numeric feature. These are MARKET-WIDE on-chain series (scope is ignored — they
# describe the whole Bitcoin network, not one trading pair), and they are an orthogonal axis to price /
# funding / sentiment: real economic activity ON the chain.
#
# PIT CONTRACT (read before touching):
#   ts           = midnight UTC of the observation day (the day the on-chain metric was recorded)
#   available_at = ts + 1 day at 00:00 UTC
#                  blockchain.com aggregates a full UTC day and publishes the day-T point with ≥~1-day
#                  latency; we conservatively stamp next-day so we NEVER claim a value before it is
#                  realistically knowable. NO LOOK-AHEAD.
#   as_of        = a query returns the latest day whose available_at ≤ as_of.
#   gaps         = a missing day is ABSENT (value=None), NEVER zero-filled. A gap is unknown, not zero.
#   revisions    = recent on-chain points can be revised slightly as late blocks settle; we conservatively
#                  treat the next-day-stamped value as final (the 1-day lag absorbs late settlement) and
#                  do not rewrite banked history.
#
# Offline testability: inject _fetcher(url)->dict so the entire HTTP path is mockable. Tests run with a
# bundled fixture — no network, no key, deterministic, no CI flakiness.
#
# Four features (one DataSource instance per chart, distinguished by `metric`):
#   btc_hashrate          — estimated network hash rate (chart "hash-rate")
#   btc_tx_count          — confirmed transactions per day (chart "n-transactions")
#   btc_mempool_size      — mempool size in bytes (chart "mempool-size")
#   btc_active_addresses  — unique active addresses per day (chart "n-unique-addresses")
#
# Confidence is low (these are exploratory orthogonal features that must earn their place via OOS — the
# Gate is the disposal layer), but higher than pure-noise OSINT controls because on-chain activity is a
# genuine economic signal for BTC.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the parse/availability logic changes so a gate-passed survivor
# stays byte-for-byte re-runnable.
TRANSFORM_VERSION = "onchain-blockchain-v1"

# blockchain.com Charts API base — free, no key. Each chart is a daily time series of {x: unix, y: value}.
_API_BASE = "https://api.blockchain.info/charts"

# Availability lag: blockchain.com publishes a full UTC day's aggregate with ≥~1-day latency. We stamp
# available_at = midnight of T+1 (the opening moment of the NEXT UTC day) — conservative, never early.
_AVAILABILITY_LAG = timedelta(days=1)

# metric name (our feature key) → blockchain.com chart slug.
METRIC_CHART_MAP: dict[str, str] = {
    "btc_hashrate": "hash-rate",
    "btc_tx_count": "n-transactions",
    "btc_mempool_size": "mempool-size",
    "btc_active_addresses": "n-unique-addresses",
}


def _chart_for_metric(metric: str) -> str | None:
    """Resolve our metric key → blockchain.com chart slug. None = unknown metric (source disabled)."""
    return METRIC_CHART_MAP.get(metric)


def _url_for_chart(chart: str, *, timespan: str = "1year") -> str:
    """blockchain.com charts URL for one chart slug. sampled=false → full daily resolution."""
    params = urllib.parse.urlencode({"timespan": timespan, "format": "json", "sampled": "false"})
    return f"{_API_BASE}/{chart}?{params}"


def _parse_response(payload: dict) -> list[AltDataPoint]:
    """Parse a blockchain.com charts response into AltDataPoints.

    PIT contract:
      ts           = midnight UTC of the recorded day (normalized from the API's unix-second x)
      available_at = ts + 1 day (the earliest the daily aggregate is realistically knowable)
      gap          = absent point, never zero
    The API returns {"values": [{"x": <unix_seconds>, "y": <value>}, ...]}.
    """
    values = payload.get("values") or []
    out: list[AltDataPoint] = []
    for item in values:
        x = item.get("x")
        y = item.get("y")
        if x is None or y is None:
            continue
        try:
            raw = datetime.fromtimestamp(int(x), tz=UTC)
            # Normalize to midnight UTC of the observation day (charts are daily; x may carry an offset).
            ts = datetime(raw.year, raw.month, raw.day, tzinfo=UTC)
            available_at = ts + _AVAILABILITY_LAG  # day T+1 midnight UTC — first knowable moment
            out.append(AltDataPoint(ts=ts, available_at=available_at, value=float(y)))
        except (ValueError, OverflowError, OSError):
            continue
    return sorted(out, key=lambda p: p.ts)


class OnchainBlockchainSource:
    """blockchain.com daily BITCOIN on-chain fundamentals as a named, point-in-time DataSource.

    Each instance exposes ONE metric (chosen by the `metric` kwarg):
      btc_hashrate         — estimated network hash rate
      btc_tx_count         — confirmed transactions per day
      btc_mempool_size     — mempool size in bytes
      btc_active_addresses — unique active addresses per day

    These are MARKET-WIDE on-chain series (scope is part of the protocol but ignored — they describe the
    whole BTC network). PIT contract: available_at = ts + 1 day (conservative ≥1-day publication lag);
    a query for `as_of` returns the latest day whose available_at ≤ as_of — never look-ahead. Gaps are
    absent (value=None), never zero-fabricated.

    Confidence is low (exploratory orthogonal feature; the Gate is the disposal layer) but above pure
    noise — on-chain activity is a real economic signal for BTC.

    Offline testability: inject _fetcher(url)->dict; all HTTP is isolated behind that single callable, so
    tests are fully deterministic without a key, network, or monkeypatching.
    """

    name: str = "btc_hashrate"
    kind: SourceKind = "macro"
    metric: str = "btc_hashrate"
    prior: str = (
        "Bitcoin on-chain network fundamentals (hashrate, transaction count, mempool size, active "
        "addresses) measure REAL economic activity on the chain — an orthogonal axis to price, funding "
        "and sentiment. Rising active addresses / transactions can reflect organic demand; mempool "
        "congestion can reflect fee pressure; hashrate reflects miner commitment. available_at = obs "
        "day + 1 (conservative ≥1-day publication lag). Gaps are None (not 0). Low-confidence until "
        "validated out-of-sample — the Gate is the disposal layer."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.40  # low / exploratory — must earn its place via OOS
    lookback_timespan: str = "1year"  # how much trailing history to request per call

    def __init__(
        self,
        *,
        metric: str = "btc_hashrate",
        lookback_timespan: str = "1year",
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self.metric = metric
        self.name = metric  # the feature key IS the metric — keep name/metric consistent for the registry
        self.lookback_timespan = lookback_timespan
        self._fetcher: Callable[[str], Any] = _fetcher or self._live_fetch

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _live_fetch(self, url: str) -> Any:
        req = urllib.request.Request(
            url, headers={"User-Agent": "cosmu-engine/0.1 (contact.moncory@gmail.com)"}
        )
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_raw_series(self, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch raw on-chain AltDataPoints for this metric whose available_at ≤ as_of.

        A gap (no data for a day) is ABSENT from the returned list — never zero-fabricated.
        Returns [] if the metric is unknown or the API fails (graceful degradation, never raises)."""
        chart = _chart_for_metric(self.metric)
        if chart is None:
            return []
        url = _url_for_chart(chart, timespan=self.lookback_timespan)
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash the gate pass
            return []
        raw = _parse_response(payload if isinstance(payload, dict) else {})
        pts = [p for p in raw if p.available_at <= as_of]  # strict point-in-time
        return pts[-limit:]

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest on-chain value for this metric whose available_at ≤ as_of (point-in-time, no look-ahead).

        `scope` is part of the protocol but ignored (these series are market-wide on-chain fundamentals).
        Returns a None-valued SourceFeature if the metric is unknown, the API is unreachable, or nothing
        is knowable yet — NEVER raises, NEVER fabricates a 0 for a gap."""
        del scope  # market-wide; scope is protocol-required but unused
        raw = self.fetch_raw_series(as_of, limit=limit)
        latest: AltDataPoint | None = None
        for p in raw:
            if p.available_at <= as_of:
                latest = p  # ascending order → the last valid one is the latest knowable

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


def make_onchain_blockchain_sources() -> list[OnchainBlockchainSource]:
    """Construct one OnchainBlockchainSource per supported metric (live fetchers).

    Used by the registry to register all four BTC on-chain features at once."""
    return [OnchainBlockchainSource(metric=m) for m in METRIC_CHART_MAP]


__all__ = [
    "METRIC_CHART_MAP",
    "TRANSFORM_VERSION",
    "OnchainBlockchainSource",
    "_chart_for_metric",
    "_parse_response",
    "make_onchain_blockchain_sources",
]
