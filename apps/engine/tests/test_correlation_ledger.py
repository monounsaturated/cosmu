# Correlation memory: every correlation_scan finding is persisted to correlation_findings (queryable + TRACKED
# over runs), the persist is opt-in + best-effort (a failure never breaks a scan), non-causal features are honestly
# flagged, and the read side gives latest-per-feature + per-feature IC history for decay-tracking. OFFLINE only.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.correlation_ledger import (
    CorrelationPersist,
    deflated_note_for,
    feature_history,
    latest_findings,
    persist_findings,
)


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


def _store(tmp_path, name="cledger") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _persist(store, run_id="run-1") -> CorrelationPersist:
    return CorrelationPersist(store=store, run_id=run_id, data_source="fixture")


def test_persist_writes_one_row_per_finding_and_an_event(tmp_path):
    store = _store(tmp_path)
    findings = [
        _Finding("funding_rate", "ccxt", "BTCUSDT", 5, 0.21, 300, 0.001, survived_fdr=True),
        _Finding("fear_greed", "alternative.me", "ETHUSDT", 1, -0.04, 250, 0.42),
    ]
    n = persist_findings(_persist(store), findings)
    assert n == 2

    rows = store.rows("SELECT feature, asset, horizon, ic, n, p, fdr_survived, data_source FROM correlation_findings ORDER BY feature")
    assert len(rows) == 2
    fr = next(r for r in rows if r["feature"] == "funding_rate")
    assert fr["asset"] == "BTCUSDT" and fr["horizon"] == 5
    assert abs(float(fr["ic"]) - 0.21) < 1e-9
    assert fr["n"] == 300
    assert fr["fdr_survived"] == 1
    assert fr["data_source"] == "fixture"

    events = store.rows("SELECT kind, ref_type, ref_id, payload FROM events WHERE kind = 'correlation_scan_run'")
    assert len(events) == 1
    assert events[0]["ref_id"] == "run-1"


def test_persist_is_propose_only_default_path_writes_nothing(tmp_path):
    """A scan that does NOT pass a CorrelationPersist writes zero rows — the ledger only persists when opted in."""
    store = _store(tmp_path)
    # the scan path simply never calls persist_findings; assert the table starts empty (no implicit writes).
    assert store.rows("SELECT COUNT(*) AS c FROM correlation_findings")[0]["c"] == 0
    assert persist_findings(_persist(store), []) == 0  # empty findings → no-op, still zero rows
    assert store.rows("SELECT COUNT(*) AS c FROM correlation_findings")[0]["c"] == 0


def test_noncausal_feature_is_honestly_flagged(tmp_path):
    store = _store(tmp_path)
    # astro_lunar_phase is a registered NON-CAUSAL CONTROL feature; a strong IC on it must be flagged as such.
    findings = [_Finding("astro_lunar_phase", "astro", "BTCUSDT", 20, 0.18, 200, 0.002, survived_fdr=True)]
    persist_findings(_persist(store), findings)
    row = store.row("SELECT deflated_note FROM correlation_findings WHERE feature = 'astro_lunar_phase'")
    assert "NON-CAUSAL" in row["deflated_note"]

    # a causal feature carries no non-causal flag.
    assert "NON-CAUSAL" not in deflated_note_for("funding_rate")
    # a registered non-causal control is flagged via the registry prior (single source of truth).
    assert "NON-CAUSAL" in deflated_note_for("astro_lunar_phase")


def test_latest_findings_newest_first_and_survived_only(tmp_path):
    store = _store(tmp_path)
    persist_findings(_persist(store, "run-old"), [
        _Finding("funding_rate", "ccxt", "BTCUSDT", 5, 0.10, 300, 0.05, survived_fdr=False),
    ])
    persist_findings(_persist(store, "run-new"), [
        _Finding("vix_level", "fred", "BTCUSDT", 5, 0.30, 300, 0.0001, survived_fdr=True),
        _Finding("defi_tvl", "defillama", "ETHUSDT", 1, 0.02, 300, 0.6, survived_fdr=False),
    ])
    latest = latest_findings(store, limit=10)
    assert len(latest) == 3
    assert latest[0]["run_id"] == "run-new"  # newest run first

    survived = latest_findings(store, survived_only=True)
    assert len(survived) == 1
    assert survived[0]["feature"] == "vix_level"


def test_feature_history_tracks_ic_across_runs_oldest_first(tmp_path):
    """The core of TRACKING: the same feature scanned across runs is queryable as an IC time series (decay)."""
    store = _store(tmp_path)
    # three runs of the same feature/asset/horizon with a DECAYING IC — the tell a single print can't show.
    for run_id, ic in (("r1", 0.25), ("r2", 0.12), ("r3", 0.01)):
        persist_findings(
            CorrelationPersist(store=store, run_id=run_id, data_source="fixture"),
            [_Finding("funding_rate", "ccxt", "BTCUSDT", 5, ic, 300, 0.01)],
        )
    hist = feature_history(store, "funding_rate", asset="BTCUSDT", horizon=5)
    assert [r["run_id"] for r in hist] == ["r1", "r2", "r3"]  # oldest first
    ics = [float(r["ic"]) for r in hist]
    assert ics == sorted(ics, reverse=True)  # monotonically decaying as inserted
    assert abs(ics[0] - 0.25) < 1e-9 and abs(ics[-1] - 0.01) < 1e-9


def test_persist_failure_is_swallowed_and_never_raises(tmp_path):
    """Best-effort + offline-safe: a broken store must NOT crash the scan — persist returns 0, never raises."""

    class _Broken(Store):
        def batch(self):  # type: ignore[override]
            raise RuntimeError("DB down")

    broken = _Broken(Settings(database_url=f"sqlite:///{tmp_path}/broken.sqlite3"))
    n = persist_findings(CorrelationPersist(store=broken, run_id="x"), [
        _Finding("funding_rate", "ccxt", "BTCUSDT", 5, 0.2, 300, 0.01),
    ])
    assert n == 0  # swallowed, not raised


def test_reads_are_offline_safe_on_missing_table(tmp_path):
    """latest_findings / feature_history return [] (never raise) when the read fails — UI/decay-tracking safe."""

    class _NoTable(Store):
        def rows(self, query, params=()):  # type: ignore[override]
            raise RuntimeError("no such table")

    bad = _NoTable(Settings(database_url=f"sqlite:///{tmp_path}/nt.sqlite3"))
    assert latest_findings(bad) == []
    assert feature_history(bad, "funding_rate") == []
