"""Phase 1.6: the four-arm cross-asset ablation — does combining asset classes beat any single one?"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import cosmu.research.gate as gate_mod
from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataStore, FixtureAltDataProvider, StoreBackedAltProvider
from cosmu.data.sources.multiasset import MULTIASSET_METRICS
from cosmu.ingest.pipeline import ingest_market_wide_numeric, ingest_news_sentiment, ingest_numeric
from cosmu.knowledge.store import Store
from cosmu.research.fixtures import synthetic_cross_asset_inputs
from cosmu.research.gate import evaluate_cross_asset_ablation


def _store(tmp_path, name="xa") -> Store:
    # no openrouter_api_key → the whole gate runs offline (CI has no keys); the LLM is ingest-only.
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _ingest_synthetic(astore: AltDataStore, market_by_class, alt, news) -> None:
    """Fill the append-only point-in-time store from the fixture providers, exactly as a scheduled worker
    would from the real free APIs — funding/fear-greed per crypto symbol, news standardized once, and the
    two market-wide cross-asset transfer series (risk_on / macro_regime)."""
    crypto = list(market_by_class["crypto"])
    all_symbols = [s for cls in market_by_class.values() for s in cls]
    ingest_numeric(astore, alt, crypto, "funding_rate", provider_name="binance")
    ingest_numeric(astore, alt, crypto, "fear_greed", provider_name="alternative.me")
    ingest_news_sentiment(astore, news, all_symbols)  # LLM standardization happens HERE, once, offline
    ingest_market_wide_numeric(astore, alt, source_metric="risk_on", stored_metric="risk_on", provider_name="polymarket")
    ingest_market_wide_numeric(astore, alt, source_metric="macro_regime", stored_metric="macro_regime", provider_name="fred")


def test_cross_asset_passes_when_combining_classes_adds_edge(tmp_path):
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    store = _store(tmp_path, "pass")
    v = evaluate_cross_asset_ablation(market_by_class, alt, news, store)

    assert v.decision == "PASS"
    # arm (3) cross-asset+alt beats arm (2) single-asset+alt, arm (1) price-only, and buy-and-hold — all net.
    assert v.xasset_return > v.single_alt_return
    assert v.xasset_return > v.price_only_return
    assert v.xasset_return > v.buy_and_hold_return
    assert v.xasset_dsr >= 0.95
    assert v.cscv_pbo < 0.5
    assert v.regimes_positive >= 2
    assert v.num_trades >= 30


def test_cross_asset_edge_comes_from_the_transfer_features(tmp_path):
    # The honest claim: the edge comes from the CROSS-ASSET transfer features (prediction-market risk_on +
    # FRED macro_regime), not from price the single-asset arms already see. Their drop-one delta must be > 0.
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    v = evaluate_cross_asset_ablation(market_by_class, alt, news, _store(tmp_path))
    deltas = {d.source: d.delta for d in v.drop_one_source}
    assert deltas["risk_on"] > 0
    assert deltas["macro_regime"] > 0
    # the per-asset-class report exists for both traded classes, sorted by contribution
    classes = {c.asset_class for c in v.drop_one_class}
    assert classes == {"crypto", "equity"}
    assert v.drop_one_class == sorted(v.drop_one_class, key=lambda c: c.delta, reverse=True)


def test_cross_asset_stops_narrow_without_a_transfer_edge(tmp_path):
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=False, seed=7)
    v = evaluate_cross_asset_ablation(market_by_class, alt, news, _store(tmp_path, "stop"))
    assert v.decision == "STOP-narrow"
    assert v.reasons


def test_every_attempt_is_counted_once_in_the_global_trial_ledger(tmp_path):
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    store = _store(tmp_path, "trials")
    v = evaluate_cross_asset_ablation(market_by_class, alt, news, store)
    # drop-one is a diagnostic, not a hypothesis — only the arms + CSCV grid register trials.
    assert len(store.rows("SELECT 1 FROM trials")) == v.attempts
    assert v.attempts <= v.bar["attempt_budget"]


def test_cross_asset_is_deterministic(tmp_path):
    a_in = synthetic_cross_asset_inputs(edge=True, seed=7)
    b_in = synthetic_cross_asset_inputs(edge=True, seed=7)
    a = evaluate_cross_asset_ablation(*a_in, _store(tmp_path, "da"))
    b = evaluate_cross_asset_ablation(*b_in, _store(tmp_path, "db"))
    assert (a.decision, a.xasset_dsr, a.cscv_pbo, a.xasset_return) == (b.decision, b.xasset_dsr, b.cscv_pbo, b.xasset_return)


def test_gate_runs_on_the_real_ingestion_seam_with_zero_llm(tmp_path, monkeypatch):
    """The production path: ingest free sources into the append-only point-in-time store, then run the SAME
    gate against a StoreBackedAltProvider with news read as a pre-standardized numeric series. The gate must
    reach the same PASS AND make ZERO LLM calls (the LLM ran only at ingest)."""
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    astore = AltDataStore(root=tmp_path / "alt")
    _ingest_synthetic(astore, market_by_class, alt, news)

    # poison the LLM seam: if the gate touches news standardization, it explodes.
    def _boom(*_a, **_k):
        raise AssertionError("LLM/standardize_news must not run in the gate/scoring path")

    monkeypatch.setattr(gate_mod, "standardize_news", _boom)

    # fear_greed is per-symbol in this fixture (crypto sentiment), so exclude it from the market-wide set.
    store_alt = StoreBackedAltProvider(astore, market_wide=frozenset({"risk_on", "macro_regime"}))
    v = evaluate_cross_asset_ablation(market_by_class, store_alt, None, _store(tmp_path, "seam"))
    assert v.decision == "PASS"
    assert v.xasset_return > v.single_alt_return > v.price_only_return
    assert v.xasset_return > v.buy_and_hold_return


def test_ingestion_is_point_in_time_and_idempotent_in_view(tmp_path):
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    astore = AltDataStore(root=tmp_path / "alt")
    _ingest_synthetic(astore, market_by_class, alt, news)
    before = astore.read_asof("polymarket", "MARKET", "risk_on", _far_future())
    _ingest_synthetic(astore, market_by_class, alt, news)  # re-run a scheduled pass
    after = astore.read_asof("polymarket", "MARKET", "risk_on", _far_future())
    # append-only re-run never changes the point-in-time VIEW (latest-revision-per-ts is identical)
    assert [(p.ts, p.value) for p in before] == [(p.ts, p.value) for p in after]


def _far_future():
    from datetime import UTC, datetime

    return datetime(2099, 1, 1, tzinfo=UTC)


def test_cross_asset_transfer_features_are_registered_with_pinned_transforms():
    by_name = {f.name: f for f in FEATURE_REGISTRY}
    for name in ("pm_risk_on", "xasset_risk_appetite", "macro_regime"):
        assert name in by_name, f"missing cross-asset feature {name}"
        feat = by_name[name]
        assert feat.transform_version is not None  # a survivor must be re-runnable byte-for-byte
        assert len(feat.asset_classes) >= 2  # cross-asset by construction
        assert feat.prior  # every source declares a prior hypothesis (more data = more overfit surface)


# --- Cross-market STATIONARY transfer features (gold/silver/wti/spx/ndx/eurusd/usdjpy) -----------
# These are free, market-wide daily price LEVELS. PR #87 read them as RAW levels, so an absolute threshold
# overfit the in-sample range. The gate now turns each into a causal rolling z-score (stationary) and folds
# them into the cross-asset arm as one equal-weight composite, with per-source drop-one attribution. The
# tests below pin the contract: the sources are attributed, the z-score is location/scale invariant (no
# raw-level overfit), an absent series is a clean pass-through, a real cross-market signal flows through, and
# the whole thing is deterministic. All offline (the multiasset series are injected as fixtures; no network).

_XA_START = datetime(2023, 1, 1, tzinfo=UTC)  # matches synthetic_cross_asset_inputs' bar window


def _xmarket_levels(metric: str, *, n: int = 600, seed: int = 7, scale: float = 1.0, offset: float = 0.0, noise: float = 0.01) -> list[AltDataPoint]:
    """A deterministic, point-in-time daily LEVEL series (a positive random walk) for one cross-market metric,
    aligned day-for-day to the synthetic bar window. `scale`/`offset` apply an affine transform to the LEVEL —
    used to prove the z-score (and thus the verdict) is invariant to the absolute level."""
    rng = random.Random(f"xm-level-{metric}-{seed}")  # str seed → process-stable
    level = 1000.0
    out: list[AltDataPoint] = []
    for i in range(n):
        level = max(1.0, level * (1 + rng.gauss(0, noise)))
        ts = _XA_START + timedelta(days=i)
        out.append(AltDataPoint(ts=ts, available_at=ts, value=level * scale + offset))
    return out


def _augment_with_xmarket(alt: FixtureAltDataProvider, *, scale: float = 1.0, offset: float = 0.0, signal_into: dict[str, str] | None = None) -> FixtureAltDataProvider:
    """Return a fresh provider carrying the synthetic alt series PLUS a cross-market LEVEL series per metric.
    `signal_into` maps a metric → an existing market-wide series name (e.g. "risk_on") whose values are copied
    in as that metric's levels, so the metric's z-score carries a REAL transfer signal instead of noise."""
    series = dict(alt.series)
    signal_into = signal_into or {}
    for m in MULTIASSET_METRICS:
        if m in signal_into:
            src = alt.series[("MARKET", signal_into[m])]
            series[("MARKET", m)] = [AltDataPoint(ts=p.ts, available_at=p.available_at, value=1000.0 + 1000.0 * p.value) for p in src]
        else:
            series[("MARKET", m)] = _xmarket_levels(m, scale=scale, offset=offset)
    return FixtureAltDataProvider(series)


def test_cross_market_sources_are_attributed_in_drop_one(tmp_path):
    """Every multiasset cross-market metric is wired into the arm and gets its own per-source drop-one entry
    (alongside the original news/funding/fear_greed/risk_on/macro_regime sources)."""
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    alt = _augment_with_xmarket(alt)
    v = evaluate_cross_asset_ablation(market_by_class, alt, news, _store(tmp_path, "xm_attr"))
    sources = {d.source for d in v.drop_one_source}
    assert set(MULTIASSET_METRICS) <= sources, f"cross-market sources missing from drop-one: {set(MULTIASSET_METRICS) - sources}"
    # drop-one stays diagnostic-only — the counted attempts (arms + CSCV grid) are unchanged by the new sources.
    assert v.attempts <= v.bar["attempt_budget"]


def test_cross_market_zscore_is_location_and_scale_invariant(tmp_path):
    """The whole point of the stationary fix: the verdict CANNOT depend on the cross-market series' absolute
    level. A causal rolling z-score is affine-invariant, so multiplying every level by 1e3 and adding 5e6
    (the exact overfit surface a raw EUR/USD threshold exploited) leaves the decision, returns, and every
    cross-market drop-one delta byte-for-byte identical."""
    mbc_a, alt_a, news_a = synthetic_cross_asset_inputs(edge=True, seed=7)
    mbc_b, alt_b, news_b = synthetic_cross_asset_inputs(edge=True, seed=7)
    a = evaluate_cross_asset_ablation(mbc_a, _augment_with_xmarket(alt_a, scale=1.0, offset=0.0), news_a, _store(tmp_path, "inv_a"))
    b = evaluate_cross_asset_ablation(mbc_b, _augment_with_xmarket(alt_b, scale=1000.0, offset=5_000_000.0), news_b, _store(tmp_path, "inv_b"))
    assert (a.decision, a.xasset_return, a.xasset_dsr, a.num_trades) == (b.decision, b.xasset_return, b.xasset_dsr, b.num_trades)
    da = {d.source: d.delta for d in a.drop_one_source if d.source in set(MULTIASSET_METRICS)}
    db = {d.source: d.delta for d in b.drop_one_source if d.source in set(MULTIASSET_METRICS)}
    assert da == db


def test_cross_market_is_passthrough_and_inert_when_absent(tmp_path):
    """With NO multiasset data the composite term is a clean pass-through: each cross-market source is still
    attributed, but dropping it cannot change the signal, so its delta is exactly zero (no fabricated edge)."""
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)  # no multiasset series
    v = evaluate_cross_asset_ablation(market_by_class, alt, news, _store(tmp_path, "xm_absent"))
    xm_deltas = {d.source: d.delta for d in v.drop_one_source if d.source in set(MULTIASSET_METRICS)}
    assert set(xm_deltas) == set(MULTIASSET_METRICS)
    assert all(delta == 0.0 for delta in xm_deltas.values()), xm_deltas


def test_cross_market_transfer_signal_flows_through_the_composite(tmp_path):
    """The wiring is NOT inert: a genuine cross-market transfer signal flows through the composite and is
    consulted by the arm. Feed every cross-market metric a level series that tracks the risk_on regime (so the
    composite reduces to a true regime lead). The arm still PASSES and still beats the single-asset arm — the
    transfer signal is captured without breaking the edge — and the verdict measurably differs from the
    no-cross-market case, proving the term is live (not dead code).

    Note (honesty): we deliberately do NOT assert a signal-carrying metric out-ranks noise in drop-one. On
    these synthetic bars the cross-market series have no TRUE relationship to returns, so per-source drop-one
    deltas are dominated by spurious in-sample correlation — a noise metric can out-rank a planted one. That
    is exactly why the gate's verdict rests on the pre-registered DSR/PBO/regime bar, not the drop-one ranking."""
    mbc_a, alt_a, news_a = synthetic_cross_asset_inputs(edge=True, seed=7)
    v_absent = evaluate_cross_asset_ablation(mbc_a, alt_a, news_a, _store(tmp_path, "xm_absent2"))
    mbc_b, alt_b, news_b = synthetic_cross_asset_inputs(edge=True, seed=7)
    alt_b = _augment_with_xmarket(alt_b, signal_into={m: "risk_on" for m in MULTIASSET_METRICS})
    v = evaluate_cross_asset_ablation(mbc_b, alt_b, news_b, _store(tmp_path, "xm_signal"))
    assert v.decision == "PASS"
    assert v.xasset_return > v.single_alt_return  # the cross-asset arm still beats single-asset with the composite live
    assert v.xasset_return != v_absent.xasset_return  # the composite term is genuinely consulted, not inert


def test_cross_market_wiring_is_deterministic(tmp_path):
    market_by_class, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    a = evaluate_cross_asset_ablation(market_by_class, _augment_with_xmarket(alt), news, _store(tmp_path, "det_a"))
    mbc2, alt2, news2 = synthetic_cross_asset_inputs(edge=True, seed=7)
    b = evaluate_cross_asset_ablation(mbc2, _augment_with_xmarket(alt2), news2, _store(tmp_path, "det_b"))
    assert (a.decision, a.xasset_return, a.xasset_dsr, a.cscv_pbo) == (b.decision, b.xasset_return, b.xasset_dsr, b.cscv_pbo)
    assert [(d.source, d.delta) for d in a.drop_one_source] == [(d.source, d.delta) for d in b.drop_one_source]
