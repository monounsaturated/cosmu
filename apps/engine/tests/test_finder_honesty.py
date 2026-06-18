# Honesty tests for the BRUT per-combo finder. The locked scorer/backtest MATH is unchanged (these still pin the
# DSR correlation-haircut, the n_obs haircut, the purged+embargoed holdout, and the validation-only screen). What
# CHANGED with brut: the finder no longer registers cross-combo trials, no longer clusters/FDRs across variants,
# and judges each (variant × symbol × venue) cell on its OWN data. These pin the brut contract:
#   - the finder registers NO global trials (a brut cell isn't part of a family);
#   - a cell's deflated Sharpe is INVARIANT to how many SIBLING cells (symbols) the sweep produced — no family
#     leak via trials_counted (only the per-combo PARAM-grid count deflates, never the cross-cell count);
#   - densifying the PARAM grid raises the per-combo trial count → the per-cell DSR gets HARDER, never easier.

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
    metrics_for_run,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import StrategyFinder, build_grid
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


def _trade_dense_market(n: int = 600, cycle: int = 30, seed: int = 5) -> dict[str, list[Bar]]:
    """A deterministic cyclic-bull market dense enough that a SINGLE symbol books >= the brut per-cell trade floor
    (30 of its OWN trades) and clears its own DSR. Under brut each cell is judged ALONE, so the fixture can no
    longer rely on pooling thin per-symbol books to clear min_trades — it must be honestly trade-dense per cell."""
    rng = random.Random(seed)
    base = dt.datetime(2021, 1, 1, tzinfo=dt.UTC)
    factor = [rng.gauss(0, 0.004) for _ in range(n)]
    market: dict[str, list[Bar]] = {}
    for k, (sym, p0) in enumerate(_SYMS.items()):
        p = p0
        bars = []
        for i in range(n):
            drift = 0.012 if i % cycle < int(cycle * 0.7) else -0.004  # frequent up/down legs → many entries
            r = drift + 0.9 * factor[i] + rng.gauss(0, 0.0006 * (1 + k * 0.1))
            o = p
            p = max(1e-6, p * (1 + r))
            hi = max(o, p) * (1 + abs(rng.gauss(0, 0.001)))
            lo = min(o, p) * (1 - abs(rng.gauss(0, 0.001)))
            bars.append(Bar(ts=base + dt.timedelta(days=i), open=Decimal(str(o)), high=Decimal(str(hi)),
                            low=Decimal(str(lo)), close=Decimal(str(p)), volume=Decimal("5000000")))
        market[sym] = bars
    return market


class _Bars:
    def __init__(self, market: dict[str, list[Bar]]):
        self._m = market

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._m.get(symbol, [])[-limit:]


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


# ----------------------------------------------------------------- BRUT: no family — per-cell, own data only


def test_finder_registers_no_trials_brut(tmp_path):
    # BRUT contract: a per-combo cell is NOT part of any cross-combo family, so the finder registers NO global
    # trials (the per-combo param-grid count rides on metrics.trials_counted, not the ledger). The pooled
    # FDR/cross-cell deflation register_trial fed is gone — each cell is judged on its OWN data.
    spec = seed_orb_fvg_spec()
    finder = _finder(tmp_path, _correlated_market(0.002))
    finder.find(spec, max_variants=24)
    n_trials = finder.store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"]
    assert n_trials == 0


def test_cell_deflated_sharpe_invariant_to_sibling_cell_count():
    # NO RE-POOLING / no family leak via the sibling count: a cell's deflated Sharpe must depend ONLY on its OWN
    # streams + its OWN per-combo PARAM-grid count — NEVER on how many SIBLING cells (other symbols/cells) the sweep
    # produced. This now ACTUALLY VARIES the sibling count: the SAME target cell is scored once inside a sweep of 2
    # cells and once inside a sweep of 500 DISTINCT sibling cells, and its DSR must come out byte-identical. (The
    # locked DSR/PBO math is untouched; only the COHORT SIZE handed to promote_brut changes — which, under brut,
    # must not enter any cell's verdict because promote_brut registers no trials, runs no FDR, and scores each cell
    # on its own metrics with TrialStats(count=1).)
    import dataclasses as _dc
    import random as _rnd

    from cosmu.master.cohort import Candidate, promote_brut

    spec = seed_orb_fvg_spec()
    market = _correlated_market(0.006, n=320, symbols=("BTCUSDT", "ETHUSDT"))
    fee = default_catalog().venue("binance").taker_fee_bps
    res = run_strategy_backtest_detailed(spec, _valid_params(spec), market, fee_bps=fee)
    sym = next(iter(res.per_symbol_runs))
    run = res.per_symbol_runs[sym]
    bh = res.per_symbol_buy_and_hold.get(sym, 0.0)

    grid_size = 32  # the target cell's OWN per-combo param-grid count (the legitimate own-overfit deflation)
    target = Candidate(id=sym, metrics=metrics_for_run(run, trials=grid_size, buy_and_hold=bh),
                       net_profit=0.0, source="finder")

    def _sibling(i: int) -> Candidate:
        # A DISTINCT sibling cell with its OWN (perturbed) return stream, so the cohort is genuinely larger — not a
        # copy of the target. Its presence must NOT touch the target cell's verdict under brut.
        rng = _rnd.Random(1000 + i)
        sib_run = _dc.replace(run, bar_returns=[r + rng.gauss(0, 0.001) for r in run.bar_returns])
        return Candidate(id=f"sibling-{i}", metrics=metrics_for_run(sib_run, trials=grid_size, buy_and_hold=bh),
                         net_profit=0.0, source="finder")

    settings = Settings(openrouter_api_key=None)
    # SWEEP A: the target among 1 sibling (cohort of 2). SWEEP B: the target among 499 siblings (cohort of 500).
    small = [target, _sibling(0)]
    large = [target] + [_sibling(i) for i in range(499)]
    by_id_small = {p.candidate_id: p for p in promote_brut(small, settings.gates)}
    by_id_large = {p.candidate_id: p for p in promote_brut(large, settings.gates)}
    # The target cell's deflated Sharpe is BYTE-IDENTICAL across a 2-cell and a 500-cell sweep.
    assert by_id_small[sym].deflated_sharpe_prob == by_id_large[sym].deflated_sharpe_prob


def test_cell_dsr_harder_as_param_grid_densifies():
    # Densifying the PARAM grid (the per-combo trial count) raises trials_counted → the per-cell DSR gets HARDER,
    # never easier. This is the legitimate own-overfit deflation, applied per cell. (More param variants tried on
    # this combo = more multiple-testing on THIS combo, so the bar rises — exactly as DSR intends.)
    spec = seed_orb_fvg_spec()
    market = _correlated_market(0.006, n=320, symbols=("BTCUSDT", "ETHUSDT"))
    fee = default_catalog().venue("binance").taker_fee_bps
    res = run_strategy_backtest_detailed(spec, _valid_params(spec), market, fee_bps=fee)
    sym = next(iter(res.per_symbol_runs))
    run, bh = res.per_symbol_runs[sym], res.per_symbol_buy_and_hold.get(sym, 0.0)
    sparse = metrics_for_run(run, trials=4, buy_and_hold=bh)
    dense = metrics_for_run(run, trials=128, buy_and_hold=bh)
    dsr_sparse = deflated_sharpe_prob(sparse, TrialStats(count=1))
    dsr_dense = deflated_sharpe_prob(dense, TrialStats(count=1))
    assert dsr_dense <= dsr_sparse + 1e-9


def test_finder_rejects_a_modest_edge_per_cell(tmp_path):
    # The modest synthetic edge fixture must not promote ANY cell under the brut per-cell gate (the per-combo
    # param-grid deflation + the locked DSR bar reject it). Honest empty result, per cell.
    spec = seed_orb_fvg_spec()
    fixture = {s: edge_bearing_screen_market(n=280)[s][-280:] for s in ("BTCUSDT", "ETHUSDT")}
    finder = _finder(tmp_path, fixture)
    rep = finder.find(spec, max_variants=48)
    assert rep.promoted == 0  # no cell of any variant cleared its OWN gate + holdout


# ------------------------------------------------- deep review H4 — the holdout is champion-only, never a filter


def test_include_holdout_false_skips_the_exam_and_keeps_validation_identical():
    """The screening lane's include_holdout=False must (a) never simulate the holdout — its metrics read the
    no-evidence sentinel (−0.5, what an empty holdout stream produces) — and (b) leave every validation number
    byte-identical, so skipping the exam can never change selection."""
    market = _correlated_market(mu=0.004)
    spec = seed_orb_fvg_spec()
    params = _valid_params(spec)
    fee = default_catalog().venue("binance").taker_fee_bps

    with_exam = run_strategy_backtest_detailed(spec, params, market, fee_bps=fee)
    without = run_strategy_backtest_detailed(spec, params, market, fee_bps=fee, include_holdout=False)

    assert float(without.metrics.holdout_deflated_sharpe) == -0.5  # the exam was never sat
    assert without.holdout_returns == []
    assert without.metrics.oos_return == with_exam.metrics.oos_return
    assert without.metrics.sharpe_per_obs == with_exam.metrics.sharpe_per_obs
    assert without.val_returns == with_exam.val_returns


def test_finder_holdout_is_champion_only(tmp_path):
    """H4 (deep review): the grid screens WITHOUT the holdout; only PROMOTED cluster representatives sit the
    exam — exactly once each, audited as a `holdout_look` event. Non-promoted variants carry the no-evidence
    sentinel: a 256-variant grid can no longer select against the untouched window."""
    from cosmu.config.settings import GateSettings

    # A denser-signal cyclic-bull regime (longer history + a tighter cycle) so a SINGLE symbol books >= the brut
    # per-cell min-trades floor (30 of its OWN trades) AND clears its own DSR — under brut, pooling 5 symbols no
    # longer carries a thin per-symbol book over the floor, so the fixture must be honestly trade-dense per cell.
    # beat-BnH is opted out so a champion actually promotes and the champion-only holdout path is exercised.
    market = _trade_dense_market()

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/champion.sqlite3", openrouter_api_key=None,
                           gates=GateSettings(require_beat_buy_and_hold=False)))
    finder = StrategyFinder(settings=store.settings, store=store, market_data=_Bars(market))
    report = finder.find(seed_orb_fvg_spec(), max_variants=10, persist=False)

    assert report.survivors, "the significant-edge fixture must promote a champion (else this test is vacuous)"
    look_ids = [r["ref_id"] for r in store.rows("SELECT ref_id FROM events WHERE kind = 'holdout_look'")]
    assert look_ids, "promoted champions must be audited as holdout_look events"
    assert len(look_ids) == len(set(look_ids))  # one exam look per champion variant — never re-sat
    # BRUT: only a variant with ≥1 passing cell sits the exam, ONCE, per cell. A confirmed survivor has at least
    # one cell whose OWN holdout was scored (real verdict, not the no-evidence sentinel) and is audited.
    for r in report.survivors:
        confirmed = [c for c in r.cells.values() if c.passed and c.holdout_passed]
        assert confirmed, "a survivor must have ≥1 cell confirmed on its own holdout"
        assert all(float(c.metrics.holdout_deflated_sharpe) != -0.5 for c in confirmed)
        assert f"{report.strategy_name}:{r.config_tag}" in set(look_ids)
    # a variant with NO passing cell never simulated the exam (the screen ran include_holdout=False).
    non_champions = [r for r in report.leaderboard if not r.gate_passed]
    for r in non_champions:
        assert r.holdout_passed is False
