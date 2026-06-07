"""Extended FRED macro series: NFCI (financial conditions) + initial jobless claims.

These two weekly series complement the existing daily FRED bundle (macro_extra.py keeps them
isolated so they can be wired by the orchestrator without touching the catalog or _STORE_PROVIDER_OF).

POINT-IN-TIME CONTRACT
-----------------------
Both series are fetched via ALFRED ``output_type=4`` (initial-release-only vintages), exactly like
``FredMacroProvider``.  Each observation carries ``realtime_start`` = the date FRED first published
that value; ``available_at = max(realtime_start, ts)`` so no bar ever knows a number it could not
have known.

Series details (both free, key optional):
  NFCI  — Chicago Fed National Financial Conditions Index (weekly, ends-of-week Friday).
           Published each Wednesday for the previous week's end date.
           A negative NFCI = looser-than-average financial conditions (bullish macro).
           Release lag: the Wednesday after the Friday reference date (≈ 5 calendar days).
           ALFRED honours this: realtime_start is typically the release Wednesday.
  ICSA  — Initial Jobless Claims (weekly, week ending Saturday).
           Published each Thursday for the prior week (≈ 8-day lag).
           A rising ICSA = labour-market deterioration (bearish macro).
           ALFRED's realtime_start reflects the Thursday release date.

Both carry real multi-day publication lags; the ALFRED realtime_start is the honest first-known
date, so ``available_at`` is never earlier than the actual release.

Revision policy: ICSA is sometimes revised the following week; NFCI is occasionally revised on
re-publication.  The ALFRED output_type=4 request returns ONLY the initial release — later
revisions are NOT included.  If a backtest reruns on a fresh ALFRED pull it may see a different
initial-release value than a prior pull (ALFRED stores the full vintage history; initial-release
is the row with the EARLIEST realtime_start for each period).  The store's append-only contract
handles this correctly: later revisions append new rows; the ``available_at``-gated read always
returns what was knowable at the query time.

Offline-testable: inject ``_fetcher(url) -> dict`` to replay a canned ALFRED payload; tests
never touch the network.
"""

from __future__ import annotations

from collections.abc import Callable

from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.macro import FredMacroProvider

# FRED series ids for the two new metrics.  These are stable public identifiers.
NFCI_SERIES = "NFCI"   # Chicago Fed National Financial Conditions Index (weekly)
ICSA_SERIES = "ICSA"   # Initial Claims (Insured Unemployment) (weekly)

# Semantic metric names used in the alt-data store and the registration snippet.
METRIC_NFCI = "nfci"
METRIC_INITIAL_CLAIMS = "initial_claims"


class FredNfciProvider:
    """FRED NFCI (Chicago Fed National Financial Conditions Index).

    Weekly; published each Wednesday for the prior week ending Friday.  Uses ALFRED
    ``output_type=4`` so ``available_at == realtime_start`` (the actual release Wednesday),
    never the earlier reference Friday — no look-ahead.

    Wraps ``FredMacroProvider`` so the ALFRED PIT logic is DRY: this class adds ONLY the
    NFCI-specific metric guard and series id.

    Offline-testable: pass ``_fetcher`` to replay canned ALFRED JSON without network access.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.stlouisfed.org/fred",
        *,
        _fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self._inner = FredMacroProvider(api_key=api_key, base_url=base_url, _fetcher=_fetcher)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """Return ascending NFCI AltDataPoints (trailing ``limit`` rows); [] for any other metric."""
        if metric != METRIC_NFCI:
            return []
        pts = self._inner.fetch_series(symbol, NFCI_SERIES, limit=limit)
        return pts[-limit:] if limit and len(pts) > limit else pts


class FredInitialClaimsProvider:
    """FRED Initial Jobless Claims (ICSA).

    Weekly; published each Thursday for the week ending the prior Saturday (≈ 8-day lag).
    Uses ALFRED ``output_type=4`` so ``available_at == realtime_start`` (the actual release
    Thursday), never the earlier reference Saturday — no look-ahead.

    Wraps ``FredMacroProvider`` so the ALFRED PIT logic is DRY.

    Offline-testable: pass ``_fetcher`` to replay canned ALFRED JSON without network access.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.stlouisfed.org/fred",
        *,
        _fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self._inner = FredMacroProvider(api_key=api_key, base_url=base_url, _fetcher=_fetcher)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """Return ascending ICSA AltDataPoints (trailing ``limit`` rows); [] for any other metric."""
        if metric != METRIC_INITIAL_CLAIMS:
            return []
        pts = self._inner.fetch_series(symbol, ICSA_SERIES, limit=limit)
        return pts[-limit:] if limit and len(pts) > limit else pts
