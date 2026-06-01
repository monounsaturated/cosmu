"""Phase 1.6: the four-arm cross-asset ablation — does combining asset classes beat any single one?"""

from __future__ import annotations

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research.fixtures import synthetic_cross_asset_inputs
from cosmu.research.gate import evaluate_cross_asset_ablation


def _store(tmp_path, name="xa") -> Store:
    # no openrouter_api_key → the whole gate runs offline (CI has no keys); the LLM is ingest-only.
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


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


def test_cross_asset_transfer_features_are_registered_with_pinned_transforms():
    by_name = {f.name: f for f in FEATURE_REGISTRY}
    for name in ("pm_risk_on", "xasset_risk_appetite", "macro_regime"):
        assert name in by_name, f"missing cross-asset feature {name}"
        feat = by_name[name]
        assert feat.transform_version is not None  # a survivor must be re-runnable byte-for-byte
        assert len(feat.asset_classes) >= 2  # cross-asset by construction
        assert feat.prior  # every source declares a prior hypothesis (more data = more overfit surface)
