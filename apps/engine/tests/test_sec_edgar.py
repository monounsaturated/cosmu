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
  8. No HTTP calls in the default run: every test is offline / monkeypatched. The one live-network test
     (TestLiveSecEdgarIntegration) is opt-in (COSMU_LIVE_SEC_TEST=1) AND marked allow_network, so CI stays offline.
  9. LIVE-PATH REGRESSION GUARD: the Form 4 ownership-doc URL strips EDGAR's xsl HTML-rendering prefix
     (primaryDocument "xslF345X06/form4.xml" → raw "form4.xml"), so the parser reads structured XML and
     extracts >0 transactions on real filings (TestLivePathXslPrefixStripped / TestParseOwnershipDocStructuredXml).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

import cosmu.data.sources.sec_edgar as sec_mod
from cosmu.data.sources.sec_edgar import (
    _CIK_BY_TICKER,
    _FIXTURE_TRANSACTIONS,
    TRANSFORM_VERSION,
    SecEdgarInsiderSource,
    _fetch_form4_transactions,
    _parse_acceptance,
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


# ---------------------------------------------------------------------------
# DATA-HONESTY: a fetch FAILURE must NOT fabricate a 0 datapoint. The ERROR path (network/parse failure
# on the LIVE fetch) yields NO observation (None), distinct from a genuine EMPTY filing (a real successful
# 0 reading that net_buy_ratio renders as None). These tests exercise the LIVE path with the network
# helpers monkeypatched in-process — they make NO real HTTP call.
# ---------------------------------------------------------------------------

class TestErrorPathVsEmptyData:
    _CIK = _CIK_BY_TICKER["AAPL"]

    def test_index_unreachable_returns_none_not_empty_list(self, monkeypatch):
        """The submissions index GET fails (None) → FETCH FAILURE sentinel None, NOT [] (no observation)."""
        monkeypatch.setattr(sec_mod, "_get_json", lambda url, *, timeout: None)
        result = _fetch_form4_transactions(self._CIK, timeout=1.0)
        assert result is None, "a failed index fetch must be None (no observation), never []"

    def test_index_malformed_returns_none(self, monkeypatch):
        """A non-dict submissions payload (garbage) is a parse FAILURE → None, never a fabricated empty."""
        monkeypatch.setattr(sec_mod, "_get_json", lambda url, *, timeout: ["unexpected", "shape"])
        assert _fetch_form4_transactions(self._CIK, timeout=1.0) is None

    def test_network_exception_returns_none_not_partial_list(self, monkeypatch):
        """A mid-stream exception AFTER some transactions were collected must discard the partial list and
        return None — a truncated list would fabricate a WRONG ratio (the core data-honesty hole)."""

        # A valid submissions index advertising two Form 4 filings...
        def _fake_get_json(url, *, timeout):
            return {
                "filings": {
                    "recent": {
                        "form": ["4", "4"],
                        "accessionNumber": ["0000000000-24-000001", "0000000000-24-000002"],
                        "acceptanceDateTime": [
                            "2024-03-01T12:00:00.000Z",
                            "2024-03-10T12:00:00.000Z",
                        ],
                        "primaryDocument": ["a.xml", "b.xml"],
                    }
                }
            }

        calls = {"n": 0}

        # ...but the SECOND ownership-doc fetch blows up mid-stream after the first (a SELL) was collected.
        def _flaky_parse(doc_url, *, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return [("S", 9_999.0)]  # a partial (bearish-only) collection
            raise OSError("connection reset mid-stream")

        monkeypatch.setattr(sec_mod, "_get_json", _fake_get_json)
        monkeypatch.setattr(sec_mod, "_parse_ownership_doc", _flaky_parse)
        result = _fetch_form4_transactions(self._CIK, timeout=1.0)
        assert result is None, "a mid-stream failure must discard the partial list → None, not a ratio"

    def test_successful_empty_fetch_returns_empty_list_not_none(self, monkeypatch):
        """A SUCCESSFUL fetch of a tracked issuer that genuinely has NO Form 4 filings → real [] (an empty
        reading), distinct from the None failure sentinel. net_buy_ratio([]) then renders it as None."""
        monkeypatch.setattr(
            sec_mod,
            "_get_json",
            lambda url, *, timeout: {"filings": {"recent": {"form": ["10-K", "8-K"]}}},
        )
        result = _fetch_form4_transactions(self._CIK, timeout=1.0)
        assert result == [], "a successful no-Form-4 fetch is a real empty reading ([]), not None"
        assert net_buy_ratio(result, as_of=_AS_OF, window_days=90) is None  # real empty → None, not 0

    def test_query_on_fetch_failure_yields_none_value_never_zero(self, monkeypatch):
        """End-to-end: a LIVE query whose fetch fails yields value=None / available_at=None — NEVER a 0."""
        monkeypatch.setattr(sec_mod, "_get_json", lambda url, *, timeout: None)
        src = SecEdgarInsiderSource(offline=False, timeout=1.0)
        f = src.query("AAPL", _AS_OF)
        assert f.value is None, "a failed fetch must NOT fabricate a 0 — it is no observation (None)"
        assert f.value != 0.0
        assert f.available_at is None

    def test_query_on_partial_then_fail_yields_none_value_never_fabricated_ratio(self, monkeypatch):
        """End-to-end: a partial-then-fail LIVE fetch must NOT surface a spurious (bearish) partial ratio."""

        def _fake_get_json(url, *, timeout):
            return {
                "filings": {
                    "recent": {
                        "form": ["4", "4"],
                        "accessionNumber": ["0000000000-24-000001", "0000000000-24-000002"],
                        "acceptanceDateTime": [
                            "2024-03-01T12:00:00.000Z",
                            "2024-03-10T12:00:00.000Z",
                        ],
                        "primaryDocument": ["a.xml", "b.xml"],
                    }
                }
            }

        calls = {"n": 0}

        def _flaky_parse(doc_url, *, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return [("S", 9_999.0)]
            raise OSError("connection reset mid-stream")

        monkeypatch.setattr(sec_mod, "_get_json", _fake_get_json)
        monkeypatch.setattr(sec_mod, "_parse_ownership_doc", _flaky_parse)
        src = SecEdgarInsiderSource(offline=False, timeout=1.0)
        f = src.query("AAPL", _AS_OF)
        assert f.value is None, "must not surface a -1 ratio fabricated from a truncated fetch"
        assert f.available_at is None

    def test_successful_empty_fetch_through_query_is_none_not_zero(self, monkeypatch):
        """End-to-end: a SUCCESSFUL but transaction-free LIVE fetch still yields value=None (a real gap)."""
        monkeypatch.setattr(
            sec_mod,
            "_get_json",
            lambda url, *, timeout: {"filings": {"recent": {"form": ["10-K"]}}},
        )
        src = SecEdgarInsiderSource(offline=False, timeout=1.0)
        f = src.query("AAPL", _AS_OF)
        assert f.value is None  # genuine empty → None (never a fabricated 0)
        assert f.available_at is None


class TestLivePathXslPrefixStripped:
    """LIVE-PATH REGRESSION GUARD (deterministic, no HTTP).

    For Form 4, EDGAR's primaryDocument is the XSL-TRANSFORMED HTML RENDERING path, e.g.
    "xslF345X06/form4.xml". That rendered HTML contains NONE of the structured
    nonDerivativeTransaction/transactionCode/transactionShares nodes the parser needs, so building the doc URL
    from primaryDocument VERBATIM made _parse_ownership_doc return 0 transactions on every live filing —
    insider_buy_ratio was ALWAYS None in production (the offline fixtures hid it; tests passed).

    The fix strips the leading xsl directory prefix so we fetch the RAW structured XML (the bare filename).
    These tests pin that the doc URL handed to the parser is the prefix-stripped one, NOT the xsl path.
    """

    _CIK = _CIK_BY_TICKER["AAPL"]

    def _index_with_primary(self, primary_doc: str):
        return {
            "filings": {
                "recent": {
                    "form": ["4"],
                    "accessionNumber": ["0001140361-26-025622"],
                    "acceptanceDateTime": ["2026-06-15T12:00:00.000Z"],
                    "primaryDocument": [primary_doc],
                }
            }
        }

    def test_xsl_prefix_stripped_from_doc_url(self, monkeypatch):
        """primaryDocument="xslF345X06/form4.xml" → the parser is asked for .../form4.xml (raw XML), and the
        URL contains NO 'xslF345X06' segment. This is the exact regression that broke the live path."""
        seen: dict[str, str] = {}
        monkeypatch.setattr(
            sec_mod, "_get_json", lambda url, *, timeout: self._index_with_primary("xslF345X06/form4.xml")
        )

        def _capture(doc_url, *, timeout):
            seen["url"] = doc_url
            return [("P", 1_000.0)]

        monkeypatch.setattr(sec_mod, "_parse_ownership_doc", _capture)
        result = _fetch_form4_transactions(self._CIK, timeout=1.0)
        assert "url" in seen, "the ownership doc was never fetched"
        assert "xslF345X06" not in seen["url"], (
            "REGRESSION: the doc URL still points at the XSL HTML rendering, which has no structured "
            "transaction nodes — the parser will extract 0 transactions on every live filing"
        )
        assert seen["url"].endswith("/form4.xml"), seen["url"]
        # un-padded CIK + de-hyphenated accession + bare filename, exactly as SEC's Archives path expects
        assert seen["url"] == (
            "https://www.sec.gov/Archives/edgar/data/320193/000114036126025622/form4.xml"
        )
        # and the (mocked) transaction is collected, so the live path yields >0 once the URL is correct
        assert result == [
            {"accepted": _parse_acceptance("2026-06-15T12:00:00.000Z"), "code": "P", "shares": 1_000.0}
        ]

    def test_bare_primary_document_is_unchanged(self, monkeypatch):
        """A primaryDocument that is ALREADY a bare filename is passed through untouched (idempotent strip)."""
        seen: dict[str, str] = {}
        monkeypatch.setattr(
            sec_mod, "_get_json", lambda url, *, timeout: self._index_with_primary("form4.xml")
        )

        def _capture(doc_url, *, timeout):
            seen["url"] = doc_url
            return []

        monkeypatch.setattr(sec_mod, "_parse_ownership_doc", _capture)
        _fetch_form4_transactions(self._CIK, timeout=1.0)
        assert seen["url"].endswith("/form4.xml")
        assert "xslF345X06" not in seen["url"]


class TestParseOwnershipDocStructuredXml:
    """The parser must extract P/S transactions from REAL structured Form 4 XML, and extract NOTHING from the
    XSL HTML rendering (the document the broken live path used to fetch). Both are exercised offline by
    monkeypatching urlopen to serve in-memory bytes — no HTTP."""

    # A minimal but faithful Form 4 ownershipDocument with one open-market BUY (P) and one SALE (S).
    _RAW_FORM4_XML = b"""<?xml version="1.0"?>
    <ownershipDocument>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts><transactionShares><value>1500</value></transactionShares></transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
          <transactionAmounts><transactionShares><value>400</value></transactionShares></transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
          <transactionAmounts><transactionShares><value>9999</value></transactionShares></transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    # The XSL HTML RENDERING of the same filing: real-world shape — NO structured nonDerivativeTransaction nodes.
    _XSL_HTML = b"""<html><body><table><tr><td>Transaction Code</td><td>P</td></tr>
      <tr><td>Shares</td><td>1500</td></tr></table></body></html>"""

    def _serve(self, monkeypatch, payload: bytes):
        import cosmu.data.sources.sec_edgar as mod

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return payload

        monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, *a, **k: _Resp())

    def test_raw_xml_yields_open_market_ps_only(self, monkeypatch):
        from cosmu.data.sources.sec_edgar import _parse_ownership_doc

        self._serve(monkeypatch, self._RAW_FORM4_XML)
        pairs = _parse_ownership_doc("https://www.sec.gov/.../form4.xml", timeout=1.0)
        # the grant (A) is ignored; only the P buy and S sale survive
        assert pairs == [("P", 1500.0), ("S", 400.0)]

    def test_xsl_html_rendering_yields_zero_transactions(self, monkeypatch):
        """Proves WHY the bug was silent: the XSL HTML rendering parses to ZERO transactions — exactly what
        the live path produced before the prefix-strip fix."""
        from cosmu.data.sources.sec_edgar import _parse_ownership_doc

        self._serve(monkeypatch, self._XSL_HTML)
        assert _parse_ownership_doc("https://www.sec.gov/.../xslF345X06/form4.xml", timeout=1.0) == []


@pytest.mark.allow_network
@pytest.mark.skipif(
    os.environ.get("COSMU_LIVE_SEC_TEST") != "1",
    reason="live SEC EDGAR fetch; opt in with COSMU_LIVE_SEC_TEST=1 (kept off the default/CI run)",
)
class TestLiveSecEdgarIntegration:
    """OPT-IN live-path integration guard (real HTTP to SEC EDGAR). Skipped unless COSMU_LIVE_SEC_TEST=1 so the
    default/CI run stays offline (the session-wide socket guard is opted out of via allow_network here).

    Empirically verified 2026-06-21: AAPL (CIK 320193) accession 000114036126025622 is a Form 4 with
    open-market activity whose RAW form4.xml yields real <transactionCode>/<transactionShares> nodes, while
    the xsl-prefixed path yields none. This is the end-to-end regression guard the fix targets: with the
    prefix-strip in place the parser MUST extract >0 transactions for this known filing."""

    def test_parser_extracts_transactions_from_known_filing(self):
        from cosmu.data.sources.sec_edgar import _parse_ownership_doc

        raw_url = "https://www.sec.gov/Archives/edgar/data/320193/000114036126025622/form4.xml"
        pairs = _parse_ownership_doc(raw_url, timeout=20.0)
        assert len(pairs) > 0, (
            "LIVE REGRESSION: the raw structured form4.xml must yield >0 open-market P/S transactions; "
            "0 here means the live ownership-doc path is broken again"
        )
        for code, shares in pairs:
            assert code in ("P", "S")
            assert shares > 0.0

    def test_full_live_fetch_yields_transactions_for_aapl(self):
        """End-to-end: the live _fetch_form4_transactions for AAPL returns a real list (not the None failure
        sentinel) and — given AAPL's recent filing history — at least one parsed transaction."""
        cik = _CIK_BY_TICKER["AAPL"]
        txns = _fetch_form4_transactions(cik, timeout=20.0)
        assert txns is not None, "a successful live fetch must not return the None failure sentinel"
        assert any(t["code"] in ("P", "S") for t in txns), (
            "AAPL's recent Form 4 history should contain >0 open-market P/S transactions once the raw-XML "
            "path is used"
        )


class TestAmendmentsExcluded:
    """Form 4/A AMENDMENTS are deliberately excluded (documented PIT tradeoff). Verify a 4/A filing does
    not contribute transactions even when its ownership doc would parse to open-market P/S."""

    _CIK = _CIK_BY_TICKER["AAPL"]

    def test_form_4a_amendment_is_excluded(self, monkeypatch):
        monkeypatch.setattr(
            sec_mod,
            "_get_json",
            lambda url, *, timeout: {
                "filings": {
                    "recent": {
                        "form": ["4/A"],  # an AMENDMENT, not a plain Form 4
                        "accessionNumber": ["0000000000-24-000009"],
                        "acceptanceDateTime": ["2024-03-01T12:00:00.000Z"],
                        "primaryDocument": ["amend.xml"],
                    }
                }
            },
        )
        # If the 4/A were honored, this buy would surface — assert it is NOT fetched.
        monkeypatch.setattr(
            sec_mod, "_parse_ownership_doc", lambda doc_url, *, timeout: [("P", 5_000.0)]
        )
        result = _fetch_form4_transactions(self._CIK, timeout=1.0)
        # excluded → no transactions; a real empty list, NOT the None fetch-failure sentinel
        assert result == []
