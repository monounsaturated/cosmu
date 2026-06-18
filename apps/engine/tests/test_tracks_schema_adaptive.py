# Schema-adaptive BRUT per-cell `tracks` access (PR #324 blockers A + B).
#
# BLOCKER A — un-migrated-prod crash. The brut spine reads/writes tracks.symbol/tracks.venue_id at four sites
# (master/portfolio.mark_to_market, orchestrator/loop._update_track_returns, master/live_eligibility.paper_net_return_pct,
# master/tracks.open_paper_track). Prod `tracks` has NO such columns yet (the migration is HELD), so the cell-keyed
# SQL raised psycopg2 UndefinedColumn BEFORE any `if row is None` fallback — crashing the 4h paper-clock cron
# fleet-wide. These pin that EVERY site probes the live schema and routes to the legacy version-only SQL when the
# cell columns are absent, so the chain raises NOTHING on a pre-migration table and is byte-correct on both.
#
# BLOCKER B — legacy version-only fallback contamination. POST-migration, _ref_ids dropped the version-only fallback,
# so a fresh brut cell with no own portfolio_snapshots / track_opened series no longer INHERITS a coexisting legacy
# version-only series (another population's forward P&L / live-proof) — it reads EMPTY history (the intended
# "no history → no premature defund / no inherited proof"). These pin no-inherit when cell columns are present, and
# the migration's ref_id rewrite re-keying a legacy series to its correct cell.

from __future__ import annotations

from decimal import Decimal

import pytest

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import (
    Store,
    reset_tracks_cell_columns_cache,
    tracks_has_cell_columns,
)
from cosmu.master.live_eligibility import _ref_ids, paper_net_return_pct
from cosmu.master.portfolio import Portfolio
from cosmu.master.tracks import open_paper_track
from cosmu.orchestrator.loop import _update_track_returns
from cosmu.spine.venue import default_catalog

_NOW = "2024-01-01T00:00:00Z"
_SYM = "BTCUSDT"
_VENUE = "binance"  # the catalog venue _instrument_venue recovers from btc-usdt-binance


@pytest.fixture(autouse=True)
def _clear_schema_cache():
    """The schema probe is memoized per database_url; tests below mutate a store's schema in-process, so the memo
    must be cleared before AND after each test (a leaked True/False would leak across tests)."""
    reset_tracks_cell_columns_cache()
    yield
    reset_tracks_cell_columns_cache()


def _store(tmp_path, name: str = "schema") -> Store:
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/{name}.sqlite3",
            openrouter_api_key=None,
            gates=GateSettings(require_beat_buy_and_hold=False),
        )
    )


def _drop_cell_columns(store: Store) -> None:
    """Mutate a fresh-schema SQLite `tracks` table into the PRE-MIGRATION prod shape: no symbol/venue_id columns
    (and no cell UNIQUE index that references them). Re-probe after."""
    store.rows("DROP INDEX IF EXISTS uq_tracks_cell")
    store.rows("ALTER TABLE tracks DROP COLUMN venue_id")
    store.rows("ALTER TABLE tracks DROP COLUMN symbol")
    reset_tracks_cell_columns_cache()


def _seed_version(store: Store) -> str:
    """A minimal strategies + strategy_versions pair (the tracks FK target). Returns version_id."""
    strategy_id = store.insert("strategies", {"name": "s", "thesis": "t", "origin": "finder", "created_at": _NOW})
    return store.insert(
        "strategy_versions",
        {
            "strategy_id": strategy_id, "parent_id": None,
            "spec": {"name": "s", "rationale": "r", "universe": {"venues": [_VENUE], "asset_classes": ["crypto"],
                     "min_instruments": 1}, "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 5},
                     "entry": [], "exit": {}, "risk": {}, "param_space": {}, "direction": 1},
            "generated_code": "# t", "code_hash": "h", "params": {}, "mutation_operator": None,
            "mutation_rationale": None, "origin": "finder", "status": "paper", "created_at": _NOW,
            "killed_at": None, "kill_reason": None,
        },
    )


def _open_position(store: Store, version_id: str, qty: str = "1", avg_price: str = "30000") -> str:
    """A held sim position for the cell (instrument btc-usdt-binance), so the paper clock has something to mark.
    Returns the instrument id."""
    inst = default_catalog().instrument(_SYM, _VENUE)
    store.rows(
        "INSERT INTO positions(id, strategy_version_id, instrument_id, symbol, venue, qty, avg_price, realized_pnl, "
        "last_was_loss, updated_at) VALUES (?, ?, ?, ?, 'sim', ?, ?, '0', 0, ?)",
        (f"{version_id}:sim:{inst.id}", version_id, inst.id, _SYM, qty, avg_price, _NOW),
    )
    return inst.id


def _cell_resolver(catalog):
    def _r(p):  # noqa: ANN001 — PositionView
        if p.strategy_version_id is None:
            return None
        inst = next((i for i in catalog.instruments if i.id == p.instrument_id), None)
        venue = inst.venue_id if inst else p.venue
        if venue == "sim" or not venue:
            return None
        return (p.strategy_version_id, p.symbol, venue)
    return _r


def _run_paper_clock(store: Store, version_id: str, mark_price: str = "33000") -> dict:
    """Drive the paper-clock chain the orchestrator runs: mark_to_market (cell-aware) → _update_track_returns.
    Returns the snapshot metrics. Raises if any site hits a column the live schema lacks (Blocker A)."""
    cat = default_catalog()
    inst = cat.instrument(_SYM, _VENUE)
    portfolio = Portfolio(store, bankroll=Decimal("100000"))
    snap = portfolio.mark_to_market({inst.id: Decimal(mark_price)}, cell_resolver=_cell_resolver(cat))
    _update_track_returns(store, [(version_id, _SYM, _VENUE)])
    return snap


# ---------------------------------------------------------- BLOCKER A: both-schema paper-clock regression


@pytest.mark.parametrize("with_cell_columns", [True, False])
def test_paper_clock_chain_runs_on_both_schemas(tmp_path, with_cell_columns):
    """The FULL paper-clock chain (mark_to_market → _update_track_returns) + open_paper_track + paper_net_return_pct
    must raise NOTHING and route correctly whether the live tracks table CARRIES the cell columns (post-migration /
    fresh) or LACKS them (current prod). On main this crashed pre-migration: the cell-keyed SELECT hit a column the
    table didn't have BEFORE the `if row is None` fallback could run."""
    store = _store(tmp_path, "both")
    if not with_cell_columns:
        _drop_cell_columns(store)
    assert tracks_has_cell_columns(store) is with_cell_columns

    version_id = _seed_version(store)
    # open_paper_track (Site 4): pass the store so the insert drops the cell fields when the columns are absent.
    track_id = open_paper_track(
        store, version_id=version_id, starting_capital="10000", symbol=_SYM, venue_id=_VENUE, store=store
    )
    assert track_id
    _open_position(store, version_id)

    # mark_to_market (Site 1) + _update_track_returns (Site 2) — the cron path. Must not raise on either schema.
    snap = _run_paper_clock(store, version_id)
    assert snap["equity"] > 0

    # The track's forward return was advanced from the marked trajectory (33000 vs 30000 basis on 1 unit → +$3000
    # on a $10000 cell ≈ +30%), proving the lookup matched the right row on BOTH schemas.
    row = store.row("SELECT return_pct, equity FROM tracks WHERE strategy_version_id = ?", (version_id,))
    assert row is not None and row["return_pct"] is not None
    assert float(row["return_pct"]) > 0  # the clock advanced (not the honest 0 seed)

    # paper_net_return_pct (Site 3): cell-scoped read. Both schemas return the SAME advanced number — the cell-keyed
    # path post-migration, the version-only path pre-migration (the only track is this version's).
    pct = paper_net_return_pct(store, version_id, symbol=_SYM, venue_id=_VENUE)
    assert pct == pytest.approx(float(row["return_pct"]))


def test_open_paper_track_drops_cell_fields_pre_migration(tmp_path):
    """open_paper_track with a per-cell symbol/venue against a PRE-migration table must INSERT a version-wide row
    (cell fields dropped) instead of raising on the missing columns — the legacy shape the readers fall back to."""
    store = _store(tmp_path, "insert")
    _drop_cell_columns(store)
    version_id = _seed_version(store)
    # Must not raise even though symbol/venue_id are supplied — they are dropped because the columns are absent.
    track_id = open_paper_track(
        store, version_id=version_id, starting_capital="10000", symbol=_SYM, venue_id=_VENUE, store=store
    )
    row = store.row("SELECT * FROM tracks WHERE id = ?", (track_id,))
    assert row is not None
    assert "symbol" not in row  # the pre-migration table simply has no such column
    assert Decimal(str(row["equity"])) == Decimal("10000.00")  # born HONEST


def test_paper_net_return_pct_pre_migration_is_version_only(tmp_path):
    """Pre-migration, paper_net_return_pct must read the version-only track even when called with symbol/venue —
    the cell-keyed SQL would raise UndefinedColumn on prod."""
    store = _store(tmp_path, "pnrp")
    _drop_cell_columns(store)
    version_id = _seed_version(store)
    store.rows(
        "INSERT INTO tracks(id, strategy_version_id, starting_capital, equity, return_pct, updated_at) "
        "VALUES (?, ?, '10000', '11000', '10.0', ?)",
        (f"trk-{version_id}", version_id, _NOW),
    )
    assert paper_net_return_pct(store, version_id, symbol=_SYM, venue_id=_VENUE) == pytest.approx(10.0)


# ---------------------------------------------------------------- BLOCKER B: no inherit, migration re-key


def test_ref_ids_drops_version_fallback_post_migration(tmp_path):
    """POST-migration (cell columns live): a cell-scoped lookup keys STRICTLY by the cell ref_id — NO version-only
    candidate. PRE-migration: it keys by version only (the only shape that exists). A version-wide call (no
    symbol/venue) always collapses to the version key."""
    store = _store(tmp_path, "refids")
    # post-migration (fresh schema has the columns)
    assert _ref_ids(store, "v1", _SYM, _VENUE) == (f"v1:{_SYM}:{_VENUE}",)
    assert _ref_ids(store, "v1", None, None) == ("v1",)
    # pre-migration
    _drop_cell_columns(store)
    assert _ref_ids(store, "v1", _SYM, _VENUE) == ("v1",)


def test_fresh_cell_does_not_inherit_legacy_version_series_post_migration(tmp_path):
    """Blocker B core: a fresh brut cell with NO own snapshots must NOT inherit a coexisting LEGACY version-only
    scope='track' series as its own forward P&L. With cell columns live, paper_net_return_pct + the snapshot reader
    return the cell's own (empty → 0 / 0%) evidence, never the legacy version-only series."""
    store = _store(tmp_path, "noinherit")
    assert tracks_has_cell_columns(store)
    version_id = _seed_version(store)

    # A coexisting LEGACY version-only forward series + version-wide track (the shape prod has 21 of).
    store.rows(
        "INSERT INTO tracks(id, strategy_version_id, starting_capital, equity, return_pct, updated_at) "
        "VALUES (?, ?, '10000', '15000', '50.0', ?)",
        (f"legacy-{version_id}", version_id, _NOW),
    )
    for i, eq in enumerate(("10000", "12000", "15000")):
        store.insert("portfolio_snapshots", {
            "scope": "track", "ref_id": version_id, "ts": f"2024-01-0{i + 1}T00:00:00Z",
            "equity": eq, "cash": "0", "positions_value": eq, "pnl": "0", "drawdown": "0",
        })

    # The fresh CELL (no own track row, no own cell-keyed snapshots) must read EMPTY — never the legacy +50%.
    from cosmu.master.drift import track_return_series
    from cosmu.master.live_eligibility import forward_daily_returns

    assert paper_net_return_pct(store, version_id, symbol=_SYM, venue_id=_VENUE) == 0.0
    assert forward_daily_returns(store, version_id, symbol=_SYM, venue_id=_VENUE) == []
    assert track_return_series(store, version_id, symbol=_SYM, venue_id=_VENUE) == []
    # The version-WIDE read still resolves the legacy series (back-compat for version-only callers).
    assert paper_net_return_pct(store, version_id) == pytest.approx(50.0)
    assert track_return_series(store, version_id) != []


def test_migration_rewrite_assigns_legacy_series_to_its_cell(tmp_path):
    """The migration's step-5/6 re-key: a legacy version-only scope='track' snapshot series (and its track_opened
    event) must be re-keyed to the cell ref_id `<version>:<symbol>:<venue>` once tracks.symbol/venue_id are
    backfilled, so each legacy cell keeps its OWN forward history under the cell key the readers use post-migration.
    SQLite stand-in for the Postgres UPDATE...FROM (same shape: ref_id = version || ':' || symbol || ':' || venue)."""
    store = _store(tmp_path, "rewrite")  # fresh schema already has the cell columns
    version_id = _seed_version(store)
    cell_ref = f"{version_id}:{_SYM}:{_VENUE}"

    # Backfilled cell track (the post-step-2 state) + a LEGACY version-only forward series + track_opened event.
    store.rows(
        "INSERT INTO tracks(id, strategy_version_id, symbol, venue_id, starting_capital, equity, return_pct, "
        "updated_at) VALUES (?, ?, ?, ?, '10000', '14000', '40.0', ?)",
        (f"trk-{version_id}", version_id, _SYM, _VENUE, _NOW),
    )
    store.insert("portfolio_snapshots", {
        "scope": "track", "ref_id": version_id, "ts": _NOW,
        "equity": "14000", "cash": "0", "positions_value": "14000", "pnl": "0", "drawdown": "0",
    })
    store.append_event(actor="master", kind="track_opened", ref_type="strategy_version", ref_id=version_id,
                       payload={"proven_regimes": ["bull"]})

    # Apply the migration's re-key (the exact UPDATE shape from the held .sql, SQLite-flavoured).
    store.rows(
        "UPDATE portfolio_snapshots SET ref_id = (SELECT t.strategy_version_id || ':' || t.symbol || ':' || "
        "t.venue_id FROM tracks t WHERE t.strategy_version_id = portfolio_snapshots.ref_id AND t.symbol IS NOT NULL "
        "AND t.venue_id IS NOT NULL) WHERE scope = 'track' AND EXISTS (SELECT 1 FROM tracks t WHERE "
        "t.strategy_version_id = portfolio_snapshots.ref_id AND t.symbol IS NOT NULL AND t.venue_id IS NOT NULL)"
    )
    store.rows(
        "UPDATE events SET ref_id = (SELECT t.strategy_version_id || ':' || t.symbol || ':' || t.venue_id FROM "
        "tracks t WHERE t.strategy_version_id = events.ref_id AND t.symbol IS NOT NULL AND t.venue_id IS NOT NULL) "
        "WHERE kind = 'track_opened' AND EXISTS (SELECT 1 FROM tracks t WHERE t.strategy_version_id = events.ref_id "
        "AND t.symbol IS NOT NULL AND t.venue_id IS NOT NULL)"
    )

    # The re-keyed series now belongs to the CELL: the cell-scoped readers find it under the cell key.
    snap = store.row("SELECT ref_id FROM portfolio_snapshots WHERE scope = 'track'")
    assert snap["ref_id"] == cell_ref
    ev = store.row("SELECT ref_id FROM events WHERE kind = 'track_opened'")
    assert ev["ref_id"] == cell_ref

    from cosmu.master.live_eligibility import forward_daily_returns, proven_regimes_for
    # The cell now reads ITS forward series + proven-regime passport (the re-keyed legacy data).
    assert "bull" in proven_regimes_for(store, version_id, symbol=_SYM, venue_id=_VENUE)
    # one snapshot → no pairwise return yet, but the lookup resolves the right ref (non-crash, cell-keyed)
    assert forward_daily_returns(store, version_id, symbol=_SYM, venue_id=_VENUE) == []
