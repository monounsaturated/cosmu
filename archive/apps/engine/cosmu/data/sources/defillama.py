# intent: DefiLlama — a FREE, no-key, market-wide point-in-time DataSource for the crypto macro lens.
# Two endpoints on https://api.llama.fi (no API key, no rate-limit for reasonable crawl rates):
#   defi_tvl          — daily TOTAL DeFi TVL across all chains    (/v2/historicalChainTvl)
#   stablecoin_mcap   — daily TOTAL circulating stablecoin market cap (/stablecoins + /stablecoincharts/all)
# These are MARKET-WIDE risk-appetite / liquidity reads, not per-symbol: rising TVL + a growing stablecoin
# float are the dry powder + on-chain risk-on signal; a draining stablecoin mcap is liquidity leaving crypto.
#
# This adapter satisfies the DataSource protocol (registry.py) so any agent can discover + PIT-query it by
# name. It mirrors the house pattern (see wikipedia_pageviews.py / multiasset.py):
#   - inject `_fetcher(url) -> dict|list` so the ENTIRE HTTP path is mockable (deterministic offline tests)
#   - a network / shape failure degrades to a None-valued SourceFeature, NEVER raises (never aborts a pass)
#   - gaps are ABSENT AltDataPoints, NEVER zero-fabricated
#
# PIT contract (the machine that never lies):
#   ts           = midnight UTC of the observation day (the day the TVL / mcap level is for)
#   available_at = ts + 1 day — a daily aggregate is finalized after the day closes, so the EARLIEST we
#                  could have known day-T's value is day T+1 (00:00 UTC). A conservative floor, never
#                  look-ahead. (Same convention as the legacy DefiLlamaTvlProvider + multiasset daily.)
#   revisions    = DefiLlama may re-state very recent days as chains re-sync; we stamp the conservative
#                  +1d floor and surface revisions through the store's append-only contract, never hide them.
#
# Note: a legacy `DefiLlamaTvlProvider` already lives in data/providers/onchain.py (the older AltDataProvider
# seam, wired into ingest/run.py for the `defi_tvl` feature). This module is the NEWER named-DataSource seam
# that the registry discovers; it ADDS the stablecoin_mcap metric and the discoverable-by-name surface
# without touching the legacy ingest path. Additive, no regressions.

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the parse / availability convention changes so a gate-passed survivor
# stays re-runnable byte-for-byte.
TRANSFORM_VERSION = "defillama-daily-v1"

# A daily aggregate is finalized after the day closes, so we'd have known it the NEXT day — a conservative
# point-in-time floor (mirrors FRED / CBOE / multiasset / the legacy DefiLlamaTvlProvider). Never look-ahead.
_AVAILABILITY_LAG = timedelta(days=1)

# Free, no-key DefiLlama endpoints.
_API_BASE = "https://api.llama.fi"
_TVL_URL = f"{_API_BASE}/v2/historicalChainTvl"
# /stablecoins gives the per-asset totals; /stablecoincharts/all gives the daily TOTAL mcap time series.
_STABLECOIN_CHART_URL = f"{_API_BASE}/stablecoins/stablecoincharts/all"

# The market-wide metrics this module owns. Each maps to one endpoint + one parser.
DEFILLAMA_METRICS: tuple[str, ...] = ("defi_tvl", "stablecoin_mcap")

# Per-metric declared priors — why an agent might care (low-confidence until OOS proves it).
_PRIORS: dict[str, str] = {
    "defi_tvl": (
        "Total DeFi TVL is a market-wide on-chain risk-appetite / liquidity gauge: rising TVL is capital "
        "committing on-chain (risk-on), a sharp drain is liquidity leaving. Daily, free, knowable day T+1. "
        "Low-confidence until validated OOS."
    ),
    "stablecoin_mcap": (
        "Total stablecoin market cap is crypto's dry powder: a growing float is fiat waiting to deploy "
        "(risk-on fuel), a shrinking float is capital redeeming out of crypto (risk-off). Daily, free, "
        "knowable day T+1. Low-confidence until validated OOS."
    ),
}


def _parse_tvl(payload: Any) -> list[AltDataPoint]:
    """Parse /v2/historicalChainTvl: [{"date": <unix_seconds>, "tvl": <usd>}, ...].

    PIT: available_at = ts + 1 day. A non-positive / missing tvl is ABSENT (never zero-fabricated)."""
    if not isinstance(payload, list):
        return []
    out: list[AltDataPoint] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        raw_tvl = row.get("tvl")
        if raw_date is None or raw_tvl is None:
            continue
        try:
            ts = datetime.fromtimestamp(int(raw_date), tz=UTC)
            tvl = float(raw_tvl)
        except (ValueError, TypeError, OSError):
            continue
        if tvl <= 0:
            continue  # missing / not-yet-aggregated day → absent, not zero
        out.append(AltDataPoint(ts=ts, available_at=ts + _AVAILABILITY_LAG, value=tvl))
    return sorted(out, key=lambda p: p.ts)


def _parse_stablecoin_mcap(payload: Any) -> list[AltDataPoint]:
    """Parse /stablecoins/stablecoincharts/all: a daily TOTAL stablecoin mcap time series.

    DefiLlama returns rows shaped like:
      {"date": "<unix_seconds>", "totalCirculatingUSD": {"peggedUSD": <usd>, ...}}
    The total mcap for a day = sum of the per-peg-type circulating values. We also tolerate a flat
    numeric `totalCirculatingUSD` (older shape) and a `totalCirculating` fallback.

    PIT: available_at = ts + 1 day. A non-positive / missing total is ABSENT (never zero-fabricated)."""
    if not isinstance(payload, list):
        return []
    out: list[AltDataPoint] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        if raw_date is None:
            continue
        try:
            ts = datetime.fromtimestamp(int(raw_date), tz=UTC)
        except (ValueError, TypeError, OSError):
            continue
        total = _extract_total_circulating(row)
        if total is None or total <= 0:
            continue  # missing / not-yet-aggregated day → absent, not zero
        out.append(AltDataPoint(ts=ts, available_at=ts + _AVAILABILITY_LAG, value=total))
    return sorted(out, key=lambda p: p.ts)


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
            return float(val)
        except (ValueError, TypeError):
            continue
    return None


class DefiLlamaSource:
    """DefiLlama market-wide daily series as a named, point-in-time DataSource (free, no key).

    Two metrics (selected by the `metric` kwarg, both MARKET-WIDE — `scope` is ignored):
      defi_tvl        — total DeFi TVL across all chains (USD)
      stablecoin_mcap — total circulating stablecoin market cap (USD)

    PIT contract: available_at = ts + 1 day (a daily aggregate is finalized after the day closes; the
    earliest day-T is knowable is day T+1). Gaps are absent AltDataPoints (never zero-fabricated).
    A network / shape failure returns a None-valued SourceFeature — NEVER raises, NEVER fabricates.

    Offline testability: inject `_fetcher(url) -> dict|list` in the constructor. All HTTP is isolated
    behind that single callable, so tests are fully deterministic with no network and no key."""

    name: str = "defi_tvl"
    kind: SourceKind = "macro"
    metric: str = "defi_tvl"
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.45  # tier1 / low-confidence — must earn its place via OOS

    def __init__(
        self,
        *,
        metric: str = "defi_tvl",
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        if metric not in DEFILLAMA_METRICS:
            raise ValueError(f"unknown DefiLlama metric {metric!r}; expected one of {DEFILLAMA_METRICS}")
        self.metric = metric
        self.name = metric  # the metric IS the discoverable feature name (consistent with feature_registry)
        self.prior = _PRIORS[metric]
        self._fetcher: Callable[[str], Any] = _fetcher or self._live_fetch

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _live_fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1 (github.com/monounsaturated/cosmu)"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 — fixed host
            return json.loads(resp.read().decode("utf-8"))

    def _url(self) -> str:
        return _TVL_URL if self.metric == "defi_tvl" else _STABLECOIN_CHART_URL

    def _parse(self, payload: Any) -> list[AltDataPoint]:
        return _parse_tvl(payload) if self.metric == "defi_tvl" else _parse_stablecoin_mcap(payload)

    def fetch_raw_series(self, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch the market-wide daily series whose available_at <= as_of (strict point-in-time).

        A gap is ABSENT from the returned list — never zero-fabricated. Returns [] on any failure."""
        try:
            payload = self._fetcher(self._url())
        except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash
            return []
        pts = [p for p in self._parse(payload) if p.available_at <= as_of]
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


def make_defillama_sources() -> list[DefiLlamaSource]:
    """Build one DefiLlamaSource per owned metric — the convenience seam the registry registers."""
    return [DefiLlamaSource(metric=m) for m in DEFILLAMA_METRICS]


__all__ = [
    "DEFILLAMA_METRICS",
    "TRANSFORM_VERSION",
    "DefiLlamaSource",
    "_extract_total_circulating",
    "_parse_stablecoin_mcap",
    "_parse_tvl",
    "make_defillama_sources",
]
