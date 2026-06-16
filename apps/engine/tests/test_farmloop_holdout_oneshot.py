# Item 1: the autonomous FarmLoop must run the holdout as a ONE-SHOT exam on its gate+FDR survivors, never as a
# per-candidate SELECTION set. The screen sees validation-only evidence (include_holdout=False); a champion that
# fails the untouched holdout is DEMOTED (the loop never retries the exam with the next-best variant). This
# TIGHTENS the gate — it can only ever remove a survivor, never add one.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import Candidate, FarmLoop
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics
from cosmu.spine.venue import default_catalog


class _FixtureProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self.bars[-limit:]


def _fixture_bars(count: int = 420) -> list[Bar]:
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    out: list[Bar] = []
    for i in range(count):
        mv = Decimal("0.012") if (i % 18) < 9 else Decimal("-0.009")
        if i % 53 == 0:
            mv -= Decimal("0.035")
        o = price
        cl = (price * (Decimal("1") + mv)).quantize(Decimal("0.0001"))
        out.append(Bar(ts=ts + dt.timedelta(days=i), open=o, high=max(o, cl) * Decimal("1.006"),
                       low=min(o, cl) * Decimal("0.994"), close=cl, volume=Decimal("1000")))
        price = cl
    return out


def _loop(tmp_path) -> FarmLoop:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/fl.sqlite3"))
    return FarmLoop(settings=store.settings, store=store, market_data=_FixtureProvider(_fixture_bars()))


# Very strong, gate-clearing metrics (no holdout field — the screen no longer measures it). Used to FORCE a
# survivor through the (correctly strict) gate so the champion-holdout step actually runs.
def _strong() -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.2"), sharpe=Decimal("19"), sortino=Decimal("2"), max_drawdown=Decimal("0.08"),
        win_rate=Decimal("0.6"), num_trades=80, sharpe_per_obs=Decimal("1.0"), skew=Decimal("0"),
        kurtosis=Decimal("3"), n_obs=1000, pbo=Decimal("0.05"), trials_counted=1,
        folds_positive_pct=Decimal("0.9"),
    )


def test_screen_is_validation_only_no_holdout_simulated(tmp_path):
    # The real screen runs include_holdout=False, so the untouched holdout is NEVER simulated during selection:
    # holdout_deflated_sharpe reads the no-evidence sentinel (PSR(∅)−0.5 = −0.5), which is BELOW any floor. That
    # the screen returns the sentinel (not a real exam value) is the proof selection didn't peek — and it's
    # exactly why _persist must score with check_holdout=False (else every candidate would die on the sentinel).
    loop = _loop(tmp_path)
    cand = Candidate(spec=seed_orb_fvg_spec(), origin="seed", lane="gate")
    metrics, _venue, _mst = loop._screen(cand, "code-hash", 7)
    assert metrics.holdout_deflated_sharpe == Decimal("-0.5")


def _force_survivor(monkeypatch, loop: FarmLoop) -> None:
    venue = default_catalog().venue_for(["binance"])
    monkeypatch.setattr(FarmLoop, "_screen", lambda self, cand, code_hash, seed: (_strong(), venue, 20))


def test_champion_holdout_demotes_a_survivor_that_fails_the_exam(tmp_path, monkeypatch):
    loop = _loop(tmp_path)
    _force_survivor(monkeypatch, loop)
    monkeypatch.setattr(FarmLoop, "_champion_holdout", lambda self, spec, params: -1.0)  # below any floor → fails
    summary = loop.run_cohort(seed=7, cohort_size=4)

    assert summary.generated > 0
    assert summary.survivors == []  # every champion failed the one-shot exam → none promoted
    killed = loop.store.rows("SELECT status, kill_reason FROM strategy_versions WHERE status = 'killed'")
    assert any(r["kill_reason"] and "holdout" in r["kill_reason"] for r in killed)
    assert loop.store.row("SELECT id FROM events WHERE kind = 'holdout_look'") is not None
    # a demoted champion's track is removed and its screen backtest marked failed
    assert loop.store.row("SELECT id FROM tracks") is None
    assert loop.store.row("SELECT id FROM backtests WHERE kind='screen' AND CAST(passed_gates AS INT)=1") is None


def test_champion_holdout_keeps_a_survivor_that_passes_the_exam(tmp_path, monkeypatch):
    loop = _loop(tmp_path)
    _force_survivor(monkeypatch, loop)
    monkeypatch.setattr(FarmLoop, "_champion_holdout", lambda self, spec, params: 5.0)  # clears the floor → passes
    summary = loop.run_cohort(seed=7, cohort_size=4)

    assert len(summary.survivors) >= 1  # champions that pass the exam stay promoted
    for s in summary.survivors:
        bt = loop.store.row("SELECT holdout_passed FROM backtests WHERE strategy_version_id=? AND kind='screen'", (s.version_id,))
        assert int(bt["holdout_passed"]) == 1  # the one-shot exam marked it passed
