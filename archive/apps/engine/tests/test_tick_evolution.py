"""The REPLICATE stage of the autonomous master tick — the self-reinforcing flywheel wired into scheduler.run_tick:
- a tick that gates ≥1 survivor REPLICATES it (evolution.run_evolution_cohort) and audits the result,
- replication is routed through the SAME deterministic gate (it never decides edge itself; FDR is the brake),
- it is best-effort: a replication blow-up never aborts an already-gated tick,
- it is deterministic for a fixed (winners, seed), and stays PAPER-only (the tick never arms live).
All offline: edge-bearing fixture, no network/keys.
"""

from __future__ import annotations

import json

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.scheduler import _load_survivor_specs, _screen_provider, run_tick


def _store(tmp_path, name: str = "tick") -> Store:
    # The replication tick's screen fixture trends up, so a long-only survivor cannot beat holding; this test
    # exercises the replicate-survivors-through-the-same-gate PLUMBING, not the cash benchmark, so opt the
    # beat-buy-and-hold gate out (covered separately). The statistical gate still decides what survives.
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/{name}.sqlite3",
            openrouter_api_key=None,
            gates=GateSettings(require_beat_buy_and_hold=False),
        )
    )


def _no_ingest(_store) -> dict:
    return {"funding_rate": 3, "fear_greed": 1}


def _completed_payload(store: Store) -> dict:
    row = store.row("SELECT payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 1")
    assert row is not None
    return json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]


def test_tick_replicates_survivors_and_audits(tmp_path):
    store = _store(tmp_path)
    report = run_tick(store, n=6, seed=7, edge_market=True, ingest=_no_ingest)
    assert report.summary.gated_passed >= 1  # something cleared the gate, so replication had a parent

    # The flywheel ran: an autonomy_evolution event was written with the parents it replicated.
    ev = store.row("SELECT payload FROM events WHERE kind = 'autonomy_evolution' ORDER BY id DESC LIMIT 1")
    assert ev is not None
    payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
    assert payload["parents"] >= 1
    assert payload["seed"] == 7
    assert payload["evolved_survivors"] == report.evolved

    # The tick report + the completed-event audit both carry the flywheel's output count.
    assert report.evolved >= 0
    assert _completed_payload(store)["evolved"] == report.evolved


def test_replication_routes_through_the_same_gate(tmp_path):
    # Replication produces NO gate-bypassing rows: every replicated strategy_version that exists carries a screen
    # backtest whose passed_gates flag the GATE set — this code never marks a survivor itself. We assert every
    # graft/recombination row (name carries the evolve markers ' -> ' or ' x ') was screened, never injected.
    store = _store(tmp_path)
    run_tick(store, n=6, seed=7, edge_market=True, ingest=_no_ingest)

    derived = store.rows(
        """
        SELECT sv.id AS id FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        WHERE s.name LIKE '% -> %' OR s.name LIKE '% x %'
        """
    )
    assert derived, "the tick gated a survivor, so replication should have emitted grafts/recombinations"
    for row in derived:
        bt = store.row(
            "SELECT passed_gates FROM backtests WHERE strategy_version_id = ? AND kind = 'screen'",
            (row["id"],),
        )
        assert bt is not None, "a replicated version must be screened by the gate, never injected past it"


def test_replication_is_best_effort_and_never_aborts_the_tick(tmp_path, monkeypatch):
    # If replication blows up, the tick still completes: survivors are gated, funding + recommendations still run,
    # and the failure is audited — the flywheel is additive, never a new way to break an already-gated tick.
    import cosmu.master.scheduler as sched

    def _boom(*_a, **_k):
        raise RuntimeError("replication exploded")

    monkeypatch.setattr(sched, "_run_evolution", _boom)
    report = run_tick(store := _store(tmp_path), n=6, seed=7, edge_market=True, ingest=_no_ingest)

    assert report.skipped is False
    assert report.evolved == 0  # blew up → contributed nothing, but did not abort
    assert report.summary.gated_passed >= 1
    assert store.row("SELECT id FROM events WHERE kind = 'autonomy_evolution_failed'") is not None
    # The completed marker was still written (the cycle finished).
    assert store.row("SELECT id FROM events WHERE kind = 'autonomy_tick_completed'") is not None


def test_replication_is_deterministic_for_fixed_seed(tmp_path):
    # Same winners + same seed → same flywheel output count (the replicated cohort is seeded/reproducible).
    a = run_tick(_store(tmp_path, "a"), n=6, seed=7, edge_market=True, ingest=_no_ingest)
    b = run_tick(_store(tmp_path, "b"), n=6, seed=7, edge_market=True, ingest=_no_ingest)
    assert a.evolved == b.evolved


def test_load_survivor_specs_skips_missing_rows(tmp_path):
    # _load_survivor_specs reconstructs specs by version_id and quietly skips a survivor whose row is gone —
    # the flywheel must never crash on a stale/malformed reference.
    store = _store(tmp_path)

    class _Ev:
        def __init__(self, vid: str) -> None:
            self.version_id = vid

    assert _load_survivor_specs(store, [_Ev("does-not-exist")]) == []


def test_screen_provider_is_one_source_of_truth():
    # The resolver the tick uses for screen/replicate/fund: explicit wins, else fixture offline, else None (real).
    sentinel = object()
    assert _screen_provider(sentinel, edge_market=True) is sentinel  # explicit provider always wins
    assert _screen_provider(None, edge_market=True) is not None      # offline → edge-bearing fixture
    assert _screen_provider(None, edge_market=False) is None         # production → real Binance (None sentinel)
