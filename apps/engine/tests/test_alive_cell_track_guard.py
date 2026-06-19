# Cross-version idempotency guard for the generous-paper WATCH / per-cell track lanes.
#
# THE BUG: the evolution loop (and the finder sweep) mint a BRAND-NEW strategies + strategy_versions row on every
# pass, then open one paper track per passing/near-miss cell. The per-cell UNIQUE(strategy_version_id, symbol,
# venue_id) dedupes WITHIN a version but never across the fresh versions each run creates — so a strategy that keeps
# clearing the watch lane accumulates one duplicate track per pass on the SAME (strategy × symbol × venue) cell
# (prod showed "DeFi-flow risk appetite" with 51 tracks across 18 versions on 3 cells). The stable cross-run
# identity is the strategy NAME, so master/tracks.alive_cell_track_exists keys the slot on strategies.name.
#
# These pin: a clean slot opens (returns False / first open allowed); a SECOND version of the SAME-NAME strategy is
# suppressed for an already-tracked cell; a KILLED version frees the slot; pre-migration (no cell columns) defers to
# the per-version guard; and version-wide (no symbol/venue) never matches.

from __future__ import annotations

import pytest

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store, reset_tracks_cell_columns_cache, tracks_has_cell_columns
from cosmu.master.tracks import alive_cell_track_exists, open_paper_track

_NOW = "2024-01-01T00:00:00Z"
_SYM = "SOL/USDT"
_VENUE = "binance"


@pytest.fixture(autouse=True)
def _clear_schema_cache():
    reset_tracks_cell_columns_cache()
    yield
    reset_tracks_cell_columns_cache()


def _store(tmp_path, name: str = "guard") -> Store:
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/{name}.sqlite3",
            openrouter_api_key=None,
            gates=GateSettings(require_beat_buy_and_hold=False),
        )
    )


def _drop_cell_columns(store: Store) -> None:
    store.rows("DROP INDEX IF EXISTS uq_tracks_cell")
    store.rows("ALTER TABLE tracks DROP COLUMN venue_id")
    store.rows("ALTER TABLE tracks DROP COLUMN symbol")
    reset_tracks_cell_columns_cache()


def _seed_version(store: Store, name: str, status: str = "screened") -> str:
    """A strategies + strategy_versions pair under `name`. Each call inserts a FRESH strategies row — the exact
    shape the loop produces every cron pass (a new strategy_id per run for the same human-facing name)."""
    strategy_id = store.insert("strategies", {"name": name, "thesis": "t", "origin": "seed", "created_at": _NOW})
    return store.insert(
        "strategy_versions",
        {
            "strategy_id": strategy_id, "parent_id": None,
            "spec": {"name": name, "rationale": "r", "universe": {"venues": [_VENUE], "asset_classes": ["crypto"],
                     "min_instruments": 1}, "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 5},
                     "entry": [], "exit": {}, "risk": {}, "param_space": {}, "direction": 1},
            "generated_code": "# t", "code_hash": f"h-{status}-{store.rows('SELECT count(*) c FROM strategy_versions')[0]['c']}",
            "params": {}, "mutation_operator": None, "mutation_rationale": None, "origin": "seed",
            "status": status, "created_at": _NOW, "killed_at": None, "kill_reason": None,
        },
    )


def test_clean_slot_allows_first_open(tmp_path):
    """No track yet for the cell → the guard returns False (a first open is always allowed)."""
    store = _store(tmp_path, "clean")
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id=_VENUE) is False


def test_second_version_same_name_is_suppressed(tmp_path):
    """The core fix: version A (alive) owns the cell; a FRESH version B of the same NAME on the same cell is
    suppressed — even though B's synthetic id never collides with A's on the per-cell UNIQUE."""
    store = _store(tmp_path, "dup")
    assert tracks_has_cell_columns(store) is True
    vid_a = _seed_version(store, "DeFi-flow", status="screened")
    open_paper_track(store, version_id=vid_a, starting_capital="1000", symbol=_SYM, venue_id=_VENUE, store=store)

    # A later cron pass mints a brand-new strategy + version for the SAME name on the SAME cell.
    _vid_b = _seed_version(store, "DeFi-flow", status="screened")
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id=_VENUE) is True
    # A DIFFERENT cell of the same strategy is NOT suppressed (each cell stands alone).
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol="ETH/USDT", venue_id=_VENUE) is False
    # A DIFFERENT venue is NOT suppressed (the venue axis is part of the slot).
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id="kraken") is False
    # A DIFFERENT strategy name is NOT suppressed.
    assert alive_cell_track_exists(store, strategy_name="Other strat", symbol=_SYM, venue_id=_VENUE) is False


def test_killed_version_frees_the_slot(tmp_path):
    """A track whose ONLY owning version is killed (gate-failed / defunded / deduped) no longer occupies the slot —
    a fresh paper track for that cell is then legitimate (guard returns False)."""
    store = _store(tmp_path, "killed")
    vid = _seed_version(store, "DeFi-flow", status="killed")
    open_paper_track(store, version_id=vid, starting_capital="1000", symbol=_SYM, venue_id=_VENUE, store=store)
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id=_VENUE) is False


def test_paper_and_live_statuses_occupy_the_slot(tmp_path):
    """A funded paper / live track occupies the slot just like a screened one (any non-killed status)."""
    for status in ("paper", "live"):
        store = _store(tmp_path, f"alive-{status}")
        vid = _seed_version(store, "DeFi-flow", status=status)
        open_paper_track(store, version_id=vid, starting_capital="1000", symbol=_SYM, venue_id=_VENUE, store=store)
        assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id=_VENUE) is True


def test_version_wide_call_never_matches(tmp_path):
    """A version-wide (no symbol/venue) query carries no cell identity to dedupe on → returns False, so the
    caller's existing one-track-per-version guard stays the authority for legacy version-wide rows."""
    store = _store(tmp_path, "vwide")
    vid = _seed_version(store, "DeFi-flow", status="screened")
    open_paper_track(store, version_id=vid, starting_capital="1000", symbol=_SYM, venue_id=_VENUE, store=store)
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=None, venue_id=None) is False
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id=None) is False


def test_pre_migration_defers_to_per_version_guard(tmp_path):
    """Pre-migration (tracks lacks symbol/venue_id) there is no cell identity on the row to match — the guard
    returns False (defers to the finder/loop one-track-per-version fallback) and never references a missing column."""
    store = _store(tmp_path, "premig")
    _drop_cell_columns(store)
    assert tracks_has_cell_columns(store) is False
    vid = _seed_version(store, "DeFi-flow", status="screened")
    open_paper_track(store, version_id=vid, starting_capital="1000", symbol=_SYM, venue_id=_VENUE, store=store)
    assert alive_cell_track_exists(store, strategy_name="DeFi-flow", symbol=_SYM, venue_id=_VENUE) is False
