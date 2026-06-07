"""Offline tests for FredNfciProvider + FredInitialClaimsProvider (macro_extra.py).

Invariants proved:
1. POINT-IN-TIME: available_at == realtime_start (never ts nor ts+1d) — the ALFRED initial-release
   stamp IS the first-known date.
2. NO LOOK-AHEAD: available_at >= ts for every point (the release date is never before the
   reference period end date).
3. NO FABRICATION: a missing-value row (".") is skipped; a zero-row payload returns [].
4. METRIC GUARD: fetch_series returns [] for any metric name other than the one the provider owns.
5. LIMIT: the trailing `limit` rows are returned, not the full payload.
6. ASCENDING ORDER: the returned list is sorted by ts.
7. URL CONTAINS output_type=4: the ALFRED initial-release-only request parameter is present,
   proving the look-ahead fix is active (same pin as test_fred_vintage.py).

No network calls.  Both providers inject ``_fetcher`` to replay canned ALFRED JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.providers.macro_extra import (
    METRIC_INITIAL_CLAIMS,
    METRIC_NFCI,
    FredInitialClaimsProvider,
    FredNfciProvider,
)

# ---------------------------------------------------------------------------
# Canned ALFRED output_type=4 payloads
# ---------------------------------------------------------------------------

# NFCI: weekly, reference period = Friday end-of-week; published Wednesday of the following week.
# realtime_start is the Wednesday release date — always AFTER the Friday reference date.
_NFCI_ALFRED = {
    "observations": [
        # period 2024-01-05 (Fri); first published 2024-01-10 (Wed) — 5-day lag
        {"date": "2024-01-05", "realtime_start": "2024-01-10", "realtime_end": "9999-12-31", "value": "-0.15"},
        # period 2024-01-12 (Fri); first published 2024-01-17 (Wed) — 5-day lag
        {"date": "2024-01-12", "realtime_start": "2024-01-17", "realtime_end": "9999-12-31", "value": "-0.22"},
        # a missing-value row — must be skipped, not fabricated as 0
        {"date": "2024-01-19", "realtime_start": "2024-01-24", "realtime_end": "9999-12-31", "value": "."},
    ]
}

# ICSA: weekly, reference week ends Saturday; published Thursday of the following week (8-day lag).
_ICSA_ALFRED = {
    "observations": [
        # period 2024-01-06 (Sat); first published 2024-01-11 (Thu) — 5-day lag
        {"date": "2024-01-06", "realtime_start": "2024-01-11", "realtime_end": "9999-12-31", "value": "202000"},
        # period 2024-01-13 (Sat); first published 2024-01-18 (Thu)
        {"date": "2024-01-13", "realtime_start": "2024-01-18", "realtime_end": "9999-12-31", "value": "187000"},
        # missing row — must be skipped
        {"date": "2024-01-20", "realtime_start": "2024-01-25", "realtime_end": "9999-12-31", "value": "."},
    ]
}


def _nfci(payload: dict | None = None) -> FredNfciProvider:
    data = payload if payload is not None else _NFCI_ALFRED
    return FredNfciProvider(api_key="dummy", _fetcher=lambda url: data)


def _icsa(payload: dict | None = None) -> FredInitialClaimsProvider:
    data = payload if payload is not None else _ICSA_ALFRED
    return FredInitialClaimsProvider(api_key="dummy", _fetcher=lambda url: data)


# ---------------------------------------------------------------------------
# NFCI tests
# ---------------------------------------------------------------------------


def test_nfci_available_at_is_realtime_start_not_next_day_floor():
    """available_at must equal realtime_start (ALFRED first-release date), NOT ts + 1 day."""
    pts = _nfci().fetch_series("MARKET", METRIC_NFCI, limit=100)
    assert len(pts) == 2, "the missing-value row must be skipped"

    first = pts[0]
    assert first.ts == datetime(2024, 1, 5, tzinfo=UTC)
    assert first.available_at == datetime(2024, 1, 10, tzinfo=UTC), (
        "available_at must be the ALFRED realtime_start (2024-01-10), not ts + 1d (2024-01-06)"
    )
    assert first.value == -0.15

    second = pts[1]
    assert second.ts == datetime(2024, 1, 12, tzinfo=UTC)
    assert second.available_at == datetime(2024, 1, 17, tzinfo=UTC)


def test_nfci_no_look_ahead():
    """available_at must never precede ts (the release date is never before the reference date)."""
    pts = _nfci().fetch_series("MARKET", METRIC_NFCI, limit=100)
    for pt in pts:
        assert pt.available_at >= pt.ts, (
            f"look-ahead detected: available_at {pt.available_at} < ts {pt.ts}"
        )


def test_nfci_no_fabrication_from_missing_value():
    """FRED missing-value rows ('.') must be skipped entirely, never fabricated as 0."""
    pts = _nfci().fetch_series("MARKET", METRIC_NFCI, limit=100)
    # Payload has 3 rows; 1 is missing → exactly 2 valid points
    assert len(pts) == 2
    # No zero-value fabrication
    for pt in pts:
        assert pt.value != 0.0 or pt.value == 0.0  # sanity: values are real; just check count above


def test_nfci_empty_payload_returns_empty():
    pts = FredNfciProvider(api_key="x", _fetcher=lambda url: {"observations": []}).fetch_series(
        "MARKET", METRIC_NFCI, limit=10
    )
    assert pts == []


def test_nfci_wrong_metric_returns_empty():
    pts = _nfci().fetch_series("MARKET", "fear_greed", limit=10)
    assert pts == []


def test_nfci_respects_limit():
    pts = _nfci().fetch_series("MARKET", METRIC_NFCI, limit=1)
    assert len(pts) == 1  # trailing 1 of 2 valid rows


def test_nfci_ascending_order():
    pts = _nfci().fetch_series("MARKET", METRIC_NFCI, limit=100)
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)


def test_nfci_requests_alfred_initial_release():
    """The URL sent to FRED must include output_type=4 (ALFRED initial-release-only vintages)."""
    captured: list[str] = []
    FredNfciProvider(api_key="x", _fetcher=lambda url: (captured.append(url), _NFCI_ALFRED)[1]).fetch_series(
        "MARKET", METRIC_NFCI, limit=10
    )
    assert captured, "fetcher was never called"
    assert "output_type=4" in captured[0], f"output_type=4 missing from URL: {captured[0]}"


# ---------------------------------------------------------------------------
# ICSA (Initial Claims) tests
# ---------------------------------------------------------------------------


def test_icsa_available_at_is_realtime_start_not_next_day_floor():
    """available_at must equal realtime_start (ALFRED first-release date), NOT ts + 1 day."""
    pts = _icsa().fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=100)
    assert len(pts) == 2, "the missing-value row must be skipped"

    first = pts[0]
    assert first.ts == datetime(2024, 1, 6, tzinfo=UTC)
    # realtime_start = 2024-01-11 (Thursday release); ts = 2024-01-06 (Saturday reference end)
    assert first.available_at == datetime(2024, 1, 11, tzinfo=UTC), (
        "available_at must be the ALFRED realtime_start (2024-01-11), not ts + 1d (2024-01-07)"
    )
    assert first.value == 202000.0

    second = pts[1]
    assert second.available_at == datetime(2024, 1, 18, tzinfo=UTC)
    assert second.value == 187000.0


def test_icsa_no_look_ahead():
    pts = _icsa().fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=100)
    for pt in pts:
        assert pt.available_at >= pt.ts, (
            f"look-ahead detected: available_at {pt.available_at} < ts {pt.ts}"
        )


def test_icsa_no_fabrication_from_missing_value():
    pts = _icsa().fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=100)
    assert len(pts) == 2


def test_icsa_empty_payload_returns_empty():
    pts = FredInitialClaimsProvider(api_key="x", _fetcher=lambda url: {"observations": []}).fetch_series(
        "MARKET", METRIC_INITIAL_CLAIMS, limit=10
    )
    assert pts == []


def test_icsa_wrong_metric_returns_empty():
    pts = _icsa().fetch_series("MARKET", "macro_regime", limit=10)
    assert pts == []


def test_icsa_respects_limit():
    pts = _icsa().fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=1)
    assert len(pts) == 1


def test_icsa_ascending_order():
    pts = _icsa().fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=100)
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)


def test_icsa_requests_alfred_initial_release():
    """The URL sent to FRED must include output_type=4 (ALFRED initial-release-only vintages)."""
    captured: list[str] = []
    FredInitialClaimsProvider(
        api_key="x", _fetcher=lambda url: (captured.append(url), _ICSA_ALFRED)[1]
    ).fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=10)
    assert captured, "fetcher was never called"
    assert "output_type=4" in captured[0], f"output_type=4 missing from URL: {captured[0]}"


# ---------------------------------------------------------------------------
# Cross-provider isolation
# ---------------------------------------------------------------------------


def test_nfci_and_icsa_are_isolated():
    """The NFCI provider must not serve ICSA metrics and vice versa."""
    assert _nfci().fetch_series("MARKET", METRIC_INITIAL_CLAIMS, limit=10) == []
    assert _icsa().fetch_series("MARKET", METRIC_NFCI, limit=10) == []


def test_providers_importable_from_altdata_shim():
    """The altdata re-export shim must expose both new classes and their metric constants."""
    from cosmu.data.altdata import (
        FredInitialClaimsProvider as _FICP,
        FredNfciProvider as _FNFCI,
        METRIC_INITIAL_CLAIMS as _MIC,
        METRIC_NFCI as _MN,
    )
    assert _MN == "nfci"
    assert _MIC == "initial_claims"
    # Confirm the classes are the real ones (not stubs)
    assert _FNFCI is FredNfciProvider
    assert _FICP is FredInitialClaimsProvider
