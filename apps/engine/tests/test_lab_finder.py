# The Strategy Finder: grid-search a spec's param space → screen each variant deterministically → rank by
# profit_factor (displayed) while the Gate + FDR + one-shot holdout decide promotion (no top-of-leaderboard
# picking) → every variant counts as a trial → winners persisted to the config library (origin='finder').

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import PAPER_MIN_DAYS, Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder, VariantResult, build_grid
from cosmu.master.live_eligibility import (
    live_eligibility_verdict,
    paper_clock_origin,
    proven_regimes_for,
)
from cosmu.master.promotion import promotion_record
from cosmu.master.scorer import BacktestMetrics
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec


class _FixtureBars:
    # Small, fast offline market: 2 catalog symbols x ~280 edge-bearing bars (enough for the screen's 80-bar
    # floor + holdout split) so finder grids stay quick in CI.
    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/finder.sqlite3", openrouter_api_key=None))


def _finder(tmp_path) -> StrategyFinder:
    store = _store(tmp_path)
    return StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())


def test_build_grid_spans_space_and_is_bounded():
    spec = seed_orb_fvg_spec()
    grid = build_grid(spec, max_variants=16)
    assert 1 <= len(grid) <= 16
    # every variant resolves every param in the space (no missing params → compiler would reject)
    for v in grid:
        assert set(v.params) == set(spec.param_space)
    # config tags are stable + unique per param combination
    tags = [v.config_tag for v in grid]
    assert len(set(tags)) == len(tags)


def test_finder_screens_ranks_by_profit_factor_and_registers_no_trials(tmp_path):
    finder = _finder(tmp_path)
    report = finder.find(seed_orb_fvg_spec(), max_variants=10)
    assert report.screened > 0
    # leaderboard is the gate-passers sorted by profit_factor descending (displayed secondary metric)
    pfs = [r.profit_factor for r in report.leaderboard]
    assert pfs == sorted(pfs, reverse=True)
    # BRUT contract: a per-combo cell is NOT part of any cross-combo family, so the brut finder registers NO
    # global trials (the per-combo param-grid count rides on metrics.trials_counted, not the ledger). The pooled
    # FDR/cross-cell deflation that register_trial fed is gone — each cell is judged on its OWN data.
    n_trials = finder.store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"]
    assert n_trials == 0


def test_screen_charges_thin_book_venue_depth_not_global_default(tmp_path, monkeypatch):
    """The screen must price each variant at its VENUE's market depth, not the global DEFAULT_SLIPPAGE_BPS=5 /
    DEFAULT_IMPACT_BPS=50. A thin-book venue (Polymarket 30/150) is the adversarial case: before the fix the
    backtest silently fell back to 5/50, screening it ~6x too cheap on impact. This spies on the backtest the
    screen invokes and asserts the venue's OWN depth is what gets charged (and that it is NOT the global 5/50)."""
    import cosmu.lab.finder as finder_mod

    finder = _finder(tmp_path)
    spec = seed_orb_fvg_spec()
    variant = build_grid(spec, max_variants=4)[0]
    market = {sym: _FixtureBars().fetch_bars(sym, spec.horizon.bar_size, limit=280) for sym in ("BTCUSDT",)}

    thin = default_catalog().venue("polymarket")
    assert (thin.slippage_bps, thin.impact_bps) == (Decimal("30"), Decimal("150")), "fixture venue moved"

    captured: dict[str, Decimal] = {}
    real_backtest = finder_mod.run_strategy_backtest_detailed

    def _spy(*args, **kwargs):
        captured["slippage_bps"] = kwargs.get("slippage_bps")
        captured["impact_bps"] = kwargs.get("impact_bps")
        return real_backtest(*args, **kwargs)

    monkeypatch.setattr(finder_mod, "run_strategy_backtest_detailed", _spy)

    out = finder._screen(spec, variant, market, thin, None, grid_size=4)
    assert out is not None, "fixture variant must screen (valid grid point)"

    # The screen charged the VENUE's depth, not the global fallback.
    assert captured["slippage_bps"] == thin.slippage_bps == Decimal("30")
    assert captured["impact_bps"] == thin.impact_bps == Decimal("150")
    # And explicitly NOT the global default the screen used to fall back to.
    from cosmu.data.backtest import DEFAULT_IMPACT_BPS, DEFAULT_SLIPPAGE_BPS

    assert captured["slippage_bps"] != DEFAULT_SLIPPAGE_BPS  # was the silent 5bps fallback
    assert captured["impact_bps"] != DEFAULT_IMPACT_BPS      # was the silent 50bps fallback


def test_screen_records_venue_depth_charged_on_backtest_row(tmp_path):
    """The persisted backtest cost row must record the EXACT depth charged (the promotion freeze pins it so live
    can detect a venue repricing), never the global DEFAULT_*. A Binance crypto spec resolves to Binance depth
    (5/40) — note impact 40 != the global 50, so this row proves the venue value flows through to persistence."""
    finder = _finder(tmp_path)
    finder.find(seed_orb_fvg_spec(), max_variants=8)

    binance = default_catalog().venue("binance")
    rows = finder.store.rows(
        "SELECT slippage_bps, impact_bps, venue_id FROM backtests WHERE kind = 'screen'"
    )
    assert rows, "the screen must persist at least one backtest cost row"
    for r in rows:
        assert r["venue_id"] == "binance"
        # Recorded the venue's OWN depth, not the global default (impact 40 is the tell: != global 50).
        assert Decimal(str(r["slippage_bps"])) == binance.slippage_bps == Decimal("5")
        assert Decimal(str(r["impact_bps"])) == binance.impact_bps == Decimal("40")


def test_finder_persists_config_library_and_holdout_before_promotion(tmp_path):
    finder = _finder(tmp_path)
    report = finder.find(seed_orb_fvg_spec(), max_variants=10)
    # config library: finder-origin versions persisted, tagged with a config_tag in params
    versions = finder.store.rows("SELECT params FROM strategy_versions WHERE origin = 'finder'")
    assert versions and all('"config_tag"' in v["params"] for v in versions)
    # promotion requires the one-shot holdout, never raw in-sample PF order
    assert all(s.promoted and s.holdout_passed for s in report.survivors)
    # one-shot holdout ledger recorded for gate-passers (cannot silently re-pick)
    if report.gate_passed:
        assert finder.store.rows("SELECT COUNT(*) AS n FROM holdout_ledger")[0]["n"] >= 1


def _bull_bars(n: int = 80) -> list[Bar]:
    """A steadily-rising reference series whose current regime classifies 'bull' (mirrors the live-eligibility
    gate's _UP fixture), so a survivor with a 'bull' proven passport is in-regime."""
    start = datetime(2023, 1, 1, tzinfo=UTC)
    price = 100.0
    out: list[Bar] = []
    for i in range(n):
        open_ = price
        price = price * 1.01
        out.append(
            Bar(
                ts=start + timedelta(days=i),
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(price * 1.01, 6))),
                low=Decimal(str(round(open_ * 0.99, 6))),
                close=Decimal(str(round(price, 6))),
                volume=Decimal("1000000"),
            )
        )
    return out


def test_finder_promotion_opens_per_cell_forward_clock_and_is_live_eligible(tmp_path):
    # BRUT per-cell: promotion writes a CELL-keyed `track_opened` event (clock origin + this cell's own
    # proven-regime passport) so master/live_eligibility matures the CELL on its OWN forward evidence. Drive the
    # persist path directly with a holdout-passing cell on BTCUSDT@binance, then prove the cell clock starts and
    # the cell becomes live-eligible — scoped to (version, symbol, venue), never a sibling cell.
    from cosmu.lab.finder import CellResult
    from cosmu.master.live_eligibility import cell_id

    finder = _finder(tmp_path)
    spec = seed_orb_fvg_spec()
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    cell_metrics = BacktestMetrics(
        oos_return=Decimal("0.05"), sharpe=Decimal("1.5"), sortino=Decimal("2.0"),
        max_drawdown=Decimal("0.10"), win_rate=Decimal("0.6"), num_trades=40,
        regime_returns={"bull": 0.05, "bear": -0.02},  # this cell proved positive net edge in bull only
    )
    cell = CellResult(
        symbol="BTCUSDT", venue_id="binance", metrics=cell_metrics, deflated_sharpe=0.96,
        trades=40, passed=True, holdout_passed=True,
    )
    survivor = VariantResult(
        config_tag="cfg-promoted", code_hash=compiled.code_hash, metrics=cell_metrics,
        deflated_sharpe=0.96, profit_factor=2.0, net_profit=0.04, gate_passed=True, reasons=[],
        fitted_params=fitted, promoted=True, holdout_passed=True,
        per_symbol={"BTCUSDT": {"return": 0.05, "sharpe": 1.5, "max_drawdown": 0.10, "trades": 40.0}},
        cells={"BTCUSDT": cell},
    )
    venue = default_catalog().venue_for(spec.universe.venues)
    finder._persist(spec, [survivor], {}, venue)
    vid = survivor.version_id
    assert vid is not None

    # The CELL paper clock opened with the cell's own proven-regime passport (cell-keyed track_opened).
    assert paper_clock_origin(finder.store, vid, symbol="BTCUSDT", venue_id="binance") is not None
    assert proven_regimes_for(finder.store, vid, symbol="BTCUSDT", venue_id="binance") == {"bull"}
    # One per-cell track row carrying the cell columns.
    tr = finder.store.row("SELECT symbol, venue_id FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert tr["symbol"] == "BTCUSDT" and tr["venue_id"] == "binance"
    # The backtest_symbols cell row carries the BRUT pass verdict (the funder fans out tracks on 'pass' cells).
    bs = finder.store.row("SELECT verdict FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'", (vid,))
    assert bs["verdict"] == "pass"

    # Promotion FROZE the live-replication record (single source of truth live reads).
    frozen = promotion_record(finder.store, vid)
    assert frozen is not None
    numeric = {k: v for k, v in frozen["params"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    assert frozen["params_hash"] and numeric == fitted
    assert venue.id in frozen["fee_model_snapshot"]
    assert frozen["fee_model_snapshot"][venue.id]["taker_bps"] == float(venue.taker_fee_bps)
    assert frozen["feature_registry_version"]
    # The pre-existing finder_survivor event is still written (cell-keyed now).
    survivor_events = finder.store.rows(
        "SELECT COUNT(*) AS n FROM events WHERE kind = 'finder_survivor' AND ref_id = ?",
        (cell_id(vid, "BTCUSDT", "binance"),),
    )
    assert survivor_events[0]["n"] == 1

    # Before the window matures, the cell clock has barely started → not forward-ready → not armable.
    now = datetime.now(tz=UTC)
    fresh = live_eligibility_verdict(finder.store, vid, _bull_bars(), now=now, symbol="BTCUSDT", venue_id="binance")
    assert fresh.forward_ready is False
    assert fresh.eligible is False

    # HONEST GATE: maturity alone is not enough — the cell track is born with ZERO forward P&L.
    matured_flat = live_eligibility_verdict(
        finder.store, vid, _bull_bars(), now=now + timedelta(days=PAPER_MIN_DAYS + 5), symbol="BTCUSDT", venue_id="binance"
    )
    assert matured_flat.paper_age_days >= PAPER_MIN_DAYS
    assert matured_flat.forward_ready is False
    assert matured_flat.eligible is False

    # Only once REAL net-positive forward P&L accrues on THIS cell (tracks.return_pct + the cell-keyed scope='track'
    # snapshot trajectory) AND the cell has actually TRADED forward (>= 1 real paper fill on its instrument) does the
    # matured, proven-regime cell become forward-ready + armable.
    finder.store.rows("UPDATE tracks SET return_pct = ? WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'", ("3.5", vid))
    instrument_id = default_catalog().instrument("BTCUSDT", "binance").id
    finder.store.rows(
        "INSERT INTO runs(id, strategy_version_id, mode, venue_id, seed, started_at, status) "
        "VALUES ('r-fp', ?, 'sandbox', 'binance', 1, ?, 'completed')", (vid, now.isoformat()))
    finder.store.rows(
        "INSERT INTO executions(id, run_id, strategy_version_id, instrument_id, venue_id, side, qty, price, fee, "
        "slippage, order_type, is_paper, ts, fill_log) "
        "VALUES ('e-fp', 'r-fp', ?, ?, 'binance', 'buy', '1', '100', '0.1', '0', 'market', 1, ?, '{}')",
        (vid, instrument_id, now.isoformat()))
    from conftest import seed_track_snapshots
    seed_track_snapshots(finder.store, cell_id(vid, "BTCUSDT", "binance"), obs=25, now=now)
    matured = live_eligibility_verdict(
        finder.store, vid, _bull_bars(), now=now + timedelta(days=PAPER_MIN_DAYS + 5), symbol="BTCUSDT", venue_id="binance"
    )
    assert matured.paper_age_days >= PAPER_MIN_DAYS
    assert matured.forward_ready is True
    assert matured.regime_eligible is True
    assert matured.eligible is True


def test_finder_is_idempotent(tmp_path):
    finder = _finder(tmp_path)
    finder.find(seed_orb_fvg_spec(), max_variants=8)
    before = finder.store.rows("SELECT COUNT(*) AS n FROM strategy_versions WHERE origin = 'finder'")[0]["n"]
    finder.find(seed_orb_fvg_spec(), max_variants=8)  # same grid → same code_hashes → no new versions
    after = finder.store.rows("SELECT COUNT(*) AS n FROM strategy_versions WHERE origin = 'finder'")[0]["n"]
    assert after == before


def test_screen_persists_per_cell_rows_with_brut_verdict(tmp_path):
    """The screen persists a backtest_symbols ROW per CELL (backtest × symbol × venue) — the queryable per-cell
    truth (1 strat × 1 symbol × 1 venue × 1 result, venue_id = the fee axis), never a pooled mean. Each row carries
    the BRUT per-cell verdict: 'pass' iff the cell cleared the gate on its OWN data, else its own kill reason — the
    funder fans out a paper track on every 'pass' cell. Queryable / outlier-sortable per version."""
    finder = _finder(tmp_path)
    finder.find(seed_orb_fvg_spec(), max_variants=8)
    rows = finder.store.rows("SELECT symbol, venue_id, return_pct, verdict, strategy_version_id FROM backtest_symbols")
    assert rows, "the screen must persist per-cell rows"
    for r in rows:
        assert r["venue_id"] == "binance"
        assert r["symbol"]  # a real symbol, never a pooled blob
        # The verdict is the BRUT cell pass/fail — 'pass' or a kill-reason string, never a sibling-compared label.
        assert r["verdict"] is None or isinstance(r["verdict"], str)
    vid = rows[0]["strategy_version_id"]
    ranked = finder.store.rows(
        "SELECT symbol FROM backtest_symbols WHERE strategy_version_id = ? ORDER BY return_pct DESC", (vid,)
    )
    assert len(ranked) >= 1  # queryable + outlier-sortable per version
