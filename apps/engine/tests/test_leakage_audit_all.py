"""The standing leakage audit over ALL wired alt-features (cosmu.research.leakage_audit_all).

The leakage tripwire (audit_feature) was only ever proven on SYNTHETIC controls; the ~36 wired alt-features were
hand-stamped PIT-honest by CONVENTION, never behaviourally audited. This module runs the tripwire on every
enabled, store-routed alt-feature's REAL point-in-time series. These tests prove the audit harness:

  - runs over a tiny FIXTURE set (injected provider + bars loader — no DB, no network) without crashing;
  - FLAGS a synthetic LEAKY feature (each value stamped one bar early — a baked-in look-ahead) as FAIL, and the
    run exits non-zero;
  - PASSES a synthetic CLEAN feature (real forward-predictive edge, strictly PIT-stamped);
  - SKIPS a feature with no store data (an honest skip, never a crash / fabricated series);
  - is deterministic + idempotent for a fixed (provider, bars, seed).

Hermetic + deterministic (string-seeded shuffle null, injected fixtures, no Binance — the M2 is geo-blocked).
"""

from __future__ import annotations

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.leakage_audit_all import (
    FAIL,
    PASS,
    SKIP,
    WARN,
    FeatureAuditResult,
    run_audit_all,
    wired_store_features,
)
from cosmu.research.leakage_tripwire import _synthetic_market

# Build the canonical synthetic market ONCE — a smooth AR(1) feature whose value at bar t drives the return
# t->t+1 (the tripwire's own offline market). feature_vals[t] is the honest, on-bar-known value.
_FEATURE_VALS, _BARS = _synthetic_market(n=400, seed=7)


def _clean_points() -> list[AltDataPoint]:
    """A strictly PIT-stamped clean feature: bar t carries feature[t], available_at == bar t (no look-ahead)."""
    return [AltDataPoint(ts=b.ts, available_at=b.ts, value=_FEATURE_VALS[t]) for t, b in enumerate(_BARS)]


def _leaked_points() -> list[AltDataPoint]:
    """A baked-in 1-bar look-ahead: bar t carries TOMORROW's value feature[t+1], back-dated to bar t so the join
    looks clean. AR(1)-smooth, so reading it a bar early stays predictive but lagging -1 recovers a STRONGER
    alignment — the forward-shift leak fingerprint."""
    return [
        AltDataPoint(ts=_BARS[t].ts, available_at=_BARS[t].ts, value=_FEATURE_VALS[t + 1])
        for t in range(len(_BARS) - 1)
    ]


class _FixtureProvider:
    """An injected fetch seam (the StoreBackedAltProvider.fetch_series contract) backed by an in-memory map of
    (symbol, metric) -> points. A miss returns [] — an honest skip, exactly like an unrouted store series."""

    def __init__(self, series: dict[tuple[str, str], list[AltDataPoint]]) -> None:
        self._series = series

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        return list(self._series.get((symbol, metric), []))[-limit:]


def _bars_loader(_symbol: str) -> list[Bar]:
    """Every fixture asset shares the synthetic market's bars (the synthetic feature was built against them)."""
    return _BARS


# =========================================================================== the audit end to end (fixtures)


def test_audit_runs_over_fixtures_without_crashing_and_classifies():
    """A clean + a leaked + a no-data feature, scored against a tiny fixture set with an INJECTED provider +
    bars loader (no DB, no network): the run completes, returns one result per feature, and never raises."""
    provider = _FixtureProvider({
        ("BTCUSDT", "clean_feat"): _clean_points(),
        ("BTCUSDT", "leaky_feat"): _leaked_points(),
        # "missing_feat" deliberately has NO entry → an honest SKIP.
    })
    features = [("clean_feat", "fixture"), ("leaky_feat", "fixture"), ("missing_feat", "fixture")]
    report = run_audit_all(
        provider, _bars_loader, assets=["BTCUSDT"], features=features, shuffle_trials=100, seed=7,
    )
    assert len(report.results) == 3
    by_name = {r.feature: r for r in report.results}
    assert set(by_name) == {"clean_feat", "leaky_feat", "missing_feat"}
    for r in report.results:
        assert isinstance(r, FeatureAuditResult)
        assert r.verdict in {PASS, WARN, FAIL, SKIP}


def test_clean_feature_passes():
    """A known-CLEAN, on-bar-honest feature with a real forward-predictive edge must PASS the audit — strictly
    as-of join, no baked-in peek, IC survives the shuffle."""
    provider = _FixtureProvider({("BTCUSDT", "clean_feat"): _clean_points()})
    report = run_audit_all(
        provider, _bars_loader, assets=["BTCUSDT"], features=[("clean_feat", "fixture")],
        shuffle_trials=100, seed=7,
    )
    res = report.results[0]
    assert res.verdict == PASS, f"clean feature mis-classified {res.verdict}: {res.reason}"
    assert res.report is not None and res.report.passed
    assert not res.is_leak
    assert report.leaks == []
    assert report.counts()[PASS] == 1


def test_leaky_feature_is_flagged_as_fail_and_fails_the_run():
    """A deliberately LEAKED feature (each value stamped ONE BAR EARLY — a hidden 1-bar look-ahead) must be
    classified FAIL on the forward-shift sanity, and the report must surface it as a real leak (non-zero run)."""
    provider = _FixtureProvider({("BTCUSDT", "leaky_feat"): _leaked_points()})
    report = run_audit_all(
        provider, _bars_loader, assets=["BTCUSDT"], features=[("leaky_feat", "fixture")],
        shuffle_trials=100, seed=7,
    )
    res = report.results[0]
    assert res.verdict == FAIL, f"baked-in look-ahead slipped through: {res.verdict} ({res.reason})"
    assert res.is_leak
    assert len(report.leaks) == 1
    assert report.leaks[0].feature == "leaky_feat"
    assert res.report is not None
    # The leak fingerprint: lagging -1 bar recovers a STRONGER alignment, and the join itself looked clean.
    assert res.report.forward_shift.backward_improves
    assert res.report.available_at.passed
    assert "PEEK" in res.reason or "LOOK-AHEAD" in res.reason


def test_missing_data_is_an_honest_skip():
    """A feature with no store series is an honest SKIP (never a crash / fabricated series / FAIL)."""
    provider = _FixtureProvider({})  # nothing routed
    report = run_audit_all(
        provider, _bars_loader, assets=["BTCUSDT"], features=[("missing_feat", "fixture")],
        shuffle_trials=50, seed=7,
    )
    res = report.results[0]
    assert res.verdict == SKIP
    assert res.n_obs == 0
    assert report.leaks == []


def test_provider_blow_up_is_a_skip_not_a_crash():
    """A provider that RAISES on fetch must not crash the run — the feature is an honest SKIP."""

    class _Boom:
        def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
            raise RuntimeError("simulated store outage")

    report = run_audit_all(
        _Boom(), _bars_loader, assets=["BTCUSDT"], features=[("x", "fixture")], shuffle_trials=20, seed=7,
    )
    assert report.results[0].verdict == SKIP


def test_noise_feature_warns_not_fails():
    """A noise feature (independent of returns, strictly PIT-stamped) has NO look-ahead, so it must WARN (IC
    inside the shuffled band — an artefact smell, not a leak), never FAIL the run."""
    import random

    rng = random.Random("audit-noise")
    noise = [AltDataPoint(ts=b.ts, available_at=b.ts, value=rng.gauss(0, 1)) for b in _BARS]
    provider = _FixtureProvider({("BTCUSDT", "noise_feat"): noise})
    report = run_audit_all(
        provider, _bars_loader, assets=["BTCUSDT"], features=[("noise_feat", "fixture")],
        shuffle_trials=100, seed=7,
    )
    res = report.results[0]
    assert res.verdict == WARN, f"noise feature should WARN, got {res.verdict}: {res.reason}"
    assert not res.is_leak
    assert report.leaks == []


# =========================================================================== determinism + the wired universe


def test_audit_is_deterministic():
    """Same inputs + seed → identical verdicts (a standing audit must be reproducible to be trustworthy)."""
    provider = _FixtureProvider({
        ("BTCUSDT", "clean_feat"): _clean_points(),
        ("BTCUSDT", "leaky_feat"): _leaked_points(),
    })
    features = [("clean_feat", "fixture"), ("leaky_feat", "fixture")]
    a = run_audit_all(provider, _bars_loader, assets=["BTCUSDT"], features=features, shuffle_trials=80, seed=3)
    b = run_audit_all(provider, _bars_loader, assets=["BTCUSDT"], features=features, shuffle_trials=80, seed=3)
    assert [(r.feature, r.verdict, r.real_ic) for r in a.results] == [
        (r.feature, r.verdict, r.real_ic) for r in b.results
    ]


def test_wired_universe_is_the_registry_store_features():
    """The audit universe is exactly the enabled, store-routed, non-price features — read from the registry so a
    newly-wired source is audited automatically, and a disabled / bar-computed feature is excluded."""
    from cosmu.config.feature_registry import feature_names
    from cosmu.data.backtest import PRICE_FEATURES
    from cosmu.data.providers.store import _STORE_PROVIDER_OF

    feats = wired_store_features()
    names = {n for n, _ in feats}
    assert names  # non-empty — there ARE wired alt-features to audit
    enabled = feature_names()
    routed = set(_STORE_PROVIDER_OF)
    assert names == {n for n in enabled if n in routed and n not in PRICE_FEATURES}
    # Known-disabled features must be ABSENT (honesty-fix invariants from the registry).
    for disabled in ("exchange_netflow", "vix_term_slope", "gtrends_search_interest"):
        assert disabled not in names
    # A known-wired feature must be PRESENT.
    assert "funding_rate" in names
    # The result is sorted + deterministic.
    assert feats == sorted(feats, key=lambda p: p[0])


def test_render_and_markdown_surface_a_leak():
    """The human report + the committed markdown must LOUDLY surface a leak when one is found."""
    provider = _FixtureProvider({("BTCUSDT", "leaky_feat"): _leaked_points()})
    report = run_audit_all(
        provider, _bars_loader, assets=["BTCUSDT"], features=[("leaky_feat", "fixture")],
        shuffle_trials=60, seed=7,
    )
    text = report.render()
    assert "LEAKAGE AUDIT" in text
    assert "REAL LEAK" in text
    assert "leaky_feat" in text
    md = report.markdown()
    assert "LEAK FOUND" in md
    assert "| `leaky_feat` |" in md
    assert "**FAIL**" in md
