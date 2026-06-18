# The Strategy Finder's prediction (Polymarket) branch: a spec declaring venue=polymarket + asset_class=prediction
# pulls the most-liquid open conditionIds from universe_pairs and reads each market's per-MARKET `odds` series
# (ingest/polymarket_odds.py) back through the PredictionDataAdapter as Bars whose price IS the implied
# probability — so the spec flows end-to-end into the BRUT backtest + per-cell gate (each market judged on its
# OWN odds series). Non-prediction specs are unaffected (no prediction markets enter their panel). Hermetic: a
# JSONL alt store is injected with synthetic odds; universe_pairs is seeded in a SQLite Store.

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataStore
from cosmu.evolution.seeder import seed_momentum_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)

_CID_A = "0xPM_A"
_CID_B = "0xPM_B"
_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _prediction_spec() -> StrategySpec:
    """A minimal prediction StrategySpec: long the YES side when the odds have been rising (ret_Nd > floor) — a
    pure odds-velocity entry on the per-market probability series. venue=polymarket, asset_class=prediction."""
    return StrategySpec(
        name="PM odds-velocity",
        rationale="Long the YES side of a prediction market when its implied probability has been rising (odds momentum).",
        universe=UniverseSelector(venues=["polymarket"], asset_classes=["prediction"], min_liquidity_usd=0, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=10),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.04, conviction=0.55),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=3, hi=10, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.0, hi=0.05),
            "stop": ParamSpace(kind="float", lo=0.05, hi=0.2),
            "take": ParamSpace(kind="float", lo=0.05, hi=0.3),
            "time_stop": ParamSpace(kind="int", lo=2, hi=10, step=1),
        },
    )


def _odds_series(n: int, base: float, amp: float) -> list[AltDataPoint]:
    """A daily odds walk in (0,1): a sine ripple around `base` so a momentum entry both fires and reverses (real
    trades, not a degenerate monotone). Probabilities stay strictly inside (0,1)."""
    out: list[AltDataPoint] = []
    for i in range(n):
        v = base + amp * math.sin(i / 9.0)
        v = min(0.97, max(0.03, v))
        ts = _T0 + timedelta(days=i)
        out.append(AltDataPoint(ts=ts, available_at=ts, value=v))
    return out


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/finder_pm.sqlite3", openrouter_api_key=None))


def _seed_universe(store: Store, rows: list[tuple[str, float]]) -> None:
    with store.batch() as w:
        w.insert_many(
            "universe_pairs",
            ["id", "venue", "symbol", "asset_class", "instrument_type", "liquidity_usd_24h", "active", "source", "fetched_at"],
            [(f"polymarket:{cid}", "polymarket", cid, "prediction", "prediction", liq, 1, "live", "2026-06-18T00:00:00+00:00") for cid, liq in rows],
            ignore_duplicates=True,
        )


def _alt_with_odds(tmp_path) -> AltDataStore:
    alt = AltDataStore(root=tmp_path / "alt")
    alt.append("polymarket", _CID_A, "odds", _odds_series(280, base=0.45, amp=0.25))
    alt.append("polymarket", _CID_B, "odds", _odds_series(280, base=0.55, amp=0.20))
    return alt


def test_prediction_branch_builds_odds_panel(tmp_path):
    store = _store(tmp_path)
    _seed_universe(store, [(_CID_A, 500.0), (_CID_B, 400.0)])
    finder = StrategyFinder(settings=store.settings, store=store, alt_store=_alt_with_odds(tmp_path))

    spec = _prediction_spec()
    market = finder._market(spec)  # noqa: SLF001 — exercising the branch directly
    # Both conditionIds are in the panel, keyed by conditionId, priced on the odds series (close ∈ (0,1)).
    assert set(market) == {_CID_A, _CID_B}
    assert all(0.0 < float(b.close) < 1.0 for b in market[_CID_A])
    assert len(market[_CID_A]) == 280


def test_prediction_spec_backtests_end_to_end(tmp_path):
    """End-to-end EXECUTABILITY (not a results claim): the prediction spec compiles, backtests on the ingested
    per-market odds, and every variant is SCREENED (a full backtest ran). Whether any cell PASSES the brut gate is
    irrelevant here — the gate is locked and judges each market on its OWN odds; we only assert the pipe is live."""
    store = _store(tmp_path)
    _seed_universe(store, [(_CID_A, 500.0), (_CID_B, 400.0)])
    finder = StrategyFinder(settings=store.settings, store=store, alt_store=_alt_with_odds(tmp_path))

    report = finder.find(_prediction_spec(), max_variants=6, persist=False, two_pass=False)
    assert report.screened >= 1  # variants compiled + backtested on the odds series end-to-end


def test_prediction_brut_cells_are_produced_with_verdicts(tmp_path):
    """The per-cell BRUT gate is REACHED for prediction: screening one variant yields one CellResult per market,
    keyed by conditionId, priced at the polymarket venue, carrying a real verdict (passed bool + DSR) computed on
    THAT market's own odds series. This is the executability proof — a SymbolRun → metrics_for_run → promote_brut
    per market — not a claim about edge."""
    from cosmu.lab.finder import build_grid
    from cosmu.master.screen_universe import build_cost_context
    from cosmu.spine.venue import default_catalog

    store = _store(tmp_path)
    _seed_universe(store, [(_CID_A, 500.0), (_CID_B, 400.0)])
    finder = StrategyFinder(settings=store.settings, store=store, alt_store=_alt_with_odds(tmp_path))
    spec = _prediction_spec()

    market = finder._market(spec)  # noqa: SLF001
    grid = build_grid(spec, max_variants=6)
    catalog = default_catalog()
    venue = catalog.venue_for(spec.universe.venues)
    assert venue.id == "polymarket"  # the spec is priced at its OWN (prediction) venue
    fee_schedule, depth_schedule, asset_class_by_symbol, venue_id_by_symbol = build_cost_context(spec, market, catalog)
    # Polymarket is asset-aware → a per-symbol fee schedule is built (not the crypto-only all-None path).
    assert fee_schedule is not None and set(fee_schedule) == {_CID_A, _CID_B}

    result = finder._screen(  # noqa: SLF001
        spec, grid[0], market, venue, alt_by_symbol=None, grid_size=len(grid),
        fee_schedule=fee_schedule, depth_schedule=depth_schedule,
        asset_class_by_symbol=asset_class_by_symbol, venue_id_by_symbol=venue_id_by_symbol,
    )
    assert result is not None, "the prediction variant failed to compile/backtest"
    assert set(result.cells) == {_CID_A, _CID_B}  # one brut cell per market, keyed by conditionId
    for cid, cell in result.cells.items():
        assert cell.symbol == cid
        assert cell.venue_id == "polymarket"            # priced at the prediction venue (per-category taker fee)
        assert isinstance(cell.passed, bool)            # a real brut verdict, not a results claim
        assert isinstance(cell.deflated_sharpe, float)  # the locked DSR math ran on this market's OWN odds


def test_non_prediction_spec_pulls_no_prediction_markets(tmp_path):
    """A crypto spec must NOT pick up prediction markets — the branch is opt-in via venue+asset_class."""
    store = _store(tmp_path)
    _seed_universe(store, [(_CID_A, 500.0), (_CID_B, 400.0)])
    finder = StrategyFinder(settings=store.settings, store=store, alt_store=_alt_with_odds(tmp_path))

    crypto_spec = seed_momentum_spec()  # venues=binance/ibkr, no polymarket
    assert finder._prediction_symbols(crypto_spec) == []  # noqa: SLF001
