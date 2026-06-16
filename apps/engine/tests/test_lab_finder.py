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
    paper_clock_origin,
    live_eligibility_verdict,
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


def test_finder_screens_ranks_by_profit_factor_and_counts_trials(tmp_path):
    finder = _finder(tmp_path)
    report = finder.find(seed_orb_fvg_spec(), max_variants=10)
    assert report.screened > 0
    # leaderboard is the gate-passers sorted by profit_factor descending (displayed secondary metric)
    pfs = [r.profit_factor for r in report.leaderboard]
    assert pfs == sorted(pfs, reverse=True)
    # EVERY screened variant was registered as a trial (deflation validity) — choke point, no bypass
    n_trials = finder.store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"]
    assert n_trials == report.screened


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


def test_finder_promotion_opens_forward_clock_and_is_live_eligible(tmp_path):
    # A finder survivor must reach the SAME paper clock as an evolution survivor: promotion now writes a
    # `track_opened` event (clock origin + proven-regime passport) so master/live_eligibility can mature it. Before
    # this, finder survivors had paper_clock_origin=None → paper_age_days 0 forever → never forward_ready → never
    # armable (paper is HARD-enforced on the live-arm path), silently stranding every finder survivor. The
    # fixture grid promotes nothing through the full Gate+holdout, so drive the promotion-persist path directly with a
    # net-positive, holdout-passing survivor, then prove the clock starts and the survivor becomes live-eligible.
    finder = _finder(tmp_path)
    spec = seed_orb_fvg_spec()
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    metrics = BacktestMetrics(
        oos_return=Decimal("0.05"), sharpe=Decimal("1.5"), sortino=Decimal("2.0"),
        max_drawdown=Decimal("0.10"), win_rate=Decimal("0.6"), num_trades=40,
        regime_returns={"bull": 0.05, "bear": -0.02},  # proved positive net edge in bull only
    )
    survivor = VariantResult(
        config_tag="cfg-promoted", code_hash=compiled.code_hash, metrics=metrics,
        deflated_sharpe=0.9, profit_factor=2.0, net_profit=0.04, gate_passed=True, reasons=[],
        fitted_params=fitted, promoted=True, holdout_passed=True,
    )
    venue = default_catalog().venue_for(spec.universe.venues)
    finder._persist(spec, [survivor], {}, venue)
    vid = survivor.version_id
    assert vid is not None

    # Promotion opened the paper clock and recorded the proven-regime passport (only the net-positive regime).
    assert paper_clock_origin(finder.store, vid) is not None
    assert proven_regimes_for(finder.store, vid) == {"bull"}

    # Promotion also FROZE the live-replication record: frozen params + hash, the venue fee model the edge was
    # priced against, the registry version, and the proven regimes — the single source of truth live reads.
    frozen = promotion_record(finder.store, vid)
    assert frozen is not None
    # The numeric knobs live actually uses are frozen verbatim (config_tag is a label, dropped before fitting).
    numeric = {k: v for k, v in frozen["params"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    assert frozen["params_hash"] and numeric == fitted
    assert venue.id in frozen["fee_model_snapshot"]
    assert frozen["fee_model_snapshot"][venue.id]["taker_bps"] == float(venue.taker_fee_bps)
    assert frozen["proven_regimes"] == ["bull"]
    assert frozen["feature_registry_version"]
    # The screen backtest recorded the cost assumptions it was scored under (so live can detect a repricing).
    bt = finder.store.row("SELECT venue_id, fee_bps FROM backtests WHERE strategy_version_id = ? AND kind = 'screen'", (vid,))
    assert bt["venue_id"] == venue.id
    assert float(bt["fee_bps"]) == float(venue.taker_fee_bps)
    # The pre-existing finder_survivor event is still written (track_opened is ADDED, not a replacement).
    survivor_events = finder.store.rows(
        "SELECT COUNT(*) AS n FROM events WHERE kind = 'finder_survivor' AND ref_id = ?", (vid,)
    )
    assert survivor_events[0]["n"] == 1

    # Before the window matures, the clock has barely started → not yet forward-ready → not armable.
    now = datetime.now(tz=UTC)
    fresh = live_eligibility_verdict(finder.store, vid, _bull_bars(), now=now)
    assert fresh.forward_ready is False
    assert fresh.eligible is False

    # HONEST GATE: maturity ALONE is not enough. The track is born with ZERO forward P&L (the new honest seed —
    # the backtest OOS is NOT copied into tracks.return_pct), so a matured-but-flat track must NOT be eligible.
    # It WOULD have been, before, when promotion seeded return_pct from the OOS — that was the live-arming leak.
    matured_flat = live_eligibility_verdict(
        finder.store, vid, _bull_bars(), now=now + timedelta(days=PAPER_MIN_DAYS + 5)
    )
    assert matured_flat.paper_age_days >= PAPER_MIN_DAYS
    assert matured_flat.forward_ready is False  # +0.00% forward → "paper not proven"
    assert matured_flat.eligible is False

    # Only once REAL net-positive forward P&L accrues (the paper clock writes tracks.return_pct from marks) does a
    # matured, proven-regime track become forward-ready + armable.
    finder.store.rows("UPDATE tracks SET return_pct = ? WHERE strategy_version_id = ?", ("3.5", vid))
    matured = live_eligibility_verdict(
        finder.store, vid, _bull_bars(), now=now + timedelta(days=PAPER_MIN_DAYS + 5)
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
