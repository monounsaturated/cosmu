# intent: Macro-liquidity FLOWS — a FREE, NO-KEY, point-in-time DataSource for the "how much fuel is in
# the system" lens, built on FRED's keyless fredgraph.csv endpoint (no API key required). The name reflects
# the operator lens: institutional / ETF-style risk appetite is downstream of system liquidity. This module
# turns two weekly Federal-Reserve balance-sheet series into named numeric features:
#
#   fed_balance_sheet_usd  — total Fed assets (WALCL), in USD millions. The Fed's balance sheet IS the base
#                            money supply; expansion (QE) is liquidity into the system, contraction (QT) is
#                            liquidity out. A first-order risk-asset driver.
#   net_liquidity_usd      — WALCL minus the Treasury General Account (WTREGEN). The TGA is cash the Treasury
#                            holds AT the Fed and thus DRAINED from the banking system; a rising TGA sterilizes
#                            balance-sheet liquidity, a falling TGA releases it. WALCL - TGA is the widely-used
#                            "net liquidity" proxy that has historically tracked risk-asset beta. Orthogonal to
#                            price / funding / sentiment / on-chain — it is a pure macro-plumbing read.
#
# Both series are FREE and require NO API KEY via the public CSV download:
#   https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL
#   https://fred.stlouisfed.org/graph/fredgraph.csv?id=WTREGEN
#
# PIT CONTRACT (the machine that never lies — read before touching):
#   ts           = the observation_date in the CSV (the WEEKLY reference date, a Wednesday for these series),
#                  normalized to midnight UTC.
#   available_at = ts + RELEASE_LAG_DAYS. The keyless fredgraph.csv carries NO realtime/vintage column, so we
#                  CANNOT read the true first-publication date here (unlike the ALFRED output_type=4 path in
#                  data/providers/macro.py). We therefore stamp a CONSERVATIVE publication-lag floor: WALCL /
#                  WTREGEN (the H.4.1 release) reference a Wednesday and publish the FOLLOWING Thursday, so the
#                  value is realistically knowable ~8 days after the reference date. We use 8 days — generous,
#                  never early. This biases AGAINST look-ahead (we under-claim availability, never over-claim).
#   gaps         = a missing / "." value is ABSENT (never zero-fabricated). For net_liquidity_usd, a day is
#                  ABSENT whenever EITHER WALCL or WTREGEN is missing for that date (no fabricated difference).
#   revisions    = fredgraph.csv returns the LATEST REVISED value (no vintage). The conservative 8-day floor
#                  absorbs the small weekly revisions; the store's append-only contract surfaces any later
#                  restatement rather than hiding it. (For revision-exact vintages, the ALFRED provider seam in
#                  data/providers/macro.py is the canonical path; this keyless module is the no-key convenience
#                  surface for the macro-plumbing lens.)
#
# Offline testability: inject `_fetcher(url) -> str` (CSV text) so the ENTIRE HTTP path is mockable; tests are
# fully deterministic with no network and no key. A network / shape failure degrades to a None-valued
# SourceFeature, NEVER raises (never aborts a gate pass).
#
# Confidence is moderate-low (the Gate is the disposal layer) but above pure noise — system liquidity is a
# well-established macro driver of risk-asset beta.

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the parse / availability / net-liquidity convention changes so a
# gate-passed survivor stays byte-for-byte re-runnable.
TRANSFORM_VERSION = "macro-liquidity-v1"

# The keyless fredgraph.csv carries no vintage column, so we stamp a CONSERVATIVE publication-lag floor.
# WALCL / WTREGEN are the weekly H.4.1 release: reference Wednesday, published the following Thursday → the
# value is realistically knowable ~8 days after the reference date. Generous, never early (anti-look-ahead).
_RELEASE_LAG = timedelta(days=8)

# FRED keyless CSV base + the two free series ids we own here.
_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_WALCL_SERIES = "WALCL"     # total Fed assets (USD millions), weekly
_WTREGEN_SERIES = "WTREGEN"  # Treasury General Account balance at the Fed (USD millions), weekly

# The market-wide metrics this module owns.
ETF_FLOW_METRICS: tuple[str, ...] = ("fed_balance_sheet_usd", "net_liquidity_usd")

# Per-metric declared priors — why an agent might care (low-confidence until OOS proves it).
_PRIORS: dict[str, str] = {
    "fed_balance_sheet_usd": (
        "Total Federal Reserve assets (WALCL) are the base money supply: balance-sheet EXPANSION (QE) "
        "pumps liquidity into the system (risk-on), CONTRACTION (QT) drains it. A first-order macro driver "
        "of risk-asset beta. Weekly, FREE, no key, conservatively knowable ~8 days after the reference "
        "date. Low-confidence until validated OOS — the Gate is the disposal layer."
    ),
    "net_liquidity_usd": (
        "Net liquidity = Fed total assets (WALCL) minus the Treasury General Account (WTREGEN). The TGA is "
        "cash drained from the banking system; a rising TGA sterilizes balance-sheet liquidity, a falling "
        "TGA releases it. WALCL - TGA is the widely-watched proxy that has historically tracked risk-asset "
        "beta — an orthogonal macro-plumbing read. Weekly, FREE, no key, conservatively knowable ~8 days "
        "after the reference date. Low-confidence until validated OOS — the Gate is the disposal layer."
    ),
}


def _parse_fredgraph_csv(csv_text: Any, series_id: str) -> dict[datetime, float]:
    """Parse a keyless fredgraph.csv body into a {midnight-UTC ts: value} map for one series.

    The CSV header is `observation_date,<SERIES_ID>`; a missing value is "." or empty and is DROPPED
    (absent, never zero-fabricated). Returns {} on any malformed input."""
    if not isinstance(csv_text, str):
        return {}
    out: dict[datetime, float] = {}
    lines = csv_text.splitlines()
    for line in lines:
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 2:
            continue
        date_raw, value_raw = cols[0], cols[1]
        # Skip the header row and any non-date cell.
        if value_raw in (".", "", series_id):
            continue
        try:
            day = datetime.fromisoformat(date_raw)
        except ValueError:
            continue  # header / preamble line
        ts = datetime(day.year, day.month, day.day, tzinfo=UTC)
        try:
            value = float(value_raw)
        except ValueError:
            continue
        out[ts] = value
    return out


def _points_from_map(ts_value: dict[datetime, float]) -> list[AltDataPoint]:
    """Turn a {ts: value} map into ascending AltDataPoints with the conservative publication-lag floor."""
    out = [
        AltDataPoint(ts=ts, available_at=ts + _RELEASE_LAG, value=val)
        for ts, val in ts_value.items()
    ]
    out.sort(key=lambda p: p.ts)
    return out


def _net_liquidity_points(
    walcl: dict[datetime, float], tga: dict[datetime, float]
) -> list[AltDataPoint]:
    """WALCL minus TGA per reference date. A date is ABSENT whenever EITHER series lacks it (no fabricated
    difference). available_at = ts + the conservative publication-lag floor."""
    out: list[AltDataPoint] = []
    for ts, assets in walcl.items():
        drain = tga.get(ts)
        if drain is None:
            continue  # no matching TGA → absent, never fabricate the difference
        out.append(AltDataPoint(ts=ts, available_at=ts + _RELEASE_LAG, value=assets - drain))
    out.sort(key=lambda p: p.ts)
    return out


class EtfFlowsSource:
    """Macro-liquidity (FRED keyless) as a named, point-in-time DataSource (free, NO key).

    Two market-wide metrics (selected by the `metric` kwarg; `scope` is ignored — these describe system-wide
    liquidity, not one trading pair):
      fed_balance_sheet_usd — total Fed assets, WALCL (USD millions)
      net_liquidity_usd     — WALCL minus the Treasury General Account, WTREGEN (USD millions)

    PIT contract: available_at = ts + 8 days (conservative H.4.1 publication-lag floor; the keyless CSV has
    no vintage column, so we under-claim availability rather than risk look-ahead). Gaps are absent
    AltDataPoints (never zero-fabricated); net_liquidity is absent whenever either input is missing. A
    network / shape failure returns a None-valued SourceFeature — NEVER raises, NEVER fabricates.

    Offline testability: inject `_fetcher(url) -> str` (CSV text) in the constructor. All HTTP is isolated
    behind that single callable, so tests are fully deterministic with no network and no key."""

    name: str = "fed_balance_sheet_usd"
    kind: SourceKind = "macro"
    metric: str = "fed_balance_sheet_usd"
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.48  # moderate-low — must earn its place via OOS (still < 0.5 → low_confidence)

    def __init__(
        self,
        *,
        metric: str = "fed_balance_sheet_usd",
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        if metric not in ETF_FLOW_METRICS:
            raise ValueError(
                f"unknown macro-liquidity metric {metric!r}; expected one of {ETF_FLOW_METRICS}"
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
            return resp.read().decode("utf-8")

    @staticmethod
    def _csv_url(series_id: str) -> str:
        return f"{_CSV_BASE}?id={series_id}"

    def _build_series(self) -> list[AltDataPoint]:
        """Fetch + parse the full series for this metric. Returns [] on any failure (never raises)."""
        try:
            walcl = _parse_fredgraph_csv(self._fetcher(self._csv_url(_WALCL_SERIES)), _WALCL_SERIES)
            if self.metric == "fed_balance_sheet_usd":
                return _points_from_map(walcl)
            tga = _parse_fredgraph_csv(self._fetcher(self._csv_url(_WTREGEN_SERIES)), _WTREGEN_SERIES)
            return _net_liquidity_points(walcl, tga)
        except Exception:  # noqa: BLE001 — network / 404 / shape → absent series, never crash the pass
            return []

    def fetch_raw_series(self, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch the market-wide series whose available_at <= as_of (strict point-in-time).

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


def make_etf_flow_sources() -> list[EtfFlowsSource]:
    """Build one EtfFlowsSource per owned metric — the convenience seam the registry registers."""
    return [EtfFlowsSource(metric=m) for m in ETF_FLOW_METRICS]


__all__ = [
    "ETF_FLOW_METRICS",
    "TRANSFORM_VERSION",
    "EtfFlowsSource",
    "_net_liquidity_points",
    "_parse_fredgraph_csv",
    "_points_from_map",
    "make_etf_flow_sources",
]
