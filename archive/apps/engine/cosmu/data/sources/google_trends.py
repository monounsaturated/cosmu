# intent: Google Trends search-interest signal as a named, point-in-time DataSource.
# Wraps pytrends (pip install pytrends) for historical weekly interest-over-time data.
# Satisfies the DataSource protocol (registry.py) so any agent can discover and query it by name.
#
# ============================================================
# CRITICAL REVISION-SAFETY WARNING — READ BEFORE RELYING ON THIS SOURCE
# ============================================================
# Google Trends RESCALES all historical values whenever the query window changes.
# A fresh fetch today for the window [2022-01-01, 2024-01-01] can return DIFFERENT
# numbers for 2022-09 than a fetch made in 2022 for the same date — because Trends
# normalises the whole window to 0-100 relative to the new peak.
#
# Consequences for point-in-time backtesting:
#   1. LOOK-AHEAD contamination: the score you "knew" in 2022 is re-calibrated against
#      activity up to the fetch date, which you could not have known then.
#   2. REVISION hazard: every re-ingest silently rewrites historical values if the
#      peak of the new window differs from the peak of the previous window.
#   3. These effects make the source LIKELY NO-GO for direct use as a backtest feature
#      without explicit normalisation anchoring (e.g. always fix the window to a
#      rolling 90-day lookback flushed weekly and treated as a SNAPSHOT, never spliced
#      across windows).
#
# This adapter DOCUMENTS and surfaces the hazard, it does NOT hide it:
#   - available_at is set to the fetch time (when we called Trends), NOT to the week
#     being described. A 2022-09 data point fetched in 2026 has available_at=2026-now.
#   - The docstring, low_confidence flag (confidence=0.2), and this comment block are
#     the only safeguards. The Gate must earn OOS evidence before trusting this source.
#   - profile-source verdict: REVIEW / likely NO-GO for backtest; acceptable for
#     paper alerting (each bar you fetch only the CURRENT snapshot).
#
# PIT contract (as honest as we can be given the vendor):
#   ts         = the Monday of the weekly Trends bucket
#   available_at = UTC timestamp of the ACTUAL HTTP fetch (not the week end — the data
#                  is only known when we fetched it, and it may be rescaled tomorrow)
#   value      = normalised search interest 0-100 (Trends' own unit)
#
# Offline testability: inject _fetcher(keywords, timeframe) -> DataFrame so CI runs with
# no network, no pytrends import, no Google API rate-limit.
#
# Dependency: pytrends (pip install pytrends) — documented optional. Without it, import
# fails loudly at instantiation so the operator knows to pip-install it.

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cosmu.data.sources.registry import SourceFeature, SourceKind

logger = logging.getLogger("cosmu.data.sources.google_trends")

# Frozen transform id — bump if the window/aggregation logic changes so any downstream
# survivor feature remains byte-for-byte reproducible.
TRANSFORM_VERSION = "gtrends-weekly-v1"

# Default crypto search keywords — broad enough to catch retail attention spikes.
# Narrow keywords (e.g. "bitcoin halving") are more specific but riskier to rescale.
DEFAULT_KEYWORDS: tuple[str, ...] = ("bitcoin", "crypto")

# Recommended rolling window for each fetch — short enough that the rescaling anchor
# stays close to "now" and the next fetch's rescaling does not move it far.
DEFAULT_TIMEFRAME = "today 3-m"  # pytrends format: trailing 90 days of weekly data


def _import_pytrends() -> Any:
    """Lazy import so the module loads even when pytrends is absent (tests inject _fetcher)."""
    try:
        from pytrends.request import TrendReq  # type: ignore[import]
        return TrendReq
    except ImportError as exc:
        raise ImportError(
            "pytrends is required for GoogleTrendsSource. Install it with: pip install pytrends"
        ) from exc


def _live_fetcher(keywords: list[str], timeframe: str) -> Any:
    """Real pytrends HTTP fetch — returns a pandas DataFrame with 'isPartial' column stripped."""
    TrendReq = _import_pytrends()
    pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)
    pt.build_payload(keywords, timeframe=timeframe, geo="")
    df = pt.interest_over_time()
    if df.empty:
        return df
    if "isPartial" in df.columns:
        df = df.drop(columns=["isPartial"])
    return df


@dataclass
class GoogleTrendsSource:
    """Google Trends weekly search interest as a named, point-in-time DataSource.

    REVISION-SAFETY: Trends rescales all historical values when the query window changes.
    This is a REVIEW / NO-GO source for backtesting (the Gate must earn OOS evidence).
    It is acceptable for PAPER alerting where each fetch is a fresh current snapshot.

    PIT contract:
      ts         = Monday of the weekly bucket (the observation period)
      available_at = UTC timestamp of the ACTUAL fetch (not ts; the value is only knowable
                     after you pull it, and it may differ on the next pull)
      value      = mean search interest across keywords for that week (0-100 Trends units)

    Confidence declared at 0.2 (low) — the source must earn its place via OOS; the Gate
    down-weights low-confidence sources until proven.

    Offline / no-key path: inject `_fetcher(keywords, timeframe) -> DataFrame`. The test
    passes a canned DataFrame with no network call or pytrends import.
    """

    name: str = "gtrends_search_interest"
    kind: SourceKind = "social"
    metric: str = "gtrends_search_interest"
    prior: str = (
        "Retail search interest (Google Trends) spikes around attention-driven price moves; "
        "historically correlates with speculative inflows but is noisy and rescales on every "
        "re-fetch (REVIEW/NO-GO for backtesting; paper alerting only until Gate validates). "
        "Must earn OOS evidence before entering any live strategy."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.2  # low — revision hazard + no proven OOS edge; must earn its place
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS
    timeframe: str = DEFAULT_TIMEFRAME
    _fetcher: Callable[[list[str], str], Any] | None = field(default=None, repr=False)

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5  # always True at 0.2

    def _get_fetcher(self) -> Callable[[list[str], str], Any]:
        return self._fetcher if self._fetcher is not None else _live_fetcher

    def fetch_series(self, *, limit: int = 52) -> list[_TrendsPoint]:
        """Fetch the rolling Trends series, returning up to `limit` most-recent weekly points.

        available_at is the ACTUAL fetch UTC time — NOT the week-end date — because the
        rescaling means a 2022-09 value fetched in 2026 is NOT the same as the value that
        was knowable in 2022. The Gate must see the full available_at gap and treat every
        historical row as arriving only at ingest time.

        Returns [] on any error (network / rate-limit / missing pytrends) so a dead source
        never aborts an ingest pass.
        """
        fetch_fn = self._get_fetcher()
        fetch_at = datetime.now(tz=UTC)
        try:
            df = fetch_fn(list(self.keywords), self.timeframe)
        except Exception:  # noqa: BLE001 — never crash the ingest pass
            logger.warning("GoogleTrendsSource: fetch failed", exc_info=True)
            return []

        if df is None or (hasattr(df, "empty") and df.empty):
            return []

        pts: list[_TrendsPoint] = []
        # df.index is a DatetimeIndex (weekly, tz-aware or naive); columns = keyword names.
        for ts_raw, row in df.iterrows():
            try:
                # Make ts UTC-aware (Trends may return tz-naive or tz-aware).
                if hasattr(ts_raw, "tzinfo") and ts_raw.tzinfo is not None:
                    ts = ts_raw.to_pydatetime().astimezone(UTC)
                else:
                    ts = ts_raw.to_pydatetime().replace(tzinfo=UTC)
                # Mean across all requested keywords for that week.
                vals = [float(row[kw]) for kw in self.keywords if kw in row.index]
                if not vals:
                    continue
                value = sum(vals) / len(vals)
                # available_at = fetch_at (the moment we retrieved the data).
                # A future re-fetch may return a different value for the same ts — that is the
                # revision hazard. We stamp it honestly so the store's append-only contract
                # surfaces the revision rather than silently overwriting history.
                pts.append(_TrendsPoint(ts=ts, available_at=fetch_at, value=value))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue

        # Sort ascending, keep last `limit` points.
        pts.sort(key=lambda p: p.ts)
        return pts[-limit:]

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest weekly search-interest snapshot knowable at `as_of`.

        Point-in-time guarantee: returns the most-recent fetched snapshot whose available_at
        <= as_of. If no snapshot has been ingested yet for a past as_of, returns value=None.
        For the PAPER use case, as_of ~ now() and the result is the current reading.
        """
        del scope  # market-wide; scope is part of the DataSource protocol but unused here
        pts = self.fetch_series(limit=limit)
        latest: _TrendsPoint | None = None
        for pt in pts:
            if pt.available_at <= as_of:
                latest = pt
            else:
                break
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


# Lightweight internal container — not exported as AltDataPoint to avoid coupling.
@dataclass(frozen=True)
class _TrendsPoint:
    ts: datetime         # Monday of the weekly Trends bucket
    available_at: datetime  # UTC fetch time (revision hazard: same ts may have diff value next fetch)
    value: float         # mean search interest 0-100 across keywords


__all__ = [
    "DEFAULT_KEYWORDS",
    "DEFAULT_TIMEFRAME",
    "TRANSFORM_VERSION",
    "GoogleTrendsSource",
]
