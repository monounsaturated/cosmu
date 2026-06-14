# Offline, deterministic tests for the equity TAA cohort MACHINERY (no cache, no network). We monkeypatch
# build_streams() with hand-built synthetic monthly streams so the full run() path — real purged+embargoed
# holdout, trial registration, promote_cohort (DSR/BH-FDR/PBO/holdout), and the two-bar verdict classification —
# is exercised without the equities cache. The adapters that read the cache (_s_daa etc.) are integration-tested
# by running the module on real data; here we pin the gate wiring + the disconfirmer logic.

from __future__ import annotations

import math

from cosmu.research import equity_taa_cohort as taa


def _months(n: int, start=(2004, 1)) -> list[tuple[int, int]]:
    out, m = [], start
    for _ in range(n):
        out.append(m)
        total = m[0] * 12 + (m[1] - 1) + 1
        m = (total // 12, total % 12 + 1)
    return out


def _stream(name, label, n, *, mean, vol, bench_mean, disconf=False) -> taa.StratStreams:
    """A deterministic monthly stream: a low-vol oscillation around `mean` (no RNG -> reproducible). `bench_mean`
    sets the SPY benchmark level so we can control the beat-B&H outcome."""
    months = _months(n)
    net = [mean + vol * math.sin(i * 1.3) for i in range(n)]          # positive mean, bounded vol -> high SRobs
    bench = [bench_mean + vol * math.sin(i * 0.7) for i in range(n)]  # the SPY reference stream
    return taa.StratStreams(name, label, months, net, bench, is_disconfirmer=disconf)


def _fake_cohort() -> list[taa.StratStreams]:
    return [
        # strong + beats its (lower) benchmark -> should clear the STRICT gate
        _stream("strong_beats_spy", "Strong (beats SPY)", 240, mean=0.014, vol=0.012, bench_mean=0.006),
        # strong risk-adjusted but does NOT out-return its (higher) benchmark -> DSR+holdout, fails only beat-B&H
        _stream("strong_lags_spy", "Strong (lags SPY raw)", 240, mean=0.011, vol=0.012, bench_mean=0.030),
        # a third real-ish member so FDR/PBO have a cohort
        _stream("medium", "Medium", 220, mean=0.010, vol=0.014, bench_mean=0.008),
        # a NULL disconfirmer: bench == net (can never beat itself) and near-zero edge
        taa.StratStreams("null_flat", "Flat null", _months(240),
                         [0.0008 * math.sin(i) for i in range(240)],
                         [0.0008 * math.sin(i) for i in range(240)], is_disconfirmer=True),
    ]


def test_run_promotes_strong_refuses_null(monkeypatch):
    monkeypatch.setattr(taa, "build_streams", _fake_cohort)
    v = taa.run(persist=False)

    assert v.verdict in {"PASS-STRICT", "PASS-DSR-HOLDOUT"}
    by = {r.name: r for r in v.rows}
    assert set(by) == {"strong_beats_spy", "strong_lags_spy", "medium", "null_flat"}

    # The strong-and-beats-benchmark stream clears the FULL strict gate.
    assert by["strong_beats_spy"].promoted_strict, by["strong_beats_spy"].reasons
    assert by["strong_beats_spy"].holdout_dsr > 0

    # The strong-but-lagging stream clears every overfitting guard but fails ONLY beat-B&H -> DSR+holdout survivor.
    assert by["strong_lags_spy"].survived_dsr_holdout
    assert not by["strong_lags_spy"].promoted_strict
    assert by["strong_lags_spy"].reasons == ["buy_and_hold"]

    # The flat NULL disconfirmer must NOT be promoted, and must never appear in a survivor list.
    assert not by["null_flat"].promoted_strict
    assert "null_flat" not in v.strict_survivors
    assert "null_flat" not in v.dsr_holdout_survivors

    # Cohort PBO is a real probability; no threshold was changed.
    assert 0.0 <= v.cohort_pbo <= 1.0


def test_run_is_deterministic(monkeypatch):
    monkeypatch.setattr(taa, "build_streams", _fake_cohort)
    a = taa.run(persist=False)
    b = taa.run(persist=False)
    fa = {(r.name, r.deflated_sharpe_prob, r.holdout_dsr, r.promoted_strict) for r in a.rows}
    fb = {(r.name, r.deflated_sharpe_prob, r.holdout_dsr, r.promoted_strict) for r in b.rows}
    assert fa == fb
    assert a.strict_survivors == b.strict_survivors


def test_insample_total_excludes_holdout():
    # A strictly-positive stream's in-sample total return is positive and uses only the in-sample slice.
    stream = [0.01] * 200
    total = taa._insample_total(stream)
    assert total > 0
    # in-sample is the first ~80% minus the 12m embargo, never the full 200 -> total < compounding all 200.
    assert total < (1.01 ** 200 - 1.0)
