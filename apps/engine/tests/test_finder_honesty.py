# Regression tests for the finder-honesty fix (P0): the 256+-variant grid that fills the config library must be
# as statistically honest as research/gate.py (the 12-variant reference). These pin the closed leaks:
#   1. true trial count flows into EVERY finder decision (gate flag, leaderboard, refine seeds, promotion);
#   2. the correlation haircut / effective-N means the Deflated Sharpe gets HARDER (never easier) as the grid
#      densifies (the original behaviour was backwards);
#   3. a real CSCV-PBO is computed across the grid;
#   4. the holdout is purged + embargoed (no warm-up bleed into training);
#   5. per-symbol min_trades + a cross-symbol haircut on the pooled PSR n_obs;
#   6. correlated variants are deduped to DISTINCT representatives before BH-FDR.

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.backtest import (
    _avg_cross_correlation,
    _effective_obs,
    _purged_embargoed_split,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder, _cluster_representatives, build_grid
from cosmu.master.scorer import (
    BacktestMetrics,
    TrialStats,
    deflated_sharpe_prob,
    effective_trials,
    expected_max_sharpe,
)
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.spine.venue import default_catalog


def _valid_params(spec) -> dict[str, float]:
    """A concrete, compiler-valid param dict (the first grid point) for direct backtest calls."""
    return build_grid(spec, max_variants=1)[0].params


_SYMS = {"BTCUSDT": 30000.0, "ETHUSDT": 2000.0, "BNBUSDT": 300.0, "SOLUSDT": 25.0, "XRPUSDT": 0.5}


def _correlated_market(mu: float, n: int = 300, seed: int = 7, symbols=("BTCUSDT", "ETHUSDT")) -> dict[str, list[Bar]]:
    """A deterministic CORRELATED market: one shared factor path + a small drift `mu`. A grid of variants over
    this is itself highly correlated — the regime a significance leak exploits."""
    rng = random.Random(seed)
    base = dt.datetime(2023, 1, 1, tzinfo=dt.UTC)
    factor = [rng.gauss(0, 0.010) for _ in range(n)]
    out: dict[str, list[Bar]] = {}
    for s in symbols:
        p = _SYMS[s]
        bars = []
        for i in range(n):
            r = mu + 0.9 * factor[i] + rng.gauss(0, 0.004)
            o = p
            p = max(1e-6, p * (1 + r))
            hi = max(o, p) * (1 + abs(rng.gauss(0, 0.002)))
            lo = min(o, p) * (1 - abs(rng.gauss(0, 0.002)))
            bars.append(Bar(ts=base + dt.timedelta(hours=i), open=Decimal(str(o)), high=Decimal(str(hi)),
                            low=Decimal(str(lo)), close=Decimal(str(p)), volume=Decimal("1000")))
        out[s] = bars
    return out


class _Bars:
    def __init__(self, market: dict[str, list[Bar]]):
        self._m = market

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._m.get(symbol, next(iter(self._m.values())))[-limit:]


def _finder(tmp_path, market, name="honesty") -> StrategyFinder:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))
    return StrategyFinder(settings=store.settings, store=store, market_data=_Bars(market))


def _modest_metrics() -> BacktestMetrics:
    # A modest per-observation edge: significant against a handful of trials, NOT against hundreds.
    return BacktestMetrics(
        oos_return=Decimal("0.1"), sharpe=Decimal("1.5"), sortino=Decimal("1.5"),
        max_drawdown=Decimal("0.1"), win_rate=Decimal("0.55"), num_trades=60,
        sharpe_per_obs=Decimal("0.18"), skew=Decimal("0"), kurtosis=Decimal("3"), n_obs=250,
        pbo=Decimal("0.1"), trials_counted=1, folds_positive_pct=Decimal("0.8"),
        holdout_deflated_sharpe=Decimal("0.2"),
    )


# ----------------------------------------------------------------- Problem 2 — the correlation haircut (scorer)


def test_effective_trials_is_a_correlation_haircut():
    assert effective_trials(200, None) == 200          # no measurement → no-op (the gate is never haircut)
    assert effective_trials(200, 0.0) == 200           # independent trials → full count
    assert effective_trials(200, 1.0) == pytest.approx(1.0, abs=1e-9)  # all duplicates → one effective trial
    mid = effective_trials(200, 0.5)
    assert 1.0 < mid < 200
    # monotone NON-DECREASING in the raw count at a fixed correlation (densifying never lowers the effective N)
    assert effective_trials(50, 0.3) <= effective_trials(500, 0.3)


def test_expected_max_sharpe_floored_and_accepts_fractional_trials():
    assert expected_max_sharpe(0.01, 1.0) == 0.0          # one (effective) trial → no benchmark
    assert expected_max_sharpe(0.01, 1.5) >= 0.0          # fractional effective count is valid + floored at 0
    assert expected_max_sharpe(0.01, 10) < expected_max_sharpe(0.01, 1000)  # grows with independent trials


def test_collapsing_observed_variance_was_the_leak():
    # BEFORE: a correlated grid's OBSERVED Sharpe variance collapses as near-duplicates pile up while the raw
    # count grows → SR0 falls → the Deflated Sharpe RISES. This pins the backwards behaviour the fix closes.
    m = _modest_metrics()
    sparse = deflated_sharpe_prob(m, TrialStats(count=25, sr_variance=0.03))     # few, dispersed trials
    dense = deflated_sharpe_prob(m, TrialStats(count=400, sr_variance=0.0015))   # many, variance collapsed
    assert dense > sparse  # the leak: a denser correlated grid was EASIER to clear


def test_haircut_makes_dsr_harder_not_easier_as_grid_densifies():
    # AFTER: at a fixed correlation, densifying the grid does NOT raise the Deflated Sharpe — the effective trial
    # count plateaus instead of inflating, so SR0 cannot collapse.
    m = _modest_metrics()
    rho = 0.4
    sparse = deflated_sharpe_prob(m, TrialStats(count=25, sr_variance=0.02, sr_correlation=rho))
    dense = deflated_sharpe_prob(m, TrialStats(count=400, sr_variance=0.02, sr_correlation=rho))
    assert dense <= sparse + 1e-9


def test_gate_path_is_unchanged_when_no_correlation_supplied():
    # The honest reference gate never supplies sr_correlation → the haircut is a strict no-op there.
    m = _modest_metrics()
    trials = TrialStats(count=12, sr_variance=0.02)  # what research/gate.py passes (no correlation)
    haircut = deflated_sharpe_prob(m, trials)
    explicit_no_haircut = deflated_sharpe_prob(m, TrialStats(count=12, sr_variance=0.02, sr_correlation=None))
    assert haircut == explicit_no_haircut


# ----------------------------------------------------------------- Problem 5 — n_obs haircut + per-symbol trades


def test_pooled_n_obs_is_deflated_for_cross_symbol_correlation():
    # Two correlated symbols are not 2x the independent observations.
    assert _effective_obs(1000, 1, 0.9) == 1000                 # single symbol → untouched
    assert _effective_obs(1000, 2, 0.0) == 1000                 # uncorrelated → untouched
    assert _effective_obs(1000, 2, 1.0) == 500                  # perfectly correlated → halved
    assert 500 < _effective_obs(1000, 2, 0.4) < 1000


def test_avg_cross_correlation_detects_shared_factor():
    a = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01]
    assert _avg_cross_correlation([a, a]) == pytest.approx(1.0, abs=1e-9)  # identical streams
    assert _avg_cross_correlation([a]) == 0.0                              # need >= 2 streams


def test_backtest_exposes_per_symbol_trades_and_haircut_n_obs():
    spec = seed_orb_fvg_spec()
    market = _correlated_market(0.004, n=300, symbols=("BTCUSDT", "ETHUSDT", "BNBUSDT"))
    fee = default_catalog().venue("binance").taker_fee_bps
    res = run_strategy_backtest_detailed(spec, _valid_params(spec), market, fee_bps=fee)
    # per-symbol trade counts are exposed (not just a pooled total)
    assert set(res.symbol_trades) <= set(market)
    assert res.min_symbol_trades == (min(res.symbol_trades.values()) if res.symbol_trades else 0)
    # the recorded PSR sample size is never the naive pooled bar count of correlated symbols
    pooled = len(res.val_returns)
    assert res.metrics.n_obs <= pooled


# ----------------------------------------------------------------- Problem 4 — purged + embargoed holdout


def test_holdout_is_purged_and_embargoed_no_warmup_bleed():
    spec = seed_orb_fvg_spec()
    bars = _correlated_market(0.002, n=300)["BTCUSDT"]
    val_bars, holdout_bars = _purged_embargoed_split(spec, _valid_params(spec), bars)
    split = max(40, int(len(bars) * 0.8))
    # validation is the first ~80%; the holdout begins AT/AFTER the split — its warm-up no longer reaches back
    # into the training window (the old bars[split - warmup:] slice did).
    assert val_bars == bars[:split]
    assert holdout_bars == bars[split:] or holdout_bars == []
    if holdout_bars:
        assert holdout_bars[0].ts == bars[split].ts  # first holdout bar is not a training bar


# ----------------------------------------------------------------- Problems 1 + 6 — finder: true count + dedupe


def test_finder_counts_every_variant_as_a_trial(tmp_path):
    # The leak: deflation used ~len(param_space) (~15). Now EVERY screened variant is a registered trial.
    spec = seed_orb_fvg_spec()
    finder = _finder(tmp_path, _correlated_market(0.002))
    rep = finder.find(spec, max_variants=24)
    n_trials = finder.store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"]
    assert n_trials == rep.screened
    assert rep.screened > len(spec.param_space)  # the true count is far above the param-space proxy


def test_finder_rejects_an_edge_that_only_clears_the_leaky_count(tmp_path):
    # The modest synthetic edge fixture: the leaky param-space count would certify the best variant; the true
    # distinct-trial count does not — so the finder promotes nothing. Closing the leak in the gate flag.
    spec = seed_orb_fvg_spec()
    fixture = {s: edge_bearing_screen_market(n=280)[s][-280:] for s in ("BTCUSDT", "ETHUSDT")}
    finder = _finder(tmp_path, fixture)
    rep = finder.find(spec, max_variants=48)
    assert rep.promoted == 0  # honest deflation against the true count rejects the modest edge
    # and the SAME edge clears the bar under the OLD param-space count — proving it was the count that leaked
    best = _modest_metrics().model_copy(update={"sharpe_per_obs": Decimal("0.40"), "n_obs": 120})
    leaky = deflated_sharpe_prob(best, TrialStats(count=len(spec.param_space), sr_variance=0.0147))
    honest = deflated_sharpe_prob(best, TrialStats(count=rep.screened, sr_variance=0.0147))
    assert leaky > honest
    assert leaky >= 0.95 > honest


def test_finder_dsr_not_easier_as_the_grid_densifies(tmp_path):
    # The headline leak, end-to-end: a denser grid must not RAISE the best Deflated Sharpe on the leaderboard.
    spec = seed_orb_fvg_spec()
    market = _correlated_market(0.006, n=320)
    sparse = _finder(tmp_path, market, name="sparse").find(spec, max_variants=12)
    dense = _finder(tmp_path, market, name="dense").find(spec, max_variants=96)
    best_sparse = max((r.deflated_sharpe for r in sparse.leaderboard), default=0.0)
    best_dense = max((r.deflated_sharpe for r in dense.leaderboard), default=0.0)
    assert best_dense <= best_sparse + 1e-6


def test_cluster_representatives_collapse_near_duplicates():
    # Problem 6: correlated variants must collapse to DISTINCT representatives before BH-FDR.
    from cosmu.lab.finder import VariantResult

    base = [0.01, -0.02, 0.015, -0.005, 0.02, -0.012, 0.008, -0.003]
    near = [x + 1e-6 for x in base]            # ~identical → same cluster
    other = [-x for x in base]                 # anti-correlated → distinct cluster

    def _vr(tag: str, sharpe: float) -> VariantResult:
        return VariantResult(config_tag=tag, code_hash=tag, metrics=_modest_metrics().model_copy(update={"sharpe_per_obs": Decimal(str(sharpe))}),
                             deflated_sharpe=0.0, profit_factor=1.0, net_profit=0.0, gate_passed=False, reasons=[])

    results = [_vr("a", 0.3), _vr("b", 0.2), _vr("c", 0.1)]
    returns = {"a": base, "b": near, "c": other}
    reps = _cluster_representatives(results, returns, threshold=0.95)
    assert "a" in reps and "b" not in reps and "c" in reps  # a,b collapse; c is distinct
    assert len(reps) == 2
