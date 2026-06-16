"""Offline, deterministic tests for the SEC EDGAR Form 4 net insider-buy DataSource.

Verified invariants (mirrors test_osint_opensky_daily.py):
  1. PIT contract: a filing accepted AFTER as_of is EXCLUDED (no look-ahead); the SourceFeature.available_at
     equals the LATEST acceptanceDateTime among the filings actually used.
  2. Gap honesty: a ticker not in the CIK map, or with no in-window open-market P/S filings, → value=None (not 0).
  3. Buy-heavy ticker → positive ratio; sell-heavy ticker → negative ratio.
  4. The pure net_buy_ratio helper: empty → None; all buys → +1; all sells → -1; window excludes old filings;
     future filings (accepted > as_of) excluded.
  5. low_confidence=True (confidence 0.30 < 0.5).
  6. transform_version is the pinned string; kind=="osint"; name=="insider_buy_ratio".
  7. DataSource-protocol compliance + registerable.
  8. No HTTP calls in any test (offline=True throughout).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cosmu.data.sources.sec_edgar import (
    TRANSFORM_VERSION,
    _CIK_BY_TICKER,
    _FIXTURE_TRANSACTIONS,
    SecEdgarInsiderSource,
    net_buy_ratio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_src(**kwargs) -> SecEdgarInsiderSource:
    """Return an offline source; tests pass a custom fixture to avoid coupling to the global default."""
    defaults = dict(offline=True)
    defaults.update(kwargs)
    return SecEdgarInsiderSource(**defaults)


# The fixtures (and these tests) are anchored to as_of = 2024-04-01, window = 90 days.
_AS_OF = datetime(2024, 4, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# PIT: a filing accepted after as_of is excluded; available_at = latest used filing's acceptanceDateTime
# ---------------------------------------------------------------------------

class TestPITContract:
    def test_filing_accepted_after_as_of_is_excluded(self):
        """TSLA's ONLY in-window filing is accepted 2024-04-15, AFTER as_of=2024-04-01 → excluded → None."""
        src = _make_src()
        f = src.query("TSLA", _AS_OF)
        assert f.value is None, "LOOK-AHEAD: a filing accepted after as_of must NOT be visible"
        assert f.available_at is None

    def test_filing_visible_once_as_of_reaches_acceptance(self):
        """At as_of = 2024-04-30 (>= TSLA's 2024-04-15 acceptance) the single buy is now knowable → +1."""
        src = _make_src()
        as_of = datetime(2024, 4, 30, tzinfo=UTC)
        f = src.query("TSLA", as_of)
        assert f.value == pytest.approx(1.0), "single open-market buy → ratio +1 once accepted"
        assert f.available_at == datetime(2024, 4, 15, 15, 0, tzinfo=UTC)

    def test_available_at_is_latest_used_acceptance(self):
        """AAPL's latest in-window used filing is the 2024-03-20 sale → that is the aggregate available_at."""
        src = _make_src()
        f = src.query("AAPL", _AS_OF)
        assert f.value is not None
        # in-window AAPL filings: 2024-02-10 P, 2024-03-05 P, 2024-03-20 S (the 2023-11-01 P is out of window)
        assert f.available_at == datetime(2024, 3, 20, 16, 0, tzinfo=UTC)

    def test_old_filing_outside_window_is_excluded(self):
        """AAPL's big 2023-11-01 buy is older than the 90d window ending 2024-04-01 → excluded from the ratio."""
        src = _make_src()
        f = src.query("AAPL", _AS_OF)
        # in-window: buys 8000+6000=14000, sells 1000 → (14000-1000)/15000 = 0.8667.
        # If the 50000 old buy leaked in, the ratio would be much closer to +1.
        assert f.value == pytest.approx((14_000.0 - 1_000.0) / 15_000.0)


# ---------------------------------------------------------------------------
# Gap honesty: missing / untracked → None, not 0
# ---------------------------------------------------------------------------

class TestGapHonesty:
    def test_untracked_ticker_returns_none(self):
        """A ticker NOT in the curated CIK map → value=None, available_at=None (gap, never 0)."""
        src = _make_src()
        f = src.query("ZZZZ", _AS_OF)
        assert f.value is None
        assert f.available_at is None

    def test_tracked_ticker_with_no_transactions_returns_none(self):
        """WMT is in the CIK map but has NO transactions → None (tracked-but-empty gap, not 0)."""
        src = _make_src()
        assert "WMT" in _CIK_BY_TICKER
        f = src.query("WMT", _AS_OF)
        assert f.value is None, "A no-data tracked ticker must yield None, NEVER 0"
        assert f.available_at is None

    def test_fetch_transactions_untracked_is_none_not_empty_list(self):
        """fetch_transactions distinguishes untracked (None) from tracked-empty ([])."""
        src = _make_src()
        assert src.fetch_transactions("ZZZZ") is None
        assert src.fetch_transactions("WMT") == []


# ---------------------------------------------------------------------------
# Buy-heavy / sell-heavy sign
# ---------------------------------------------------------------------------

class TestSign:
    def test_buy_heavy_ticker_is_positive(self):
        src = _make_src()
        f = src.query("AAPL", _AS_OF)
        assert f.value is not None and f.value > 0.0

    def test_sell_heavy_ticker_is_negative(self):
        src = _make_src()
        f = src.query("XOM", _AS_OF)
        # in-window XOM: sells 7000+5000=12000, buys 2000 → (2000-12000)/14000 < 0
        assert f.value is not None and f.value < 0.0
        assert f.value == pytest.approx((2_000.0 - 12_000.0) / 14_000.0)

    def test_ratio_is_bounded(self):
        src = _make_src()
        for ticker in ("AAPL", "XOM"):
            f = src.query(ticker, _AS_OF)
            assert f.value is not None
            assert -1.0 <= f.value <= 1.0


# ---------------------------------------------------------------------------
# Pure helper: net_buy_ratio
# ---------------------------------------------------------------------------

class TestNetBuyRatioHelper:
    def test_empty_returns_none(self):
        assert net_buy_ratio([], as_of=_AS_OF, window_days=90) is None

    def test_all_buys_is_plus_one(self):
        txns = [
            {"accepted": datetime(2024, 3, 1, tzinfo=UTC), "code": "P", "shares": 100.0},
            {"accepted": datetime(2024, 3, 10, tzinfo=UTC), "code": "P", "shares": 50.0},
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) == pytest.approx(1.0)

    def test_all_sells_is_minus_one(self):
        txns = [
            {"accepted": datetime(2024, 3, 1, tzinfo=UTC), "code": "S", "shares": 100.0},
            {"accepted": datetime(2024, 3, 10, tzinfo=UTC), "code": "S", "shares": 50.0},
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) == pytest.approx(-1.0)

    def test_balanced_is_zero(self):
        txns = [
            {"accepted": datetime(2024, 3, 1, tzinfo=UTC), "code": "P", "shares": 100.0},
            {"accepted": datetime(2024, 3, 2, tzinfo=UTC), "code": "S", "shares": 100.0},
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) == pytest.approx(0.0)

    def test_window_excludes_old_filings(self):
        """A buy older than the window is excluded; only the recent sell counts → -1."""
        txns = [
            {"accepted": datetime(2023, 6, 1, tzinfo=UTC), "code": "P", "shares": 1_000.0},  # > 90d old
            {"accepted": datetime(2024, 3, 15, tzinfo=UTC), "code": "S", "shares": 200.0},
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) == pytest.approx(-1.0)

    def test_future_filing_excluded_no_lookahead(self):
        """A filing accepted AFTER as_of is excluded; only the in-window buy counts → +1."""
        txns = [
            {"accepted": datetime(2024, 3, 15, tzinfo=UTC), "code": "P", "shares": 500.0},
            {"accepted": datetime(2024, 4, 20, tzinfo=UTC), "code": "S", "shares": 9_999.0},  # future
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) == pytest.approx(1.0)

    def test_non_open_market_codes_ignored(self):
        """Grants (A) / option exercise (M) / gifts (G) are ignored; only P/S count."""
        txns = [
            {"accepted": datetime(2024, 3, 1, tzinfo=UTC), "code": "A", "shares": 1_000_000.0},
            {"accepted": datetime(2024, 3, 2, tzinfo=UTC), "code": "M", "shares": 500_000.0},
            {"accepted": datetime(2024, 3, 3, tzinfo=UTC), "code": "P", "shares": 100.0},
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) == pytest.approx(1.0)

    def test_zero_and_bad_shares_skipped(self):
        """Zero/negative/garbage share counts are skipped; if nothing valid remains → None."""
        txns = [
            {"accepted": datetime(2024, 3, 1, tzinfo=UTC), "code": "P", "shares": 0.0},
            {"accepted": datetime(2024, 3, 2, tzinfo=UTC), "code": "S", "shares": None},
        ]
        assert net_buy_ratio(txns, as_of=_AS_OF, window_days=90) is None


# ---------------------------------------------------------------------------
# Metadata and protocol
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_low_confidence_is_true(self):
        src = _make_src()
        assert src.low_confidence is True
        assert src.confidence < 0.5
        assert src.confidence == pytest.approx(0.30)

    def test_transform_version_is_pinned(self):
        src = _make_src()
        assert src.transform_version == TRANSFORM_VERSION
        assert TRANSFORM_VERSION == "sec-edgar-insider-v1"

    def test_name_is_insider_buy_ratio_snake_case(self):
        src = _make_src()
        assert src.name == "insider_buy_ratio"
        assert src.metric == "insider_buy_ratio"
        assert "_" in src.name
        assert " " not in src.name

    def test_kind_is_osint(self):
        src = _make_src()
        assert src.kind == "osint"

    def test_prior_mentions_low_confidence_and_pit(self):
        src = _make_src()
        prior_lower = src.prior.lower()
        assert "low-confidence" in prior_lower or "low confidence" in prior_lower
        assert "acceptancedatetime" in prior_lower
        assert "no look-ahead" in prior_lower

    def test_query_returns_source_feature_with_correct_metadata(self):
        from cosmu.data.sources.registry import SourceFeature

        src = _make_src()
        f = src.query("AAPL", _AS_OF)
        assert isinstance(f, SourceFeature)
        assert f.name == "insider_buy_ratio"
        assert f.scope == "AAPL"
        assert f.transform_version == TRANSFORM_VERSION
        assert f.low_confidence is True
        assert f.confidence < 0.5

    def test_scope_is_uppercased(self):
        src = _make_src()
        f = src.query("aapl", _AS_OF)
        assert f.scope == "AAPL"
        assert f.value is not None


# ---------------------------------------------------------------------------
# DataSource protocol compliance
# ---------------------------------------------------------------------------

class TestDataSourceProtocol:
    def test_satisfies_datasource_protocol(self):
        from cosmu.data.sources.registry import DataSource

        src = _make_src()
        assert isinstance(src, DataSource)

    def test_registerable_in_registry(self):
        from cosmu.data.sources.registry import DataSourceRegistry

        src = _make_src()
        reg = DataSourceRegistry()
        reg.register(src)
        assert "insider_buy_ratio" in reg.names()
        catalog = reg.discover()
        entry = next(c for c in catalog if c["name"] == "insider_buy_ratio")
        assert entry["low_confidence"] is True
        assert entry["kind"] == "osint"


# ---------------------------------------------------------------------------
# CIK seed map sanity
# ---------------------------------------------------------------------------

class TestCikMap:
    def test_ciks_are_zero_padded_10_digits(self):
        for ticker, cik in _CIK_BY_TICKER.items():
            assert len(cik) == 10, f"{ticker} CIK must be zero-padded to 10 digits"
            assert cik.isdigit(), f"{ticker} CIK must be all digits"

    def test_seed_has_at_least_ten_tickers(self):
        assert len(_CIK_BY_TICKER) >= 10

    def test_fixture_tickers_are_in_cik_map(self):
        for ticker in _FIXTURE_TRANSACTIONS:
            assert ticker in _CIK_BY_TICKER


# ---------------------------------------------------------------------------
# No HTTP in any test — every source is offline; live network helpers are never called.
# ---------------------------------------------------------------------------

class TestNoHttp:
    def test_offline_is_default_in_tests(self):
        src = _make_src()
        assert src.offline is True

    def test_no_network_call_on_query(self, monkeypatch):
        """Patch urlopen to explode; an offline query must never reach it."""
        import cosmu.data.sources.sec_edgar as mod

        def _boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            raise AssertionError("NETWORK CALL in an offline test")

        monkeypatch.setattr(mod.urllib.request, "urlopen", _boom)
        src = _make_src()
        # exercise every public path
        for ticker in ("AAPL", "XOM", "TSLA", "WMT", "ZZZZ"):
            src.query(ticker, _AS_OF)
