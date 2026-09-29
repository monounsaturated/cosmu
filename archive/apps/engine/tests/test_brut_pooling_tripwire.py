# BRUT-integrity regression tripwire: a pooled per-STRATEGY average can NEVER rescue a per-cell verdict.
#
# The operator's core "BRUT" guarantee (hand-verified, memorialized in evolution/loop.py::_score_cells): the live
# funding VERDICT judges each (strategy × symbol × venue) CELL on its OWN data. A cell passes iff it clears the
# locked stats gate on its OWN streams (its own bar_returns + fold_returns + trade count). It must NEVER be
# rescued by a per-strategy POOLED average of OOS-return / %-perf across the strategy's cells.
#
# The pooled figure (data/backtest.py::_combine -> SymbolRun.total_return = statistics.fmean(total_return across
# symbols), surfaced as BacktestMetrics.oos_return on the pooled BacktestResult) is a DISPLAY metric ONLY. It must
# never reach a verdict.
#
# These tests drive the SAME per-cell verdict path the live loop uses: build per-cell metrics from per-symbol
# SymbolRuns via metrics_for_run(trials=1), then call promote_brut(candidates, gates, min_trades=...) — byte-for-byte
# what evolution/loop.py::_score_cells does. The headline scenario constructs a sweep whose POOLED average return is
# a clear, Gate-pass-looking positive, yet EVERY individual cell is a Gate-FAIL. The assertion: the number of
# promotions reflects ONLY the per-cell verdicts — the pooled positive rescues NOTHING.
#
# If this file ever goes red, someone re-introduced pooled rescue into the funding path. Do not "fix" the test —
# fix the regression.

from __future__ import annotations

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.backtest import SymbolRun, Trade, _combine, metrics_for_run
from cosmu.master.cohort import Candidate, promote_brut

# The live brut floor evolution/loop.py hands promote_brut (loop._BRUT_MIN_TRADES). Pinned here so the scenario
# exercises the EXACT pre-paper trade bar the funding path applies, not GateSettings' default.
_BRUT_MIN_TRADES = 30


def _trades(n: int, pnl_pct: float = 0.02) -> list[Trade]:
    """n identical winning trades — enough to drive num_trades and a positive win_rate/profit_factor."""
    return [Trade(entry=100.0, exit=100.0 * (1 + pnl_pct), pnl_pct=pnl_pct) for _ in range(n)]


def _run(*, total_return: float, bar_returns: list[float], fold_returns: list[float], trades: list[Trade]) -> SymbolRun:
    """A hand-built per-symbol run with full control over the streams the brut gate scores. bar_returns drives
    sharpe_per_obs / n_obs (the DSR), fold_returns drives folds_positive_pct + the PBO proxy, trades drives
    num_trades. total_return is what _combine pools into the DISPLAY-only fmean — it never enters a per-cell DSR."""
    return SymbolRun(
        total_return=total_return,
        sharpe=0.0,  # annualized display field; metrics_for_run recomputes the scored numbers from the streams
        sortino=0.0,
        max_drawdown=0.05,  # under GateSettings.max_drawdown_pct (0.25) so drawdown is never the killer
        trades=trades,
        bar_returns=bar_returns,
        bar_ts=[f"2026-01-{i % 28 + 1:02d}T00:00:00+00:00" for i in range(len(bar_returns))],
        fold_returns=fold_returns,
        regime_pnl={},
        periods_per_year=365.0,
    )


def _lifter_run() -> SymbolRun:
    """A 'lifter' cell: a HUGE positive total_return (+1.50) that pulls the pooled fmean strongly positive — but it
    books only a HANDFUL of trades (5 < _BRUT_MIN_TRADES=30), so on its OWN data it is a Gate-FAIL (min_trades).
    This is the rescue bait: under any pooled-average shortcut, its +150% would carry the whole strategy."""
    return _run(
        total_return=1.50,
        bar_returns=[0.20, 0.18, 0.22, 0.19, 0.21],  # large per-bar edge, but only n_obs=5 (thin)
        fold_returns=[0.2, 0.2, 0.2, 0.2, 0.2],
        trades=_trades(5, pnl_pct=0.25),
    )


def _loser_run(seed: float) -> SymbolRun:
    """A 'loser' cell: NEGATIVE total_return on a long, dense, choppy/losing stream. Plenty of trades and bars (so
    it can't be excused as 'thin'), but a sub-threshold/negative own edge → Gate-FAIL on its OWN data (DSR +
    folds_positive + beat-buy-and-hold). These DRAG the pooled mean down toward zero but never below the lifters'
    pull, so the pooled average stays POSITIVE while the cells themselves are all dead."""
    n = 120
    bar_returns = [(-0.01 if i % 2 == 0 else 0.008) + seed * 0.0001 for i in range(n)]  # net-negative drift
    fold_returns = [-0.02, 0.01, -0.03, -0.01, -0.02, 0.005, -0.015, -0.02]  # mostly losing folds
    return _run(
        total_return=-0.12 + seed * 0.0,  # clearly negative own return
        bar_returns=bar_returns,
        fold_returns=fold_returns,
        trades=_trades(40, pnl_pct=-0.003),  # dense (>=30) but losing
    )


def _verdicts(runs: dict[str, SymbolRun], gates: GateSettings) -> dict[str, object]:
    """Replicate evolution/loop.py::_score_cells EXACTLY: one CohortCandidate per cell, metrics built from that
    cell's OWN run via metrics_for_run(trials=1), then promote_brut(min_trades=_BRUT_MIN_TRADES). Returns
    {cell_id: BrutPromotion}. The per-cell trade floor is enforced inside promote_brut via min_trades, mirroring
    the live floor_ok check the loop layers on top."""
    candidates = [
        Candidate(id=key, metrics=metrics_for_run(run, trials=1, buy_and_hold=0.0), net_profit=0.0, source="farmloop")
        for key, run in runs.items()
    ]
    return {p.candidate_id: p for p in promote_brut(candidates, gates, min_trades=_BRUT_MIN_TRADES)}


# --------------------------------------------------------------------- the headline guarantee


def test_positive_pooled_average_rescues_no_per_cell_verdict():
    """THE guarantee: a strategy whose POOLED average return is a clear, Gate-pass-looking positive, but whose
    EVERY individual cell is a Gate-FAIL, promotes ZERO cells. The pooled positive rescues nothing — a cell passes
    iff it clears on its OWN streams."""
    runs = {
        "BTC/USDT@binance": _lifter_run(),   # +150% own return, but only 5 trades -> FAIL (min_trades)
        "ETH/USDT@binance": _lifter_run(),   # idem -> FAIL (min_trades)
        "SOL/USDT@binance": _loser_run(1),   # negative own edge -> FAIL
        "XRP/USDT@binance": _loser_run(2),   # negative own edge -> FAIL
        "BNB/USDT@binance": _loser_run(3),   # negative own edge -> FAIL
    }

    # 1) The POOLED display metric is a clear positive — exactly the figure data/backtest.py::_combine surfaces as
    #    BacktestResult.oos_return. This is the rescue bait: a pooled-average shortcut would read this as a PASS.
    pooled = _combine(list(runs.values()))
    assert pooled.total_return > 0.30, (
        f"fixture invalid: pooled fmean must look like a clear Gate-pass positive, got {pooled.total_return}"
    )

    # 2) Drive the SAME per-cell verdict path the live loop uses.
    verdicts = _verdicts(runs, Settings(openrouter_api_key=None).gates)

    # 3) The verdict reflects ONLY the per-cell evidence: NOTHING is promoted. The pooled +30%+ rescued nothing.
    promoted = [cid for cid, p in verdicts.items() if p.promoted]
    assert promoted == [], f"pooled positive average rescued cells it must not: {promoted}"

    # And every cell carries a real per-cell kill reason (it failed on its OWN data, not for being unscored).
    for cid, p in verdicts.items():
        assert not p.promoted
        assert p.reasons, f"cell {cid} failed without a recorded per-cell reason"

    # The two lifters die on their OWN thinness (min_trades) — never excused by their +150%.
    assert "min_trades" in verdicts["BTC/USDT@binance"].reasons
    assert "min_trades" in verdicts["ETH/USDT@binance"].reasons


def test_a_genuinely_strong_cell_still_passes_on_its_own_data():
    """Control / non-vacuity: the per-cell path is not a brick that fails everything. A cell that clears the gate on
    its OWN dense, positive, low-overfit streams DOES promote — proving the all-fail result above is the pooled
    average being correctly ignored, not the gate being unconditionally closed."""
    n = 600
    strong = _run(
        total_return=0.45,
        # a steady, dense per-bar edge -> high sharpe_per_obs against trials=1 -> clears the 0.95 DSR bar
        bar_returns=[0.01 if i % 7 else 0.012 for i in range(n)],
        fold_returns=[0.03, 0.02, 0.04, 0.025, 0.03, 0.035, 0.02, 0.03],  # all-positive folds
        trades=_trades(80, pnl_pct=0.01),  # well over the trade floor
    )
    candidates = [Candidate(
        id="STRONG@binance",
        # beat-buy-and-hold opted out (this is a streams-only control, not a basket-relative test)
        metrics=metrics_for_run(strong, trials=1, buy_and_hold=0.0),
        net_profit=0.0, source="farmloop",
    )]
    gates = GateSettings(require_beat_buy_and_hold=False)
    verdicts = {p.candidate_id: p for p in promote_brut(candidates, gates, min_trades=_BRUT_MIN_TRADES)}
    assert verdicts["STRONG@binance"].promoted, (
        f"a genuinely strong own-data cell must still pass — gate is over-closed: {verdicts['STRONG@binance'].reasons}"
    )


# --------------------------------------------------------------------- the structural invariant


def test_promote_brut_uses_per_cell_trials_one_invariant_to_sweep_size():
    """Lock the STRUCTURE that makes pooled rescue impossible: promote_brut defaults to TrialStats(count=1) (a brut
    cell has no siblings in its test) and the per-combo deflation rides on metrics.trials_counted (per cell). A
    cell's verdict is therefore INVARIANT to how many OTHER cells the sweep produced — adding losers can neither
    rescue nor sink a target cell.

    We score the SAME failing lifter cell inside a 2-cell sweep and inside a 200-cell sweep (199 distinct extra
    losers) and assert its verdict + deflated Sharpe are byte-identical."""
    gates = Settings(openrouter_api_key=None).gates
    target = Candidate(
        id="TARGET@binance",
        metrics=metrics_for_run(_lifter_run(), trials=1, buy_and_hold=0.0),
        net_profit=0.0, source="farmloop",
    )
    # The structural fact: metrics built with trials=1 carry trials_counted == 1 (per cell, not a family count).
    assert target.metrics.trials_counted == 1

    def _losers(k: int) -> list[Candidate]:
        return [
            Candidate(id=f"loser-{i}", metrics=metrics_for_run(_loser_run(i), trials=1, buy_and_hold=0.0),
                      net_profit=0.0, source="farmloop")
            for i in range(k)
        ]

    small = {p.candidate_id: p for p in promote_brut([target, *_losers(1)], gates, min_trades=_BRUT_MIN_TRADES)}
    large = {p.candidate_id: p for p in promote_brut([target, *_losers(199)], gates, min_trades=_BRUT_MIN_TRADES)}

    # The target cell's verdict AND its deflated Sharpe are identical across a 2-cell and a 200-cell sweep:
    # the cohort size never enters the per-cell verdict (no register_trial, no FDR, no sibling deflation).
    assert small["TARGET@binance"].promoted == large["TARGET@binance"].promoted is False
    assert small["TARGET@binance"].deflated_sharpe_prob == large["TARGET@binance"].deflated_sharpe_prob
