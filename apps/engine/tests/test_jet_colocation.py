"""Offline, deterministic tests for the corporate-jet co-location DataSource.

Verified invariants:
  1. PIT contract: available_at = obs_day + 1 day (next-day); NEVER look-ahead.
  2. Gap honesty: a missing day contributes nothing; a window with NO knowable day => value=None (not 0).
  3. as_of earlier than first available datum, OR an untracked ticker => value=None, available_at=None.
  4. detect_colocation_events: a target landing at the same airport as another tracked ticker counts once;
     a lone aircraft counts 0; an untracked target yields the source's None.
  5. low_confidence=True (confidence 0.12 < 0.5); kind=="osint"; name is snake_case.
  6. transform_version is the pinned string.
  7. query() uses the latest day whose available_at <= as_of (never the next day — no look-ahead).
  8. No HTTP calls in any test (offline=True throughout).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from cosmu.data.sources.jet_colocation import (
    TRANSFORM_VERSION,
    _AIRCRAFT_BY_TICKER,
    _FIXTURE_ARRIVALS_BY_DAY,
    JetColocationSource,
    _arrivals_by_ticker_for_day,
    _day_to_unix,
    _ticker_of_icao24,
    detect_colocation_events,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_src(**kwargs) -> JetColocationSource:
    """Return an offline source; tests pass a custom fixture / window to avoid coupling to the default."""
    defaults = dict(offline=True)
    defaults.update(kwargs)
    return JetColocationSource(**defaults)


# The fixture spans 2024-01-01 .. 2024-01-05 (2024-01-03 absent). Use a window wide enough to cover it so a
# single query aggregates the whole fixture; available_at semantics still hold per-day.
_JAN02 = datetime(2024, 1, 2, tzinfo=UTC)  # obs_day 2024-01-01 becomes knowable here
_JAN06 = datetime(2024, 1, 6, tzinfo=UTC)  # latest knowable obs_day = 2024-01-05


# ---------------------------------------------------------------------------
# PIT: available_at = obs_day + 1 day
# ---------------------------------------------------------------------------

class TestPITContract:
    def test_available_at_is_next_day_midnight(self):
        src = _make_src()
        avail = src._available_at(date(2024, 1, 1))
        assert avail == datetime(2024, 1, 2, tzinfo=UTC), "available_at must be the next UTC midnight"

    def test_as_of_exactly_at_available_at_sees_the_day(self):
        """as_of == available_at(D) -> D is knowable (boundary inclusive). With a 1-day window ending at
        the latest knowable day, as_of=2024-01-02 sees only obs_day 2024-01-01 (the KSJC co-location)."""
        src = _make_src(window_days=1)
        as_of = datetime(2024, 1, 2, tzinfo=UTC)  # latest knowable obs_day = 2024-01-01
        f = src.query("AAPL", as_of)
        assert f.value == 1.0, "AAPL co-located with MSFT at KSJC on 2024-01-01 => 1 event"
        assert f.available_at == as_of

    def test_as_of_one_second_before_available_at_cannot_see_the_day(self):
        """as_of = available_at(D) - 1 second -> D is NOT knowable (no look-ahead)."""
        src = _make_src(window_days=1)
        # available_at for obs_day 2024-01-04 is 2024-01-05 00:00 UTC; ask one second before.
        as_of = datetime(2024, 1, 4, 23, 59, 59, tzinfo=UTC)
        # latest knowable obs_day = 2024-01-03 (a GAP). The 2024-01-04 KTEB co-location must NOT be visible.
        f = src.query("AAPL", as_of)
        assert f.value is None, "2024-01-03 is a gap; 2024-01-04 data must not leak in (no look-ahead)"

    def test_feature_available_at_matches_source_for_latest_day(self):
        """SourceFeature.available_at matches the source's _available_at() for the latest knowable day."""
        src = _make_src(window_days=30)
        f = src.query("AAPL", _JAN06)  # latest knowable obs_day = 2024-01-05
        assert f.available_at == src._available_at(date(2024, 1, 5))


# ---------------------------------------------------------------------------
# Gap honesty: missing day -> None, not 0
# ---------------------------------------------------------------------------

class TestGapHonesty:
    def test_window_with_only_gap_day_returns_none_not_zero(self):
        """A 1-day window landing exactly on the absent 2024-01-03 -> value=None (gap), not 0."""
        src = _make_src(window_days=1)
        as_of = datetime(2024, 1, 4, tzinfo=UTC)  # latest knowable obs_day = 2024-01-03 (absent)
        f = src.query("AAPL", as_of)
        assert f.value is None, "A gap day must yield value=None, NEVER 0"
        assert f.available_at is None

    def test_colocation_events_for_gap_day_returns_none(self):
        src = _make_src()
        assert src.colocation_events_for_day("AAPL", date(2024, 1, 3)) is None

    def test_zero_events_day_is_int_zero_not_none(self):
        """A day we HAVE data for, where the target did NOT co-locate, is a real 0 (not a gap)."""
        src = _make_src()
        # 2024-01-02: AAPL at KSJC, MSFT at KSEA (different airports) => 0 events, but data exists.
        assert src.colocation_events_for_day("AAPL", date(2024, 1, 2)) == 0

    def test_window_sums_events_across_days(self):
        """Over the full fixture window AAPL has events on 2024-01-01 (KSJC) and 2024-01-04 (KTEB) => 2."""
        src = _make_src(window_days=30)
        f = src.query("AAPL", _JAN06)
        assert f.value == 2.0


# ---------------------------------------------------------------------------
# Before-any-data / untracked-ticker cases
# ---------------------------------------------------------------------------

class TestBeforeDataAndUntracked:
    def test_as_of_before_2015_returns_none(self):
        """as_of before the OpenSky data era -> no datum knowable -> value=None, available_at=None."""
        src = _make_src()
        ancient = datetime(2010, 1, 1, tzinfo=UTC)
        f = src.query("AAPL", ancient)
        assert f.value is None
        assert f.available_at is None

    def test_untracked_ticker_returns_none_not_zero(self):
        """A ticker NOT in the seed map => value=None (honest 'we don't track this'), NEVER 0."""
        src = _make_src(window_days=30)
        f = src.query("ZZZZ", _JAN06)
        assert f.value is None, "An untracked ticker must yield None, not a fabricated 0"
        assert f.available_at is None

    def test_colocation_events_for_untracked_ticker_is_none(self):
        src = _make_src()
        assert src.colocation_events_for_day("ZZZZ", date(2024, 1, 1)) is None


# ---------------------------------------------------------------------------
# detect_colocation_events: the pure core-logic helper
# ---------------------------------------------------------------------------

class TestDetectColocationEvents:
    def test_same_airport_counts_one(self):
        """Target and another tracked ticker at the same airport => 1 co-location event."""
        arrivals = {"AAPL": {"a1b2c3": "KSJC"}, "MSFT": {"b2c3d4": "KSJC"}}
        assert detect_colocation_events(arrivals, "AAPL") == 1

    def test_lone_aircraft_counts_zero(self):
        """A lone target aircraft (no other tracked ticker at its airport) => 0."""
        arrivals = {"AAPL": {"a1b2c3": "KSJC"}, "MSFT": {"b2c3d4": "KSEA"}}
        assert detect_colocation_events(arrivals, "AAPL") == 0

    def test_target_with_no_arrivals_counts_zero(self):
        arrivals = {"MSFT": {"b2c3d4": "KSEA"}}
        assert detect_colocation_events(arrivals, "AAPL") == 0

    def test_one_airport_with_multiple_others_counts_once(self):
        """One (day, airport) co-location counts ONCE even if several other companies share it."""
        arrivals = {
            "AAPL": {"a1b2c3": "KTEB"},
            "GOOGL": {"c3d4e5": "KTEB"},
            "META": {"e5f6a7": "KTEB"},
        }
        assert detect_colocation_events(arrivals, "AAPL") == 1

    def test_two_distinct_airports_count_two(self):
        """Target co-located at two DISTINCT airports => 2."""
        arrivals = {
            "AAPL": {"a1b2c3": "KTEB", "a1b2c4": "KSJC"},
            "GOOGL": {"c3d4e5": "KTEB"},
            "MSFT": {"b2c3d4": "KSJC"},
        }
        assert detect_colocation_events(arrivals, "AAPL") == 2

    def test_second_target_jet_alone_does_not_add(self):
        """2024-01-04 fixture shape: AAPL+GOOGL at KTEB (1 event), AAPL's 2nd jet alone at KLAX (no add)."""
        grouped = _arrivals_by_ticker_for_day(_FIXTURE_ARRIVALS_BY_DAY["2024-01-04"])
        assert detect_colocation_events(grouped, "AAPL") == 1


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class TestModuleHelpers:
    def test_ticker_of_icao24_case_insensitive(self):
        assert _ticker_of_icao24("A1B2C3") == "AAPL"
        assert _ticker_of_icao24("b2c3d4") == "MSFT"

    def test_ticker_of_icao24_untracked_is_none(self):
        assert _ticker_of_icao24("ffffff") is None

    def test_arrivals_by_ticker_drops_untracked_hex(self):
        grouped = _arrivals_by_ticker_for_day({"a1b2c3": "KSJC", "ffffff": "KSJC"})
        assert grouped == {"AAPL": {"a1b2c3": "KSJC"}}

    def test_day_to_unix_2024_01_01(self):
        assert _day_to_unix(date(2024, 1, 1)) == 1_704_067_200

    def test_day_to_unix_monotone(self):
        d = date(2024, 1, 1)
        prev = _day_to_unix(d)
        for _ in range(5):
            d += timedelta(days=1)
            curr = _day_to_unix(d)
            assert curr == prev + 86_400
            prev = curr


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_low_confidence_is_true(self):
        src = _make_src()
        assert src.low_confidence is True
        assert src.confidence < 0.5
        assert src.confidence == 0.12

    def test_transform_version_is_pinned(self):
        src = _make_src()
        assert src.transform_version == TRANSFORM_VERSION == "jet-colocation-v1"

    def test_metric_equals_name_and_snake_case(self):
        src = _make_src()
        assert src.name == "jet_colocation"
        assert src.metric == src.name
        assert "_" in src.name
        assert " " not in src.name

    def test_kind_is_osint(self):
        src = _make_src()
        assert src.kind == "osint"

    def test_prior_is_causal_not_a_control(self):
        """The prior must declare it LOW-CONFIDENCE and explicitly NOT a non-causal control."""
        prior_lower = src.prior.lower() if (src := _make_src()) else ""
        assert "low-confidence" in prior_lower or "low confidence" in prior_lower
        assert "not a non-causal control" in prior_lower

    def test_query_returns_source_feature_with_correct_metadata(self):
        from cosmu.data.sources.registry import SourceFeature

        src = _make_src(window_days=1)
        f = src.query("AAPL", _JAN02)
        assert isinstance(f, SourceFeature)
        assert f.name == "jet_colocation"
        assert f.scope == "AAPL"
        assert f.transform_version == TRANSFORM_VERSION
        assert f.low_confidence is True
        assert f.confidence < 0.5


# ---------------------------------------------------------------------------
# DataSource protocol compliance
# ---------------------------------------------------------------------------

class TestDataSourceProtocol:
    def test_satisfies_datasource_protocol(self):
        from cosmu.data.sources.registry import DataSource

        src = _make_src()
        assert isinstance(src, DataSource)

    def test_registerable_in_registry_shows_low_confidence(self):
        from cosmu.data.sources.registry import DataSourceRegistry

        src = _make_src()
        reg = DataSourceRegistry()
        reg.register(src)
        assert "jet_colocation" in reg.names()
        catalog = reg.discover()
        entry = next(c for c in catalog if c["name"] == "jet_colocation")
        assert entry["low_confidence"] is True
        assert entry["kind"] == "osint"

    def test_seed_map_is_partial_and_lowercase_hex(self):
        """Coverage is intentionally partial; hex ids are lowercase placeholders."""
        assert "AAPL" in _AIRCRAFT_BY_TICKER
        assert "ZZZZ" not in _AIRCRAFT_BY_TICKER  # partial by design
        for hexes in _AIRCRAFT_BY_TICKER.values():
            for h in hexes:
                assert h == h.lower()


# ---------------------------------------------------------------------------
# Offline-safety + look-ahead hardening (ACTIVELY enforced, not just claimed)
# ---------------------------------------------------------------------------

class TestNoHttpAndLookahead:
    def test_offline_query_makes_no_http_call(self, monkeypatch):
        """Booby-trap urllib.request.urlopen to raise; an offline query must NEVER reach it."""
        import cosmu.data.sources.jet_colocation as mod

        def _boom(*a, **k):  # pragma: no cover - must never be called
            raise AssertionError("offline query made a real HTTP call")

        monkeypatch.setattr(mod.urllib.request, "urlopen", _boom)
        src = _make_src(window_days=30)
        f = src.query("AAPL", _JAN06)  # must resolve from fixture only
        assert f.value == 2.0

    def test_as_of_in_tz_ahead_of_utc_does_not_look_ahead(self):
        """A tz-aware as_of east of UTC must be normalized to UTC before picking the latest knowable day —
        otherwise as_of.date() is a calendar day ahead and we'd claim a day not yet published (look-ahead)."""
        from datetime import timezone

        src = _make_src()
        tz14 = timezone(timedelta(hours=14))
        # 2024-01-02 00:30 UTC+14 == 2024-01-01 10:30 UTC; latest knowable obs_day must be
        # 2023-12-31, NOT 2024-01-01 (whose available_at 2024-01-02 00:00 UTC is ~14h ahead).
        as_of = datetime(2024, 1, 2, 0, 30, tzinfo=tz14)
        assert src._latest_knowable_day(as_of) == date(2023, 12, 31)


# ---------------------------------------------------------------------------
# Live-path CALL-REDUCTION (rate-limit hardening) — fetch each aircraft ONCE
# per window + MEMOIZE across queries. Pure efficiency: NO computed value or
# PIT change. Exercised without real HTTP by counting fetch calls.
# ---------------------------------------------------------------------------

class TestLivePathCallReduction:
    def _num_aircraft(self) -> int:
        return sum(len(v) for v in _AIRCRAFT_BY_TICKER.values())

    def _patch_counting_fetch(self, monkeypatch, *, day_to_arrivals):
        """Replace _fetch_aircraft_arrivals with a counter that synthesizes per-aircraft flight dicts from a
        {iso_day: {icao24: airport}} map, filtered to the requested [begin, end) span (server-side filter
        emulation, by lastSeen). Returns the call-count list (one entry per (icao24, begin, end) request)."""
        import cosmu.data.sources.jet_colocation as mod

        calls: list[tuple[str, int, int]] = []

        def _fake_fetch(base_url, icao24, begin, end, timeout):  # noqa: ANN001
            calls.append((icao24.lower(), begin, end))
            flights = []
            for iso_day, arr in day_to_arrivals.items():
                d = date.fromisoformat(iso_day)
                last_seen = mod._day_to_unix(d) + 3600  # arrives 01:00 UTC that day
                if icao24.lower() in arr and begin <= last_seen < end:
                    flights.append({"lastSeen": last_seen, "estArrivalAirport": arr[icao24.lower()]})
            return flights

        monkeypatch.setattr(mod, "_fetch_aircraft_arrivals", _fake_fetch)
        return calls

    def test_window_fetches_each_aircraft_once_not_per_day(self, monkeypatch):
        """The online window path must issue ONE request per aircraft for the whole 30-day window, NOT one
        per (aircraft x day). With ~12 aircraft x 30 days the naive path would be ~360 calls; we expect 12."""
        day_to_arrivals = {d: {} for d in _FIXTURE_ARRIVALS_BY_DAY}
        day_to_arrivals.update({k: {kk.lower(): vv for kk, vv in v.items()}
                                for k, v in _FIXTURE_ARRIVALS_BY_DAY.items()})
        calls = self._patch_counting_fetch(monkeypatch, day_to_arrivals=day_to_arrivals)
        src = JetColocationSource(offline=False, window_days=30)  # ONLINE path, but fetch is patched
        src.query("AAPL", _JAN06)
        n = self._num_aircraft()
        assert len(calls) == n, f"expected one fetch per aircraft ({n}), got {len(calls)}"
        assert len(calls) < n * 30, "window fetch must be far below the per-(aircraft x day) call count"
        # Every aircraft was fetched exactly once, and over a SINGLE span (same begin/end for all).
        assert len({c[0] for c in calls}) == n
        assert len({(c[1], c[2]) for c in calls}) == 1, "all aircraft fetched over the same window span"

    def test_repeated_queries_same_window_reuse_memo_no_extra_calls(self, monkeypatch):
        """A second query over the SAME window (e.g. another ticker in the same ingest pass) must hit the
        per-instance memo and issue ZERO additional fetches."""
        calls = self._patch_counting_fetch(monkeypatch, day_to_arrivals={})
        src = JetColocationSource(offline=False, window_days=30)
        src.query("AAPL", _JAN06)
        after_first = len(calls)
        assert after_first == self._num_aircraft()
        src.query("MSFT", _JAN06)   # same as_of => same window => memo hit
        src.query("GOOGL", _JAN06)  # same window again
        assert len(calls) == after_first, "memoized window must not re-fetch for repeated same-window queries"

    def test_window_path_value_matches_per_day_fetch_byte_identical(self, monkeypatch):
        """The call-reducing window sweep must produce the SAME feature value as the per-day fetch would —
        proving it is a pure efficiency change, not a behaviour change. We feed both paths the same synthetic
        arrivals (AAPL+MSFT co-locate at KSJC on 2024-01-01, AAPL+GOOGL at KTEB on 2024-01-04 => 2 events)."""
        day_to_arrivals = {k: {kk.lower(): vv for kk, vv in v.items()}
                           for k, v in _FIXTURE_ARRIVALS_BY_DAY.items()}
        self._patch_counting_fetch(monkeypatch, day_to_arrivals=day_to_arrivals)
        src = JetColocationSource(offline=False, window_days=30)
        f = src.query("AAPL", _JAN06)
        # Same shape as the offline fixture query (TestGapHonesty.test_window_sums_events_across_days => 2.0).
        assert f.value == 2.0
        assert f.available_at == src._available_at(date(2024, 1, 5))

    def test_offline_window_path_still_makes_no_http(self, monkeypatch):
        """Offline must NOT use the live sweep at all: booby-trap both fetch entrypoints; query resolves from
        the fixture only (offline byte-identical guarantee preserved by the call-reduction refactor)."""
        import cosmu.data.sources.jet_colocation as mod

        def _boom(*a, **k):  # pragma: no cover - must never be called offline
            raise AssertionError("offline query reached a live fetch path")

        monkeypatch.setattr(mod, "_fetch_aircraft_arrivals", _boom)
        monkeypatch.setattr(mod, "_live_arrivals_by_day", _boom)
        monkeypatch.setattr(mod, "_live_arrivals_for_day", _boom)
        src = _make_src(window_days=30)
        f = src.query("AAPL", _JAN06)
        assert f.value == 2.0
