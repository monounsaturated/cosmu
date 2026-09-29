# The clean real-data cutover: reset_sim_state purges synthetic-era discovery + paper rows but PRESERVES
# config (venues/instruments), the live interlocks (live_toggle/caps), and real ingested alt-data.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.reset import sim_state_counts, reset_sim_state


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/reset.sqlite3", openrouter_api_key=None))


def test_reset_purges_sim_state_but_preserves_config_and_live_toggle(tmp_path):
    store = _store(tmp_path)
    # Seed: a strategy version + track + position + snapshot (discovery/paper state), and config we must keep.
    sid = store.insert("strategies", {"name": "s1", "thesis": "t", "origin": "seed", "created_at": "2026-01-01"})
    vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "seed", "status": "paper", "created_at": "2026-01-01"})
    store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "100000", "equity": "100000", "return_pct": "0", "updated_at": "2026-01-01"})
    store.insert("positions", {"strategy_version_id": vid, "instrument_id": "i1", "symbol": "BTCUSDT", "venue": "binance", "qty": "1", "avg_price": "100", "realized_pnl": "0", "last_was_loss": 0, "updated_at": "2026-01-01"})
    store.insert("portfolio_snapshots", {"scope": "pool", "ref_id": "global", "ts": "2026-01-01", "equity": "83196", "cash": "0", "positions_value": "0", "pnl": "-16804", "drawdown": "0.16"})
    # live_toggle row exists from migrate() (the money interlock) — it must survive the reset.

    counts = sim_state_counts(store)
    assert counts["strategy_versions"] == 1 and counts["positions"] == 1 and counts["portfolio_snapshots"] == 1

    reset_sim_state(store)

    # Paper/discovery state gone.
    assert store.row("SELECT COUNT(*) AS n FROM strategy_versions")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM positions")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM portfolio_snapshots")["n"] == 0
    # The money interlock (live_toggle) is never touched by the reset.
    assert store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")["enabled"] == 0
    # The reset itself is audited (an event survives because it is written inside the same purge transaction,
    # AFTER the events DELETE).
    assert store.row("SELECT COUNT(*) AS n FROM events WHERE kind = 'sim_state_reset'")["n"] == 1
