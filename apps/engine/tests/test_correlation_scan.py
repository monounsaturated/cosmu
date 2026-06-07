# The honest alt-data correlation engine: PIT information coefficients, FDR-controlled, propose-only.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config import feature_registry
from cosmu.config.feature_registry import FEATURE_REGISTRY, FeatureDefinition, feature_names
from cosmu.data.market import Bar
from cosmu.research import correlation_scan
from cosmu.research.correlation_scan import _forward_returns, scan_universe, spearman_ic


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
    universe = {name for name, _ in scan_universe()}
    new_altdata = {
        "weather_hub_stress", "astro_lunar_phase", "wiki_pageviews", "usgs_earthquake_count",
        "rss_news_count", "gtrends_search_interest", "fear_greed", "opensky_daily_flights",
        "reddit_post_volume", "cryptopanic_bullish_votes",
    }
    assert new_altdata <= universe, f"new alt-data not scanned: {new_altdata - universe}"


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
