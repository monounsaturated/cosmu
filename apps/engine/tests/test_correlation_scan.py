# The honest alt-data correlation engine: PIT information coefficients, FDR-controlled, propose-only.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config import feature_registry
from cosmu.config.feature_registry import FEATURE_REGISTRY, FeatureDefinition, feature_names
from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.data.providers.store import AltDataPoint, PgAltDataStore
from cosmu.knowledge.store import Store
from cosmu.master.correlation_ledger import CorrelationPersist, feature_history, latest_findings
from cosmu.research import correlation_scan
from cosmu.research.correlation_scan import (
    _forward_returns,
    _sweep_universe,
    new_run_id,
    run_correlation_scan,
    scan_universe,
    spearman_ic,
)


def test_spearman_ic_perfect_and_noise():
    xs = [float(i) for i in range(60)]
    ic, p, n = spearman_ic(xs, [x * 3 - 5 for x in xs])  # perfectly monotone
    assert ic == 1.0 and p == 0.0 and n == 60
    ic2, _, _ = spearman_ic(xs, list(reversed(xs)))       # perfectly anti-monotone
    assert ic2 == -1.0


def test_spearman_ic_fails_closed_on_thin_or_degenerate():
    assert spearman_ic([1, 2, 3], [1, 2, 3]) == (0.0, 1.0, 3)        # n<10 → fail-closed
    assert spearman_ic([1.0] * 20, list(range(20))) == (0.0, 1.0, 20)  # zero variance → fail-closed


def test_scan_universe_reads_the_registry_not_a_hardcoded_list():
    # the scan universe IS the enabled feature registry — single source of truth, no frozen list to drift.
    universe = {name for name, _ in scan_universe()}
    assert universe == feature_names()
    # every pair carries the feature's registered source (used downstream for store routing).
    by_name = {f.name: f.source for f in FEATURE_REGISTRY if f.enabled}
    assert all(by_name[name] == source for name, source in scan_universe())


def test_scan_universe_picks_up_the_ten_new_altdata_features():
    # the 10 newly-registered alt-data sources must all be in the scan's universe (× asset × horizon downstream).
    # NOTE: gtrends_search_interest is QUARANTINED (revision_safety hazard: Google Trends rescales history
    # → look-ahead contamination). It is excluded from feature_names() / scan_universe() until profile-source
    # validates revision_safety = PASS. All other 9 new alt-data features remain enabled and scannable.
    universe = {name for name, _ in scan_universe()}
    new_altdata = {
        "weather_hub_stress", "astro_lunar_phase", "wiki_pageviews", "usgs_earthquake_count",
        "rss_news_count", "fear_greed", "opensky_daily_flights",
        "reddit_post_volume", "cryptopanic_bullish_votes",
    }
    assert new_altdata <= universe, f"new alt-data not scanned: {new_altdata - universe}"
    # gtrends is quarantined → must NOT be in the scan universe
    assert "gtrends_search_interest" not in universe, (
        "gtrends_search_interest is quarantined (revision_safety hazard) and must not be scanned"
    )


def test_scan_universe_excludes_disabled_and_supports_subset_filter():
    # disabled features (e.g. the honesty-fix exchange_netflow) are NEVER in the scan universe.
    assert "exchange_netflow" not in {name for name, _ in scan_universe()}
    # an explicit subset restricts (still gated on enabled) — for targeted re-scans.
    assert {name for name, _ in scan_universe(["fear_greed", "wiki_pageviews"])} == {"fear_greed", "wiki_pageviews"}
    assert scan_universe(["exchange_netflow"]) == []  # disabled → dropped even when explicitly requested


def test_a_newly_registered_feature_is_picked_up_by_the_scan_universe(monkeypatch):
    # PROVES the universe READS the registry: register a brand-new enabled feature and it appears in the scan
    # universe with no edit to correlation_scan — the moment a source is registered it is scanned.
    novel = FeatureDefinition(
        name="brand_new_altdata_xyz", source="some_new_source", tier="tier1",
        asset_classes=["crypto"], asof_semantics="fetch time (no look-ahead)",
        prior="A freshly-wired test source — must earn its place OOS.",
    )
    patched = (*FEATURE_REGISTRY, novel)
    monkeypatch.setattr(feature_registry, "FEATURE_REGISTRY", patched)
    monkeypatch.setattr(correlation_scan, "FEATURE_REGISTRY", patched)
    universe = {name for name, _ in scan_universe()}
    assert "brand_new_altdata_xyz" in universe
    assert ("brand_new_altdata_xyz", "some_new_source") in scan_universe()


def test_forward_returns_are_strictly_future_no_lookahead():
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    bars = [Bar(ts=t0 + timedelta(days=i), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
                close=Decimal(str(100 + i)), volume=Decimal("0")) for i in range(10)]
    fwd = _forward_returns(bars, horizon=2)
    # the forward return at bar i uses close[i+2]/close[i] — strictly future; last `horizon` bars have no entry.
    assert fwd[bars[0].ts.isoformat()] == (102 / 100) - 1.0
    assert bars[-1].ts.isoformat() not in fwd and bars[-2].ts.isoformat() not in fwd
    assert len(fwd) == 8


# ── persistence: the scan TRACKS its findings to the correlation ledger (opt-in, offline-safe) ────────────────

def _store(tmp_path, name="cscan") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _fixture_market_and_store(tmp_path):
    """A tiny DETERMINISTIC offline fixture: 200 daily bars whose forward returns are a clean (deterministic)
    function of a seeded market-wide `fear_greed` series, so the scan finds a strong, FDR-surviving IC with NO
    network, NO LLM. fear_greed routes to provider 'alternative.me' / key 'MARKET' in the store-backed provider."""
    store = _store(tmp_path)
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    points: list[AltDataPoint] = []
    px = 100.0
    for i in range(200):
        ts = t0 + timedelta(days=i)
        val = float((i * 37) % 101)  # pseudo-random but fully deterministic feature value
        points.append(AltDataPoint(ts=ts, available_at=ts, value=val))
        px *= 1.0 + (val - 50.0) / 5000.0  # next return is a deterministic function of the feature → strong IC
        bars.append(Bar(ts=ts, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
                        close=Decimal(str(round(px, 6))), volume=Decimal("0")))
    PgAltDataStore(store).append("alternative.me", "MARKET", "fear_greed", points)
    return {"BTCUSDT": bars}, store


def test_scan_persists_every_finding_to_the_ledger_and_is_re_readable(tmp_path):
    # SCAN A TINY FIXTURE → assert findings persisted + re-readable (the core "track everything, never lie" path).
    market, store = _fixture_market_and_store(tmp_path)
    persist = CorrelationPersist(store=store, run_id="scan-run-1", data_source="fixture")
    rep = run_correlation_scan(store, market, horizons=(1, 5), features=["fear_greed"], persist=persist)

    assert rep.n_tests == 2 and rep.n_survived_fdr >= 1  # a real, deterministic, FDR-surviving correlation

    # every ranked finding landed in correlation_findings, re-readable under the stamped run_id + fixture tag.
    rows = latest_findings(store)
    assert len(rows) == rep.n_tests
    assert all(r["run_id"] == "scan-run-1" and r["data_source"] == "fixture" for r in rows)
    assert {r["feature"] for r in rows} == {"fear_greed"}
    assert {int(r["horizon"]) for r in rows} == {1, 5}

    # the persisted IC matches the report (no fabrication, no rounding drift) — and is queryable as a tracked series.
    by_h = {int(r.horizon): r.ic for r in rep.results}
    hist1 = feature_history(store, "fear_greed", asset="BTCUSDT", horizon=1)
    assert len(hist1) == 1 and abs(float(hist1[0]["ic"]) - by_h[1]) < 1e-9


def test_scan_default_path_is_propose_only_and_persists_nothing(tmp_path):
    # No CorrelationPersist passed → the scan never writes a row (persist is opt-in, so tests stay clean).
    market, store = _fixture_market_and_store(tmp_path)
    rep = run_correlation_scan(store, market, horizons=(1, 5), features=["fear_greed"])
    assert rep.n_tests == 2  # the scan still runs + ranks
    assert store.rows("SELECT COUNT(*) AS c FROM correlation_findings")[0]["c"] == 0  # but persisted nothing


def test_scan_is_deterministic_for_a_fixed_fixture(tmp_path):
    # The same fixture scanned twice yields identical ICs — the "machine that never lies" must be reproducible.
    market_a, _ = _fixture_market_and_store(tmp_path)
    market_b, _ = _fixture_market_and_store(tmp_path)
    a = run_correlation_scan(_store(tmp_path, "a"), market_a, horizons=(1, 5), features=["fear_greed"])
    b = run_correlation_scan(_store(tmp_path, "b"), market_b, horizons=(1, 5), features=["fear_greed"])
    assert [(r.horizon, r.ic, r.n_obs, r.p_value) for r in a.results] == \
           [(r.horizon, r.ic, r.n_obs, r.p_value) for r in b.results]


def test_persist_failure_never_breaks_the_scan(tmp_path):
    # Best-effort + offline-safe: a broken PERSIST store must NOT crash the scan — the report is returned unchanged.
    # The scan reads its alt-data from the fixture store; only the (separate) persist store is broken.
    market, scan_store = _fixture_market_and_store(tmp_path)

    class _Broken(Store):
        def batch(self):  # type: ignore[override]
            raise RuntimeError("DB down")

    broken = _Broken(Settings(database_url=f"sqlite:///{tmp_path}/broken.sqlite3"))
    persist = CorrelationPersist(store=broken, run_id="x", data_source="fixture")
    rep = run_correlation_scan(scan_store, market, horizons=(1, 5), features=["fear_greed"], persist=persist)
    assert rep.n_tests == 2  # the scan completed + returned its ranked report despite the persist failure


def test_sweep_universe_is_config_driven_with_an_offline_fallback(monkeypatch):
    # The sweep visits the CONFIGURED asset universe (matrix_sweep_assets — one place to widen the grid).
    uni = _sweep_universe()
    assert isinstance(uni, list) and uni and all(isinstance(s, str) for s in uni)
    # offline (settings unavailable) → built-in majors fallback, never an empty/fabricated universe.
    import cosmu.research.correlation_scan as cs

    def _boom():
        raise RuntimeError("no settings offline")

    monkeypatch.setattr("cosmu.config.settings.get_settings", _boom)
    assert _sweep_universe() == list(cs._DEFAULT_UNIVERSE)


def test_new_run_id_is_unique_and_prefixed():
    a, b = new_run_id("sweep"), new_run_id("sweep")
    assert a.startswith("sweep-") and b.startswith("sweep-") and a != b  # each run is its own tracked row group
