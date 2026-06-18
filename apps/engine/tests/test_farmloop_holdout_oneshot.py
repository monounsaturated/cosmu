# BRUT FarmLoop: each (mutant × symbol) cell is judged ON ITS OWN data — no cross-mutant FDR, no cluster dedupe,
# no global-trial deflation. The screen sees validation-only evidence (include_holdout=False); the untouched
# holdout is a ONE-SHOT per-cell CONFIRMATION on each passing cell (a cell that fails its own holdout is not
# funded). The loop registers NO global trials (a brut cell is not part of any family). These pin those contracts.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import Candidate, FarmLoop, _BrutCell
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store


class _FixtureProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self.bars[-limit:]


def _fixture_bars(count: int = 600) -> list[Bar]:
    """A trade-DENSE cyclic-bull series so a SINGLE symbol's cell books >= the brut per-cell trade floor (30 of its
    OWN trades) and clears its own DSR — under brut each cell is judged ALONE, so pooling thin per-symbol books
    over min_trades no longer works."""
    ts = dt.datetime(2023, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    out: list[Bar] = []
    for i in range(count):
        mv = Decimal("0.012") if (i % 14) < 9 else Decimal("-0.005")
        o = price
        cl = (price * (Decimal("1") + mv)).quantize(Decimal("0.0001"))
        out.append(Bar(ts=ts + dt.timedelta(days=i), open=o, high=max(o, cl) * Decimal("1.006"),
                       low=min(o, cl) * Decimal("0.994"), close=cl, volume=Decimal("1000")))
        price = cl
    return out


def _loop(tmp_path, *, beat_bnh: bool = False) -> FarmLoop:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/fl.sqlite3",
                           gates=GateSettings(require_beat_buy_and_hold=beat_bnh)))
    return FarmLoop(settings=store.settings, store=store, market_data=_FixtureProvider(_fixture_bars()))


def test_screen_is_validation_only_no_holdout_simulated(tmp_path):
    # The real screen runs include_holdout=False, so the untouched holdout is NEVER simulated during selection:
    # holdout_deflated_sharpe reads the no-evidence sentinel (PSR(∅)−0.5 = −0.5). The brut _screen returns the
    # per-symbol RUNS + per-symbol B&H (the streams each cell is judged on) — never the pooled holdout.
    loop = _loop(tmp_path)
    cand = Candidate(spec=seed_orb_fvg_spec(), origin="seed", lane="gate")
    metrics, _venue, _mst, _vr, per_symbol, per_symbol_runs, per_symbol_bh, _cell_meta = loop._screen(cand, "code-hash", 7)
    assert metrics.holdout_deflated_sharpe == Decimal("-0.5")  # the exam was never sat during the screen
    assert set(per_symbol_runs) == set(per_symbol)  # a run per screened symbol — the per-cell streams
    assert set(per_symbol_bh) <= set(per_symbol)    # each cell's own buy-and-hold benchmark


def test_brut_loop_registers_no_global_trials(tmp_path):
    # BRUT contract: a per-combo cell is not part of any cross-combo family, so the autonomous loop registers NO
    # global trials (it no longer contaminates the pooled research lanes' ledger, and each cell deflates on its OWN
    # per-combo evidence). The pooled FDR/cluster cull that register_trial fed is gone.
    loop = _loop(tmp_path)
    loop.run_cohort(seed=7, cohort_size=4)
    assert loop.store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"] == 0


def test_score_cells_judges_each_symbol_on_its_own_streams(tmp_path):
    # _score_cells builds ONE cell per symbol from that symbol's OWN run + B&H + trials=1 and scores it ALONE via
    # promote_brut — the cell's pass/fail is independent of its siblings. A thin cell (< the per-cell trade floor)
    # is killed on min_trades_per_symbol; a cell never re-pools sibling streams.
    loop = _loop(tmp_path)
    cand = Candidate(spec=seed_orb_fvg_spec(), origin="seed", lane="gate")
    metrics, venue, mst, vr, per_symbol, per_symbol_runs, per_symbol_bh, cell_meta = loop._screen(cand, "h", 7)
    from cosmu.evolution.loop import _Screened

    sc = _Screened(cand=cand, params={}, compiled=None, metrics=metrics, survival_score=0.0, proven=[],
                   per_symbol=per_symbol, per_symbol_runs=per_symbol_runs, per_symbol_buy_and_hold=per_symbol_bh,
                   venue_id=venue.id, pre_kill=None, cell_meta=cell_meta)
    cells = loop._score_cells(sc)
    assert set(cells) == set(per_symbol_runs)
    for sym, cell in cells.items():
        assert isinstance(cell, _BrutCell)
        assert cell.symbol == sym and cell.venue_id == venue.id
        # the cell's own trade count drives its floor reason — never a pooled total
        if cell.trades < 5:
            assert "min_trades_per_symbol" in cell.reasons


def test_champion_holdout_runs_are_per_cell(tmp_path):
    # The one-shot exam re-runs the backtest WITH the embargoed holdout and exposes a holdout RUN per symbol, so
    # the brut gate confirms EACH passing cell on its OWN holdout stream (never a pooled basket holdout).
    from cosmu.evolution.loop import fit_params

    loop = _loop(tmp_path)
    spec = seed_orb_fvg_spec()
    holdout_runs, holdout_bh = loop._champion_holdout_runs(spec, fit_params(spec))
    assert isinstance(holdout_runs, dict)
    assert isinstance(holdout_bh, dict)
    # every holdout run has its own bar_returns stream (the per-cell confirmation evidence)
    for run in holdout_runs.values():
        assert hasattr(run, "bar_returns")
