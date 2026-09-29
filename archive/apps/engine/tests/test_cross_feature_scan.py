# The CROSSING engine: PIT cross-correlation BETWEEN alt-data sources (not feature→return). Two correlated synthetic
# series surface as an FDR-surviving pair; two independent series do not; a pair touching a registered non-causal
# control is KEPT and FLAGGED; the lead leg is strictly past→future; the persist reuses the SAME correlation_findings
# table (pair encoded as feature="A~B" / source="cross-feature" / horizon=lag). Deterministic + OFFLINE only.

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.data.providers.store import AltDataPoint, PgAltDataStore
from cosmu.knowledge.store import Store
from cosmu.master.correlation_ledger import CorrelationPersist, latest_findings
from cosmu.research.cross_feature_scan import (
    CROSS_SOURCE,
    PairICResult,
    decode_pair,
    encode_pair,
    persist_pair_findings,
    run_cross_feature_scan,
    scan_pair,
)


def _store(tmp_path, name="cross") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _bars(n: int) -> list[Bar]:
    """A flat bar timeline (the bars are just the shared clock the two feature series align onto — the cross-feature
    scan correlates feature↔feature, never feature→return, so the close prices are irrelevant here)."""
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    return [Bar(ts=t0 + timedelta(days=i), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
                close=Decimal("100"), volume=Decimal("0")) for i in range(n)]


def _points(bars: list[Bar], fn) -> list[AltDataPoint]:
    """Seed an alt series whose value at bar i is fn(i), available_at = the bar's own ts (PIT: known at bar t)."""
    return [AltDataPoint(ts=b.ts, available_at=b.ts, value=float(fn(i))) for i, b in enumerate(bars)]


def _fixture(tmp_path):
    """A DETERMINISTIC offline fixture, NO network / NO LLM:
      - fear_greed (A) and reddit_post_volume (B) are a CLEAN monotone function of the same driver → a strong,
        FDR-surviving CONTEMPORANEOUS cross-correlation (the 'these two sources move together' signal).
      - astro_lunar_phase (C) is an INDEPENDENT, registered NON-CAUSAL control series → its pairs must NOT survive
        FDR, and ANY finding touching it must carry the honest non-causal note.
    All three route to the market-wide 'MARKET' key in the store-backed provider."""
    store = _store(tmp_path)
    bars = _bars(240)
    pg = PgAltDataStore(store)

    driver = [float((i * 31) % 97) for i in range(len(bars))]  # pseudo-random but fully deterministic
    pg.append("alternative.me", "MARKET", "fear_greed", _points(bars, lambda i: driver[i]))
    # B is a strictly-monotone transform of the SAME driver → Spearman ic ≈ +1 contemporaneously (rank-preserving).
    pg.append("reddit_volume", "MARKET", "reddit_post_volume", _points(bars, lambda i: driver[i] * 2.0 + 7.0))
    # C is an INDEPENDENT deterministic wiggle, uncorrelated in rank with the driver (a different period).
    pg.append("astro", "MARKET", "astro_lunar_phase", _points(bars, lambda i: math.sin(i * 1.317) * 1000.0))
    return store, {"BTCUSDT": bars}


def test_encode_decode_pair_is_sorted_and_collision_free():
    # the pair key is SORTED so (A,B) and (B,A) land under one tracked series; decode round-trips.
    assert encode_pair("reddit_post_volume", "fear_greed") == "fear_greed~reddit_post_volume"
    assert encode_pair("a", "b") == encode_pair("b", "a")
    assert decode_pair("fear_greed~reddit_post_volume") == ("fear_greed", "reddit_post_volume")
    assert decode_pair("fear_greed") is None  # a single-feature scan row is NOT a pair


def test_correlated_pair_surfaces_and_survives_fdr(tmp_path):
    store, market = _fixture(tmp_path)
    rep = run_cross_feature_scan(
        store, market, lags=(0,),
        features=["fear_greed", "reddit_post_volume", "astro_lunar_phase"],
    )
    by_pair = {(r.feature, r.lag): r for r in rep.results}

    fg_reddit = by_pair[("fear_greed~reddit_post_volume", 0)]
    assert fg_reddit.ic > 0.95          # a clean monotone relationship → near-perfect rank correlation
    assert fg_reddit.survived_fdr        # the real correlated pair clears BH-FDR
    # neither leg is a registered NON-CAUSAL control → no non-causal red-flag on this pair (the honest note may still
    # carry a leg's low-confidence prior, which is correct: it flags trust, not a known-false relationship).
    assert "NON-CAUSAL" not in fg_reddit.deflated_note


def test_independent_pair_does_not_survive_and_noncausal_is_flagged(tmp_path):
    store, market = _fixture(tmp_path)
    rep = run_cross_feature_scan(
        store, market, lags=(0,),
        features=["fear_greed", "reddit_post_volume", "astro_lunar_phase"],
    )
    by_pair = {(r.feature, r.lag): r for r in rep.results}

    # the independent astro series does NOT have a strong, surviving correlation with the driver-linked features.
    fg_astro = by_pair[("astro_lunar_phase~fear_greed", 0)]
    assert abs(fg_astro.ic) < 0.3        # independent → weak rank correlation
    assert not fg_astro.survived_fdr     # noise: does not clear FDR
    # ACCEPTED + FLAGGED: a pair touching a registered NON-CAUSAL control carries the honest note (never dropped).
    assert "NON-CAUSAL" in fg_astro.deflated_note and "astro_lunar_phase" in fg_astro.deflated_note


def test_lead_leg_is_strictly_past_to_future_no_lookahead():
    # scan_pair at lag k pairs a_t with b_{t+k}: the b-value is strictly LATER than the a-value. Build a series where
    # b at bar t equals a at bar t-1 (b is a one-step-lagged echo of a) → a should LEAD b by exactly lag 1.
    bars = _bars(120)
    a_vals = {b.ts.isoformat(): float((i * 13) % 89) for i, b in enumerate(bars)}
    b_vals = {b.ts.isoformat(): a_vals[bars[i - 1].ts.isoformat()] for i, b in enumerate(bars) if i >= 1}
    res = {r.lag: r for r in scan_pair(a_vals, b_vals, "a_feat", "b_feat", "BTCUSDT", bars, lags=(0, 1))}
    assert res[1].ic > 0.95   # a_t == b_{t+1} by construction → near-perfect LEAD at lag 1
    assert abs(res[0].ic) < res[1].ic  # the contemporaneous correlation is weaker than the true 1-step lead


def test_non_overlapping_stride_keeps_n_honest(tmp_path):
    # lag-k samples are stride-sampled by (k+1) so windows don't overlap — the effective n must SHRINK with the lag,
    # never stay at the raw bar count (overlapping windows would inflate n and deflate p dishonestly).
    bars = _bars(240)
    a_vals = {b.ts.isoformat(): float((i * 31) % 97) for i, b in enumerate(bars)}
    b_vals = dict(a_vals)
    res = {r.lag: r.n_obs for r in scan_pair(a_vals, b_vals, "a", "b", "BTCUSDT", bars, lags=(0, 1, 5))}
    assert res[0] > res[1] > res[5]                 # honest n shrinks as the stride grows with the lag
    assert res[5] <= len(bars) // 6 + 1             # lag 5 → every 6th bar, never the raw count


def test_pair_persists_to_correlation_findings_with_the_pair_encoding(tmp_path):
    # the CROSSING reuses the SAME correlation_findings table; assert the pair encoding the API/UI reads back.
    store, market = _fixture(tmp_path)
    persist = CorrelationPersist(store=store, run_id="cross-run-1", data_source="fixture")
    rep = run_cross_feature_scan(
        store, market, lags=(0,),
        features=["fear_greed", "reddit_post_volume", "astro_lunar_phase"], persist=persist,
    )

    rows = latest_findings(store)
    assert len(rows) == rep.n_tests
    assert all(r["run_id"] == "cross-run-1" and r["data_source"] == "fixture" for r in rows)
    # EVERY persisted row is a pair row: feature encodes the pair, source is the cross-feature tag, horizon is the lag.
    assert all("~" in r["feature"] for r in rows)
    assert all(r["source"] == CROSS_SOURCE for r in rows)
    assert all(int(r["horizon"]) == 0 for r in rows)
    # the persisted IC matches the report (no fabrication, no rounding drift).
    fg_reddit = next(r for r in rows if r["feature"] == "fear_greed~reddit_post_volume")
    rep_ic = next(r.ic for r in rep.results if r.feature == "fear_greed~reddit_post_volume")
    assert abs(float(fg_reddit["ic"]) - rep_ic) < 1e-9
    # a cross_feature_scan_run event was emitted under the run_id (one queryable unit).
    ev = store.rows("SELECT ref_id FROM events WHERE kind = 'cross_feature_scan_run'")
    assert len(ev) == 1 and ev[0]["ref_id"] == "cross-run-1"


def test_default_path_is_propose_only_and_persists_nothing(tmp_path):
    store, market = _fixture(tmp_path)
    rep = run_cross_feature_scan(store, market, lags=(0,),
                                 features=["fear_greed", "reddit_post_volume", "astro_lunar_phase"])
    assert rep.n_tests >= 1  # the scan still runs + ranks
    assert store.rows("SELECT COUNT(*) AS c FROM correlation_findings")[0]["c"] == 0  # but wrote nothing (opt-in)


def test_scan_is_deterministic_for_a_fixed_fixture(tmp_path):
    store_a, market_a = _fixture(tmp_path)
    # rebuild an identical fixture in a second store → identical ranked ICs (the machine that never lies is reproducible).
    import shutil
    dst = tmp_path / "second"
    dst.mkdir()
    store_b, market_b = _fixture(dst)
    feats = ["fear_greed", "reddit_post_volume", "astro_lunar_phase"]
    a = run_cross_feature_scan(store_a, market_a, lags=(0, 1), features=feats)
    b = run_cross_feature_scan(store_b, market_b, lags=(0, 1), features=feats)
    assert [(r.feature, r.lag, r.ic, r.n_obs, r.p_value) for r in a.results] == \
           [(r.feature, r.lag, r.ic, r.n_obs, r.p_value) for r in b.results]
    _ = shutil  # keep the import used (tmp dir layout)


def test_persist_failure_never_breaks_the_scan(tmp_path):
    # best-effort + offline-safe: a broken PERSIST store must NOT crash the scan — the report is returned unchanged.
    store, market = _fixture(tmp_path)

    class _Broken(Store):
        def batch(self):  # type: ignore[override]
            raise RuntimeError("DB down")

    broken = _Broken(Settings(database_url=f"sqlite:///{tmp_path}/broken.sqlite3"))
    persist = CorrelationPersist(store=broken, run_id="x", data_source="fixture")
    rep = run_cross_feature_scan(store, market, lags=(0,),
                                 features=["fear_greed", "reddit_post_volume", "astro_lunar_phase"], persist=persist)
    assert rep.n_tests >= 1  # completed + returned its ranked report despite the persist failure


def test_persist_pair_findings_empty_is_a_noop(tmp_path):
    store = _store(tmp_path)
    assert persist_pair_findings(CorrelationPersist(store=store, run_id="r"), []) == 0
    assert store.rows("SELECT COUNT(*) AS c FROM correlation_findings")[0]["c"] == 0


def test_pairiresult_feature_property_is_the_sorted_pair_key():
    r = PairICResult(a="zeta", b="alpha", asset="BTCUSDT", lag=0, ic=0.5, n_obs=100, p_value=0.01)
    assert r.feature == "alpha~zeta"  # sorted, so (a,b) order never splits the tracked series
