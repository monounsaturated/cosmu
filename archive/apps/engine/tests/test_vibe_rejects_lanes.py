# The VIBE/EXPLORE lane and the REJECTS WATCH-LIST activation are OBSERVE-ONLY: they route a low-confidence idea
# (or a gate-rejected-but-close candidate) into a ZERO-CAPITAL paper track on the SAME SIM machinery survivors use,
# and NEVER touch the gate's pass/fail or any threshold. These offline tests pin: (A) the explore disposition
# (persist lane='explore' + zero-capital track + graduate-to-gate only on a clear) and (B) the rejects activation
# (watch_rejects=True bands close rejects; link_and_open opens zero-capital tracks + stamps strategy_version_id).
# Pure, DB-light, no network — all offline against a temp sqlite store.

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cosmu.config.settings import Settings
from cosmu.evolution.seeder import seed_breakout_spec
from cosmu.knowledge.store import Store
from cosmu.master.lane_router import (
    graduated_spec,
    is_explore,
    lane_of,
)
from cosmu.master.rejects_lane import (
    RejectsCandidate,
    link_and_open_rejects_tracks,
    persist_rejects_watch,
)
from cosmu.master.verdict_log import CohortPersist, persist_cohort_verdict
from cosmu.master.zero_capital import (
    enter_explore,
    graduate_explore,
    open_zero_capital_track,
    persist_explore_version,
)


def _store(tmp_path, name="vrl") -> Store:
    s = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))
    s.migrate()
    return s


@dataclass(frozen=True)
class _Promo:
    """Duck-typed stand-in for cohort.Promotion (the lanes read it by attribute, never import cohort)."""

    candidate_id: str
    promoted: bool
    deflated_sharpe_prob: float
    survived_fdr: bool
    net_profit: float = 0.0
    rank: int | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Cand:
    id: str
    label: str = "c"

    class _M:
        holdout_deflated_sharpe = None

    @property
    def metrics(self):  # noqa: ANN201
        return self._M()


# ---------------------------------------------------------------- (A) VIBE / EXPLORE lane


def test_explore_lane_default_is_gate_and_explore_flips_cleanly():
    spec = seed_breakout_spec()
    assert lane_of(spec) == "gate"  # every existing spec is gate-lane (default preserved)
    assert not is_explore(spec)
    ex = spec.model_copy(update={"lane": "explore"})
    assert is_explore(ex)
    # Graduation rewrites ONLY the lane (explore → gate); a non-explore spec is returned unchanged.
    assert graduated_spec(ex).lane == "gate"
    assert graduated_spec(spec) is spec


def test_persist_explore_version_stamps_explore_lane_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    spec = seed_breakout_spec()
    vid = persist_explore_version(store, spec)
    assert vid is not None
    row = store.row("SELECT spec, status, origin FROM strategy_versions WHERE id = ?", (vid,))
    assert row is not None
    assert json.loads(row["spec"])["lane"] == "explore"  # the vibe is observe-only until it graduates
    assert row["status"] == "screened"  # badge: Backtest — never funded by the strict gate
    assert row["origin"] == "explore"
    # Idempotent on the compiled code_hash: the same vibe re-entered returns the SAME version, never a duplicate.
    assert persist_explore_version(store, spec) == vid


def test_enter_explore_opens_a_zero_capital_track(tmp_path):
    store = _store(tmp_path)
    result = enter_explore(store, seed_breakout_spec())
    assert result is not None and result.opened
    vid = result.strategy_version_id
    # The track is ZERO capital — it can never move money and is weightless on every equity/leaderboard sum.
    track = store.row("SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert track is not None and str(track["starting_capital"]) in ("0", "0.0")
    # A FLAT (zero-qty) sim position is registered so the SIM executor's flat-row query observes it forward.
    pos = store.row(
        "SELECT qty, venue FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) = 0", (vid,)
    )
    assert pos is not None and pos["venue"] == "sim"
    # The lifecycle/maturity clock sees the track origin, tagged zero_capital.
    evt = store.row(
        "SELECT payload FROM events WHERE kind = 'zero_capital_track_opened' AND ref_id = ?", (vid,)
    )
    assert evt is not None and json.loads(evt["payload"])["origin"] == "explore"


def test_graduate_explore_flips_lane_only_when_gate_clears(tmp_path):
    store = _store(tmp_path)
    vid = persist_explore_version(store, seed_breakout_spec())
    assert vid is not None
    # Gate does NOT clear → nothing graduates, the vibe keeps observing on paper (lane stays 'explore').
    assert graduate_explore(store, vid, gate_clears=lambda _v: False) is False
    assert json.loads(store.row("SELECT spec FROM strategy_versions WHERE id = ?", (vid,))["spec"])["lane"] == "explore"
    # Gate clears → graduates to the gate-lane; the rest of the system now treats it as a normal survivor.
    assert graduate_explore(store, vid, gate_clears=lambda _v: True) is True
    assert json.loads(store.row("SELECT spec FROM strategy_versions WHERE id = ?", (vid,))["spec"])["lane"] == "gate"
    assert store.row("SELECT 1 FROM events WHERE kind = 'explore_graduated' AND ref_id = ?", (vid,)) is not None


# ---------------------------------------------------------------- (B) REJECTS WATCH-LIST activation


def _seed_explore_version(store: Store, spec, tag: str) -> str:
    """A persisted version for a rejects candidate (mirrors the finder: every screened variant gets a version)."""
    vid = persist_explore_version(store, spec.model_copy(update={"name": f"{spec.name} {tag}"}))
    assert vid is not None
    return vid


def test_watch_rejects_flag_bands_close_rejects(tmp_path):
    store = _store(tmp_path)
    candidates = [_Cand("close_a"), _Cand("far"), _Cand("survivor")]
    promotions = [
        _Promo("close_a", promoted=False, deflated_sharpe_prob=0.93, survived_fdr=True, reasons=["deflated_sharpe"]),
        _Promo("far", promoted=False, deflated_sharpe_prob=0.70, survived_fdr=True, reasons=["deflated_sharpe"]),
        _Promo("survivor", promoted=True, deflated_sharpe_prob=0.97, survived_fdr=True, reasons=[]),
    ]
    # watch_rejects=True opts the verdict-persist into banding the close rejects — NEVER changing the pass/fail.
    persist = CohortPersist(store=store, run_id="run-w", hypothesis="h", source="finder:test", watch_rejects=True)
    assert persist_cohort_verdict(persist, candidates, promotions) is True
    rows = store.rows("SELECT candidate_id FROM rejects_watch WHERE cohort_run_id = 'run-w'")
    # Only the in-band, FDR-surviving, non-critical near-miss is watched — the far reject + the survivor are not.
    assert [r["candidate_id"] for r in rows] == ["close_a"]
    # watch_rejects defaults OFF → an unflagged run watches nothing (every existing caller byte-for-byte unchanged).
    persist_off = CohortPersist(store=store, run_id="run-off", hypothesis="h", source="finder:test")
    persist_cohort_verdict(persist_off, candidates, promotions)
    assert store.rows("SELECT 1 FROM rejects_watch WHERE cohort_run_id = 'run-off'") == []


def test_link_and_open_rejects_tracks_opens_zero_capital_and_stamps_version(tmp_path):
    store = _store(tmp_path)
    spec = seed_breakout_spec()
    vid = _seed_explore_version(store, spec, "rj")
    persist_rejects_watch(
        store,
        [RejectsCandidate("close_a", deflated_sharpe_prob=0.93, net_profit=0.1, reasons=["deflated_sharpe"])],
        "run-1",
    )
    # Before linking, the watch row carries no track.
    assert store.row("SELECT strategy_version_id FROM rejects_watch WHERE candidate_id = 'close_a'")["strategy_version_id"] is None
    opened = link_and_open_rejects_tracks(store, "run-1", {"close_a": vid})
    assert opened == 1
    # The version is stamped back AND a ZERO-capital track was opened on the SAME SIM path survivors use.
    linked = store.row("SELECT strategy_version_id FROM rejects_watch WHERE candidate_id = 'close_a'")
    assert linked["strategy_version_id"] == vid
    track = store.row("SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert track is not None and str(track["starting_capital"]) in ("0", "0.0")
    evt = store.row("SELECT payload FROM events WHERE kind = 'zero_capital_track_opened' AND ref_id = ?", (vid,))
    assert evt is not None and json.loads(evt["payload"])["origin"] == "rejects"
    # Idempotent: re-running the link never double-opens (the row already carries the version).
    assert link_and_open_rejects_tracks(store, "run-1", {"close_a": vid}) == 0


def test_open_zero_capital_track_is_idempotent_per_version(tmp_path):
    store = _store(tmp_path)
    vid = persist_explore_version(store, seed_breakout_spec())
    assert open_zero_capital_track(store, vid, origin="rejects").opened is True
    # A version that already has a track is not re-opened (idempotent — never resets a clock or duplicates a row).
    second = open_zero_capital_track(store, vid, origin="rejects")
    assert second.opened is False and second.reason == "track_exists"
    assert len(store.rows("SELECT 1 FROM tracks WHERE strategy_version_id = ?", (vid,))) == 1
