# Item 1: the autonomous FarmLoop must run the holdout as a ONE-SHOT exam on its gate+FDR survivors, never as a
# per-candidate SELECTION set. The screen sees validation-only evidence (include_holdout=False); a champion that
# fails the untouched holdout is DEMOTED (the loop never retries the exam with the next-best variant). This
# TIGHTENS the gate — it can only ever remove a survivor, never add one.

from __future__ import annotations

import datetime as dt
import hashlib
import random
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
    metrics, _venue, _mst, _vr, _ps = loop._screen(cand, "code-hash", 7)
    assert metrics.holdout_deflated_sharpe == Decimal("-0.5")


def _distinct_val_stream(cand: Candidate) -> list[float]:
    """A strongly-positive, per-candidate-DISTINCT validation return stream for the forced-survivor mock. The
    cohort now clusters correlated streams into distinct representatives and certifies them with a REAL cohort
    CSCV-PBO — so the mock must hand back streams that (a) are NOT all >= 0.95 correlated (else the cohort
    collapses to ONE representative → cohort_pbo=1.0 → every candidate fails the pbo gate) and (b) stay strongly
    positive so CSCV-PBO is low (the IS-best config is also OOS-good). A deterministic per-candidate seed gives
    each its own idiosyncratic noise on a shared strong uptrend."""
    # hashlib, NOT builtin hash(): hash() is salted per-process (PYTHONHASHSEED) so the streams — and thus the
    # cohort CSCV-PBO — differed across runs, making this exam flaky (~3/5 hash seeds killed every champion on
    # pbo before the holdout could be exercised). hashlib is stable, so the forced survivor is reproducible.
    rng = random.Random(int.from_bytes(hashlib.sha256(cand.spec.name.encode()).digest()[:4], "big"))
    # 60 bars: a strong, consistent positive drift (0.01/bar) plus small idiosyncratic noise. Different noise per
    # candidate breaks the 0.95 correlation; the dominant drift keeps every stream a clear winner (low PBO).
    return [0.01 + rng.uniform(-0.006, 0.006) for _ in range(60)]


def _force_survivor(monkeypatch, loop: FarmLoop) -> None:
    venue = default_catalog().venue_for(["binance"])
    monkeypatch.setattr(
        FarmLoop, "_screen",
        lambda self, cand, code_hash, seed: (_strong(), venue, 20, _distinct_val_stream(cand), {}),
    )
    # Isolate the HOLDOUT exam (what THESE tests assert) from the orthogonal, stochastic cohort CSCV-PBO: pin the
    # cohort PBO low so the forced-strong champion deterministically reaches the one-shot holdout step. The cohort
    # PBO behaviour itself is fully covered by test_farmloop_cscv_pbo.py — here it must not gate the exam under
    # test (otherwise the stream fixture's incidental correlation, not the holdout, decides survivorship).
    monkeypatch.setattr("cosmu.evolution.loop.cohort_cscv_pbo", lambda *a, **k: 0.05)


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
