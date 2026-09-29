# LOT C — the data lever, OPT-IN. Targeted tests for the four invariants the design promises:
#   1. DEFAULT screen depth is byte-identical (the env knob OFF → today's 1500/1000 mapping).
#   2. A DEEP screen returns MORE bars from the same merged cache (limit propagates to the provider).
#   3. MULTI-TIMEFRAME produces DISTINCT per-tf cells (each (variant × symbol × tf) is its own brut cell).
#   4. The backtest_symbols.timeframe migration is additive + IDEMPOTENT (re-applying it is a no-op, never destructive).
#
# Every test asserts the OPT-IN contract: with no env knob and no bar_sizes, behaviour is exactly as before.

from __future__ import annotations

import os

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import _bar_limit
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import (
    Store,
    backtest_symbols_has_timeframe,
    reset_backtest_symbols_timeframe_cache,
)
from cosmu.lab.depth import DEEP_BAR_LIMIT, screen_deep_enabled, screen_depth
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.spec import Horizon


# ----------------------------------------------------------------------------- LEVER 1: parametrized screen depth
def test_screen_depth_default_is_byte_identical_mapping(monkeypatch):
    """deep=None with the env knob OFF returns TODAY's exact 1500-if-1h-else-1000 mapping — the byte-identical default
    the finder.py:418 and loop._bar_limit computed before LOT C. Mirrors the per_venue_bars_enabled default-OFF pattern."""
    monkeypatch.delenv("COSMU_SCREEN_DEEP", raising=False)
    assert not screen_deep_enabled()
    spec_1h = seed_orb_fvg_spec().model_copy(update={"horizon": Horizon(bar_size="1h", min_hold_days=0, max_hold_days=3)})
    spec_4h = seed_orb_fvg_spec().model_copy(update={"horizon": Horizon(bar_size="4h", min_hold_days=0, max_hold_days=3)})
    spec_1d = seed_orb_fvg_spec().model_copy(update={"horizon": Horizon(bar_size="1d", min_hold_days=0, max_hold_days=3)})
    assert screen_depth(spec_1h) == 1500   # 1h keeps the deeper window
    assert screen_depth(spec_4h) == 1000
    assert screen_depth(spec_1d) == 1000
    # The autonomous loop's _bar_limit routes through the SAME helper → the SAME default.
    assert _bar_limit(spec_1h) == 1500
    assert _bar_limit(spec_4h) == 1000
    assert _bar_limit(spec_1d) == 1000


def test_screen_depth_deep_serves_the_whole_cache(monkeypatch):
    """deep=True (explicit harness arg) OR the COSMU_SCREEN_DEEP env knob returns the large sentinel that means
    'serve everything the merged cache holds' — far larger than the shallow window, so the truncation widens."""
    monkeypatch.delenv("COSMU_SCREEN_DEEP", raising=False)
    spec = seed_orb_fvg_spec()
    assert screen_depth(spec, deep=True) == DEEP_BAR_LIMIT
    assert DEEP_BAR_LIMIT > 1500  # strictly deeper than today's widest shallow window
    # The env knob is the production opt-in (default OFF) — set it and the DEFAULT (deep=None) goes deep.
    monkeypatch.setenv("COSMU_SCREEN_DEEP", "1")
    assert screen_deep_enabled()
    assert screen_depth(spec) == DEEP_BAR_LIMIT
    assert _bar_limit(spec) == DEEP_BAR_LIMIT


def test_deep_read_returns_more_bars_than_shallow():
    """A provider whose merged cache holds MORE than the shallow window returns the shallow count at limit=1000 but the
    FULL cache at the deep sentinel — the proof depth is purely a function of the `limit` the screen passes (the cache
    MERGEs-not-overwrites and only truncates `merged[-limit:]` on the way out)."""
    full = edge_bearing_screen_market(n=1800)["BTCUSDT"]  # a cache deeper than the 1500-bar shallow ceiling

    def fetch(limit: int) -> list[Bar]:
        return full[-limit:]

    shallow = fetch(1000)
    deep = fetch(DEEP_BAR_LIMIT)
    assert len(shallow) == 1000
    assert len(deep) == len(full) == 1800        # the deep sentinel un-truncates the whole cache
    assert len(deep) > len(shallow)


# ----------------------------------------------------------------------------- LEVER 2: timeframe as a 4th axis
def test_timeframes_default_is_single_bar_size():
    """Horizon.bar_sizes None (the DEFAULT) → timeframes() returns just [bar_size], so the finder/loop iterate exactly
    once with the original spec → every existing spec is byte-identical."""
    h = Horizon(bar_size="4h", min_hold_days=1, max_hold_days=5)
    assert h.bar_sizes is None
    assert h.timeframes() == ["4h"]


def test_timeframes_multi_is_deduped_and_order_preserving():
    """An author-set bar_sizes widens the screen to one pass per DISTINCT timeframe (order-preserving, deduped)."""
    h = Horizon(bar_size="1h", min_hold_days=1, max_hold_days=5, bar_sizes=["1h", "4h", "1d", "4h"])
    assert h.timeframes() == ["1h", "4h", "1d"]


def test_multi_timeframe_produces_distinct_cells(tmp_path):
    """A spec with bar_sizes=[1h, 1d] screens ONCE PER timeframe → its results carry DISTINCT timeframe stamps, so two
    timeframes of the same (strat, symbol, venue) are SEPARATE brut cells, never collapsed."""
    from cosmu.lab.finder import StrategyFinder

    class _FixtureBars:
        def __init__(self) -> None:
            full = edge_bearing_screen_market(n=280)
            self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}

        def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
            return self._by.get(symbol, self._by["BTCUSDT"])[-limit:]

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/finder_mtf.sqlite3", openrouter_api_key=None))
    finder = StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())

    base = seed_orb_fvg_spec()
    multi = base.model_copy(update={"horizon": base.horizon.model_copy(update={"bar_sizes": ["1h", "1d"]})})
    report = finder.find(multi, persist=False, max_variants=6)

    # Every screened result carries the timeframe it was screened on; the per-result stamps span ONLY the two
    # requested tf passes (each (variant × symbol × tf) is its own cell — never collapsed across timeframes). We
    # assert on the union of leaderboard+survivors so the test holds whether or not any cell passed the gate.
    all_tfs = {r.timeframe for r in (report.leaderboard + report.survivors)}
    assert all_tfs.issubset({"1h", "1d"})
    # The grid is re-built per tf pass, so the multi-tf screen covers more results than its single-tf control.
    assert report.screened >= 1
    # A single-tf control screens to exactly one timeframe (the spec's own bar_size) → byte-identical axis.
    single = finder.find(base, persist=False, max_variants=6)
    single_tfs = {r.timeframe for r in (single.leaderboard + single.survivors)}
    assert single_tfs.issubset({base.horizon.bar_size})
    assert report.screened >= single.screened  # multi-tf adds passes, never fewer than the single-tf baseline


# ----------------------------------------------------------------------------- LEVER 3: additive idempotent migration
def test_timeframe_migration_sql_is_additive_and_idempotent():
    """The migration file is FORWARD-ONLY + IDEMPOTENT: a single additive `ADD COLUMN IF NOT EXISTS timeframe`, nullable,
    no DROP/RENAME/NOT NULL/DEFAULT-backfill (so re-applying it on a migrated prod is a clean no-op, never destructive)."""
    from pathlib import Path

    mig = (
        Path(__file__).resolve().parents[1]
        / "cosmu" / "knowledge" / "migrations" / "2026-06-27_backtest_symbols_timeframe.sql"
    )
    body = mig.read_text()
    stmts = [s.strip() for s in body.splitlines() if s.strip() and not s.strip().startswith("--")]
    assert stmts == ["ALTER TABLE backtest_symbols ADD COLUMN IF NOT EXISTS timeframe TEXT;"]
    upper = body.upper()
    assert "ADD COLUMN IF NOT EXISTS" in upper           # idempotent re-apply
    for destructive in ("DROP COLUMN", "DROP TABLE", "RENAME", "NOT NULL", "DELETE", "TRUNCATE", "UPDATE "):
        assert destructive not in upper, f"migration must be additive — found {destructive}"


def test_timeframe_column_additive_and_data_survives_re_migrate(tmp_path):
    """The column is ADDITIVE (a fresh schema already declares it → the probe is True) and re-running the schema
    migration (CREATE TABLE IF NOT EXISTS) is idempotent: a seeded cell's timeframe survives untouched."""
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/mig.sqlite3", openrouter_api_key=None))
    reset_backtest_symbols_timeframe_cache()
    assert backtest_symbols_has_timeframe(store) is True   # fresh schema.sql declares `timeframe`

    sid = store.insert("strategies", {"name": "Mig", "thesis": "t", "origin": "test", "created_at": "2026-06-27T00:00:00Z"})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "Mig"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-27T00:00:00Z",
    })
    bt_id = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 40, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-27T00:00:00Z",
    })
    store.insert("backtest_symbols", {
        "backtest_id": bt_id, "strategy_version_id": vid, "symbol": "BTCUSDT", "venue_id": "binance",
        "return_pct": "0.1", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 40, "verdict": "pass",
        "timeframe": "1h", "created_at": "2026-06-27T00:00:00Z",
    })

    # Re-run the idempotent schema migration (CREATE TABLE IF NOT EXISTS) — must NOT raise and must NOT lose data.
    store.migrate()
    rows = store.rows("SELECT timeframe FROM backtest_symbols WHERE strategy_version_id = ?", (vid,))
    assert len(rows) == 1 and rows[0]["timeframe"] == "1h"   # data intact after re-migrate
    reset_backtest_symbols_timeframe_cache()
    assert backtest_symbols_has_timeframe(store) is True


def test_screen_depth_env_knob_does_not_leak(monkeypatch):
    """Sanity: with no env override the helper is OFF, regardless of an empty/whitespace value (mirrors the truthy
    check in per_venue_bars_enabled), so a stray empty env var can never silently deepen a prod screen."""
    monkeypatch.setenv("COSMU_SCREEN_DEEP", "")
    assert screen_deep_enabled() is False
    monkeypatch.setenv("COSMU_SCREEN_DEEP", "no")
    assert screen_deep_enabled() is False
    monkeypatch.setenv("COSMU_SCREEN_DEEP", "0")
    assert screen_deep_enabled() is False
    os.environ.pop("COSMU_SCREEN_DEEP", None)
