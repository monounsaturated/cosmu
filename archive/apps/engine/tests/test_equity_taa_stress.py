# Offline, deterministic tests for the equity-TAA WORST-REGIME stress harness (no cache, no network, no RNG).
# We drive the pure functions with hand-built monthly streams so the whole instrument — vol-regime labelling
# (PIT), worst-regime (minimum, not average) Sharpe, the LTCM forced-exit re-pricing, K-bar feasibility, and the
# stress-regime correlation spike — is exercised without the equities cache. The adapters that read the cache are
# integration-tested by running the module on real data (COSMU_EQUITY_CACHE set); here we pin the math + flags.
#
# Invariant under test (the whole point): the Gate scores the AVERAGE edge; the harness must surface a negative
# WORST regime that the average hides, a forced exit that erases the stress-regime edge, and correlations that
# collapse to ~1 under stress. None of this touches a Gate constant.

from __future__ import annotations

import math

from cosmu.research import equity_taa_cohort as taa
from cosmu.research import equity_taa_stress as st


def _months(n: int, start: tuple[int, int] = (2004, 1)) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    m = start
    for _ in range(n):
        out.append(m)
        total = m[0] * 12 + (m[1] - 1) + 1
        m = (total // 12, total % 12 + 1)
    return out


# --------------------------------------------------------------------------------------------------------------
# Vol-regime labelling
# --------------------------------------------------------------------------------------------------------------


def test_trailing_vol_is_point_in_time():
    # The vol the market is IN as month t opens uses ONLY returns before t — mutating a FUTURE bar must not
    # change an earlier month's vol value (no look-ahead).
    base = [0.001 * math.sin(i) for i in range(60)]
    v_at_30 = st._trailing_vol(base, 30, st.VOL_WINDOW)
    mutated = list(base)
    mutated[45] = 0.5  # a huge future shock
    assert st._trailing_vol(mutated, 30, st.VOL_WINDOW) == v_at_30


def test_vol_regime_labels_terciles_and_stress_cluster():
    # Low-vol first half, high-vol second half -> the back months land in the high-vol 'stress' tercile.
    n = 240
    bench = [0.002 * math.sin(i) if i < n // 2 else 0.05 * math.sin(i) for i in range(n)]
    labels = st.vol_regime_labels(bench)
    assert len(labels) == n
    assert set(labels) <= set(st.REGIME_NAMES)
    # roughly equal terciles (each within a sane band of n/3)
    for name in st.REGIME_NAMES:
        assert 50 <= labels.count(name) <= 120
    # the last (high-vol) month is a stress month; the early calm block is mostly calm
    assert labels[-1] == "stress"
    assert labels[:60].count("calm") > labels[:60].count("stress")


# --------------------------------------------------------------------------------------------------------------
# Per-regime Sharpe — minimum, not average
# --------------------------------------------------------------------------------------------------------------


def test_regime_sharpes_split_and_counts():
    returns = [0.01] * 10 + [-0.02] * 10
    labels = ["calm"] * 10 + ["stress"] * 10
    rs = st.regime_sharpes(returns, labels)
    by = {r.regime: r for r in rs}
    assert by["calm"].n_months == 10 and by["stress"].n_months == 10
    assert by["calm"].total_return > 0 and by["stress"].total_return < 0


def test_worst_regime_is_minimum_not_average():
    # A stream that is strongly positive in calm/normal but NEGATIVE in stress: the full-sample (average) Sharpe
    # is positive, yet the worst-regime Sharpe is negative. This is the fragility the Gate cannot see.
    calm = [0.02 + 0.002 * math.sin(i) for i in range(80)]
    normal = [0.012 + 0.002 * math.sin(i) for i in range(80)]
    stress = [-0.03 + 0.002 * math.sin(i) for i in range(80)]
    returns = calm + normal + stress
    labels = ["calm"] * 80 + ["normal"] * 80 + ["stress"] * 80

    full = st._ann_sharpe(returns, st.PERIODS_PER_YEAR)
    wr = st.worst_regime(st.regime_sharpes(returns, labels))
    assert full > 0.0, "the average edge is positive (what the Gate scores)"
    assert wr is not None and wr.regime == "stress"
    assert wr.ann_sharpe < 0.0, "the worst regime is negative (what the Gate hides)"


def test_worst_regime_ignores_thin_regimes():
    # A regime with too few months is not eligible to be 'the worst' (noise, never flagged).
    returns = [0.01] * 100 + [-0.5] * 3
    labels = ["calm"] * 100 + ["stress"] * 3
    wr = st.worst_regime(st.regime_sharpes(returns, labels), min_months=st.MIN_REGIME_MONTHS)
    assert wr is not None and wr.regime == "calm"  # the 3-month stress blip is excluded


# --------------------------------------------------------------------------------------------------------------
# LTCM forced-exit re-pricing
# --------------------------------------------------------------------------------------------------------------


def test_forced_exit_repricing_worsens_stress_only():
    # cost is charged every month (gross-net); re-pricing it at >1x in STRESS months must lower the stress Sharpe
    # and add positive drag; at 1x nothing changes; calm/normal months are untouched.
    n = 60
    labels = (["calm"] * 20 + ["normal"] * 20 + ["stress"] * 20)
    net = [0.01 + 0.004 * math.sin(i) for i in range(n)]  # positive mean, real dispersion -> non-zero Sharpe
    gross = [g + 0.001 for g in net]  # 10 bps monthly rebalance cost everywhere

    fe1 = st.reprice_forced_exit(net, gross, labels, slip_mult=1.0)
    assert fe1 is not None
    assert math.isclose(fe1.stress_sharpe_base, fe1.stress_sharpe_forced, rel_tol=1e-9, abs_tol=1e-9)
    assert fe1.extra_drag_annualized == 0.0

    fe5 = st.reprice_forced_exit(net, gross, labels, slip_mult=5.0, one_sided_penalty=1.5)
    assert fe5.extra_drag_annualized > 0.0
    assert fe5.stress_sharpe_forced < fe5.stress_sharpe_base
    assert fe5.stress_months == 20


def test_forced_exit_none_without_gross():
    labels = ["calm"] * 10 + ["stress"] * 10
    net = [0.01] * 20
    assert st.reprice_forced_exit(net, [], labels) is None
    assert st.reprice_forced_exit(net, [0.01] * 19, labels) is None  # length mismatch


def test_forced_exit_k_bar_feasibility():
    labels = ["calm"] * 10 + ["stress"] * 10
    net = [0.01] * 20
    gross = [g + 0.0005 for g in net]
    # tiny ADV, large book -> cannot clear within 1 bar -> infeasible
    tight = st.reprice_forced_exit(net, gross, labels, k_bars=1, book_notional_usd=1_000_000.0,
                                   adv_usd=1_000_000.0, participation_cap=0.10, stress_liquidity_haircut=0.5)
    assert tight is not None and tight.feasible_within_k is False and tight.bars_to_exit > 1
    # huge ADV -> clears in one bar
    loose = st.reprice_forced_exit(net, gross, labels, k_bars=1, book_notional_usd=50_000.0,
                                   adv_usd=1_000_000_000.0, participation_cap=0.10, stress_liquidity_haircut=0.5)
    assert loose.feasible_within_k is True and loose.bars_to_exit <= 1
    # no capacity inputs -> cannot measure -> None (never a false 'infeasible' flag)
    blind = st.reprice_forced_exit(net, gross, labels)
    assert blind.feasible_within_k is None and math.isnan(blind.bars_to_exit)


# --------------------------------------------------------------------------------------------------------------
# Stress-regime correlation
# --------------------------------------------------------------------------------------------------------------


def test_stress_correlation_spikes_vs_calm():
    # Two books that move differently in calm months but IDENTICALLY in stress months: stress ρ ~ 1, calm ρ lower.
    n = 120
    labels = (["calm", "normal"] * 30 + ["stress"] * 60)
    a = []
    b = []
    for i in range(n):
        if labels[i] == "stress":
            v = -0.02 + 0.001 * i
            a.append(v)
            b.append(v)  # identical under stress -> rank corr 1
        else:
            a.append(math.sin(i * 1.1))
            b.append(math.sin(i * 2.9))  # different rank order -> lower corr
    streams = {"a": a, "b": b}
    stress = st.regime_correlation(streams, labels, "stress")
    calm = st.regime_correlation(streams, labels, "calm")
    assert stress.average_pairwise_correlation > 0.99
    assert stress.average_pairwise_correlation > calm.average_pairwise_correlation
    assert any(p.correlation >= st.CROWDING_RHO for p in stress.pairs)


# --------------------------------------------------------------------------------------------------------------
# Orchestration: analyze_streams flags + verdict
# --------------------------------------------------------------------------------------------------------------


def _vol_bench(n: int) -> list[float]:
    """A benchmark with clear low/high vol clustering so vol_regime_labels produces all three regimes."""
    return [0.002 * math.sin(i) if (i // 12) % 4 != 3 else 0.06 * math.sin(i * 1.7) for i in range(n)]


def _strat(name: str, label: str, months, bench, *, stress_mean: float, calm_mean: float,
           cost: float, disconf: bool = False) -> taa.StratStreams:
    labs = st.vol_regime_labels(bench)
    net, gross = [], []
    for i in range(len(months)):
        base = stress_mean if labs[i] == "stress" else calm_mean
        g = base + 0.008 * math.sin(i * 1.1)
        gross.append(g)
        net.append(g - cost)
    return taa.StratStreams(name, label, months, net, bench, is_disconfirmer=disconf,
                            gross=([] if disconf else gross))


def test_analyze_streams_flags_fragile_and_verdict():
    n = 240
    ms = _months(n)
    bench = _vol_bench(n)
    fragile = _strat("daa", "DAA-like (fragile)", ms, bench, stress_mean=-0.015, calm_mean=0.020, cost=0.0002)
    robust = _strat("vaa", "VAA-like (robust)", ms, bench, stress_mean=0.006, calm_mean=0.012, cost=0.0002)
    v = st.analyze_streams([fragile, robust],
                           adv_usd_by_name={"daa": 1e9, "vaa": 1e9},
                           capital_by_name={"daa": 5e4, "vaa": 5e4})
    by = {r.name: r for r in v.rows}
    # the fragile book: average edge positive, worst-regime negative -> flagged
    assert by["daa"].full_sample_sharpe > 0
    assert by["daa"].worst_regime_sharpe < 0
    assert st.F_WORST_NEG in by["daa"].flags
    assert "daa" in v.flagged
    assert v.verdict == "FRAGILE-SURVIVORS"
    # liquid book + tiny capital -> exit feasible within K bars (not flagged infeasible)
    assert by["daa"].forced_exit is not None and by["daa"].forced_exit.feasible_within_k is True
    assert st.F_EXIT_INFEASIBLE not in by["daa"].flags


def test_analyze_streams_infeasible_exit_flag():
    n = 240
    ms = _months(n)
    bench = _vol_bench(n)
    s = _strat("daa", "DAA-like", ms, bench, stress_mean=0.01, calm_mean=0.012, cost=0.0002)
    # a thin venue: ADV tiny relative to the book -> forced exit cannot clear within 1 bar
    v = st.analyze_streams([s, _strat("vaa", "VAA", ms, bench, stress_mean=0.011, calm_mean=0.012, cost=0.0002)],
                           adv_usd_by_name={"daa": 100_000.0, "vaa": 1e9},
                           capital_by_name={"daa": 10_000_000.0, "vaa": 5e4}, k_bars=1)
    by = {r.name: r for r in v.rows}
    assert by["daa"].forced_exit.feasible_within_k is False
    assert st.F_EXIT_INFEASIBLE in by["daa"].flags
    assert "daa" in v.flagged


def test_disconfirmer_has_no_forced_exit_and_is_not_flagged():
    n = 240
    ms = _months(n)
    bench = _vol_bench(n)
    real = _strat("daa", "DAA", ms, bench, stress_mean=0.01, calm_mean=0.012, cost=0.0002)
    null = _strat("placebo", "PLACEBO", ms, bench, stress_mean=-0.5, calm_mean=-0.5, cost=0.0, disconf=True)
    v = st.analyze_streams([real, null])
    by = {r.name: r for r in v.rows}
    assert by["placebo"].forced_exit is None
    assert by["placebo"].flags == [] or all(f == st.F_CROWDED for f in by["placebo"].flags) is False
    assert "placebo" not in v.flagged


def test_analyze_streams_is_deterministic():
    n = 200
    ms = _months(n)
    bench = _vol_bench(n)
    s1 = _strat("daa", "DAA", ms, bench, stress_mean=-0.02, calm_mean=0.013, cost=0.0002)
    s2 = _strat("vaa", "VAA", ms, bench, stress_mean=0.007, calm_mean=0.012, cost=0.0002)
    a = st.analyze_streams([s1, s2])
    b = st.analyze_streams([s1, s2])
    fa = [(r.name, r.full_sample_sharpe, r.worst_regime_sharpe, tuple(r.flags)) for r in a.rows]
    fb = [(r.name, r.full_sample_sharpe, r.worst_regime_sharpe, tuple(r.flags)) for r in b.rows]
    assert fa == fb and a.verdict == b.verdict


def test_to_markdown_renders_table():
    n = 120
    ms = _months(n)
    bench = _vol_bench(n)
    s = _strat("daa", "DAA", ms, bench, stress_mean=-0.02, calm_mean=0.013, cost=0.0002)
    md = st.to_markdown(st.analyze_streams([s, _strat("vaa", "VAA", ms, bench, stress_mean=0.007,
                                                      calm_mean=0.012, cost=0.0002)]))
    assert "WORST-regime SR" in md and "| DAA |" in md and "Verdict:" in md


# --------------------------------------------------------------------------------------------------------------
# run() wiring + the inert gross field
# --------------------------------------------------------------------------------------------------------------


def test_run_insufficient_data(monkeypatch):
    monkeypatch.setattr(st, "build_streams", lambda: [])
    v = st.run()
    assert v.verdict == "INSUFFICIENT-DATA"


def test_run_uses_build_streams(monkeypatch):
    n = 200
    ms = _months(n)
    bench = _vol_bench(n)
    cohort = [
        _strat("daa", "DAA", ms, bench, stress_mean=-0.02, calm_mean=0.014, cost=0.0002),
        _strat("vaa", "VAA", ms, bench, stress_mean=0.006, calm_mean=0.012, cost=0.0002),
    ]
    monkeypatch.setattr(st, "build_streams", lambda: cohort)
    v = st.run()
    assert v.n_strategies == 2
    assert {r.name for r in v.rows} == {"daa", "vaa"}


def test_gross_field_is_optional_and_defaults_empty():
    # Backward-compat: a StratStreams built the old way (no gross) is valid and inert; the Gate path never reads it.
    s = taa.StratStreams("x", "X", _months(12), [0.01] * 12, [0.01] * 12)
    assert s.gross == []
