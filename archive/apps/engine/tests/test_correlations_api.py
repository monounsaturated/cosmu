# GET /correlations serves the correlation engine read-out from the correlation_ledger: the latest run's findings,
# the BH-FDR survivors, a compact feature × asset IC heatmap for one horizon, and per-feature stability/decay
# (IC across runs). Read-only + propose-only — NEVER a Gate/money action. Honest empty state when no findings.
# OFFLINE only: seed the ledger via the canonical persist path, monkeypatch the store, assert the GET returns it.

from __future__ import annotations

from dataclasses import dataclass

import cosmu.api.routers.correlations as correlations_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.correlation_ledger import CorrelationPersist, persist_findings


@dataclass(frozen=True)
class _Finding:
    """Duck-typed stand-in for research.correlation_scan.ICResult (the ledger never imports the scanner)."""

    feature: str
    source: str
    asset: str
    horizon: int
    ic: float
    n_obs: int
    p_value: float
    survived_fdr: bool = False


def _store(tmp_path, name="corr_api") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(correlations_mod, "store", store)
    return TestClient(app_mod.app)


def _persist(store, run_id, findings):
    persist_findings(CorrelationPersist(store=store, run_id=run_id, data_source="fixture"), findings)


def test_honest_empty_state_when_no_findings(tmp_path, monkeypatch):
    """No findings yet → empty arrays + a null heatmap horizon. Never fabricated."""
    store = _store(tmp_path)
    body = _client(monkeypatch, store).get("/correlations").json()
    assert body["latest_run_id"] is None
    assert body["latest"] == [] and body["survivors"] == [] and body["stability"] == []
    assert body["heatmap"]["horizon"] is None
    assert body["heatmap"]["features"] == [] and body["heatmap"]["cells"] == []


def test_latest_run_findings_survivors_and_non_causal_flag(tmp_path, monkeypatch):
    store = _store(tmp_path)
    # an OLD run that must NOT bleed into the latest-run view.
    _persist(store, "run-old", [_Finding("funding_rate", "ccxt", "BTCUSDT", 5, 0.05, 300, 0.4)])
    # the LATEST run: a real survivor, a non-survivor, and a registered NON-CAUSAL control that survived FDR.
    _persist(store, "run-new", [
        _Finding("funding_rate", "ccxt", "BTCUSDT", 5, 0.22, 300, 0.001, survived_fdr=True),
        _Finding("defi_tvl", "defillama", "ETHUSDT", 1, 0.02, 300, 0.6, survived_fdr=False),
        _Finding("astro_lunar_phase", "astro", "BTCUSDT", 5, 0.18, 200, 0.002, survived_fdr=True),
    ])

    body = _client(monkeypatch, store).get("/correlations").json()
    assert body["latest_run_id"] == "run-new"
    # ONLY the latest run's three findings (the old run is excluded).
    assert len(body["latest"]) == 3
    assert {f["run_id"] for f in body["latest"]} == {"run-new"}

    # survivors = the two FDR-survivors of the latest run.
    survivors = {f["feature"] for f in body["survivors"]}
    assert survivors == {"funding_rate", "astro_lunar_phase"}

    # the non-causal control is honestly flagged; the causal survivor is not.
    by_feat = {f["feature"]: f for f in body["latest"]}
    assert by_feat["astro_lunar_phase"]["non_causal"] is True
    assert "NON-CAUSAL" in by_feat["astro_lunar_phase"]["deflated_note"]
    assert by_feat["funding_rate"]["non_causal"] is False
    # PIT-honest numerics carried through.
    assert abs(by_feat["funding_rate"]["ic"] - 0.22) < 1e-9
    assert by_feat["funding_rate"]["n"] == 300 and by_feat["funding_rate"]["fdr_survived"] is True
    assert by_feat["funding_rate"]["data_source"] == "fixture"


def test_heatmap_is_one_horizon_feature_by_asset(tmp_path, monkeypatch):
    store = _store(tmp_path)
    # horizon 5 is measured TWICE, horizon 1 once → the heatmap pins to the most-measured horizon (5).
    _persist(store, "run-h", [
        _Finding("funding_rate", "ccxt", "BTCUSDT", 5, 0.22, 300, 0.001, survived_fdr=True),
        _Finding("vix_level", "fred", "ETHUSDT", 5, -0.11, 300, 0.02),
        _Finding("defi_tvl", "defillama", "BTCUSDT", 1, 0.30, 300, 0.0001, survived_fdr=True),
    ])
    hm = _client(monkeypatch, store).get("/correlations").json()["heatmap"]
    assert hm["horizon"] == 5
    # only the two horizon-5 cells appear; the horizon-1 finding is excluded.
    assert {c["feature"] for c in hm["cells"]} == {"funding_rate", "vix_level"}
    assert hm["features"] == ["funding_rate", "vix_level"]
    assert hm["assets"] == ["BTCUSDT", "ETHUSDT"]
    cell = next(c for c in hm["cells"] if c["feature"] == "funding_rate")
    assert abs(cell["ic"] - 0.22) < 1e-9 and cell["fdr_survived"] is True and cell["non_causal"] is False


def test_stability_tracks_ic_decay_across_runs(tmp_path, monkeypatch):
    """The TRACKING core: a feature scanned across runs is a decay series (oldest-first), delta_ic negative."""
    store = _store(tmp_path)
    for run_id, ic in (("r1", 0.25), ("r2", 0.12), ("r3", 0.01)):
        _persist(store, run_id, [_Finding("funding_rate", "ccxt", "BTCUSDT", 5, ic, 300, 0.01)])
    stab = _client(monkeypatch, store).get("/correlations").json()["stability"]
    s = next(x for x in stab if x["feature"] == "funding_rate")
    assert s["n_runs"] == 3
    assert [p["run_id"] for p in s["history"]] == ["r1", "r2", "r3"]  # oldest first
    assert abs(s["first_ic"] - 0.25) < 1e-9 and abs(s["latest_ic"] - 0.01) < 1e-9
    assert s["delta_ic"] < 0  # decaying run-over-run
