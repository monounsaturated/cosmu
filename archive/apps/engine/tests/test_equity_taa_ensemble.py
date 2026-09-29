# Offline, deterministic test for the survivor-ensemble machinery (no cache). We monkeypatch the member adapters
# with synthetic streams (same mean, DIFFERENT phase) so the 1/N blend's diversification — lower vol -> higher
# Sharpe than any single member — is exercised + pinned without the equities cache.

from __future__ import annotations

import math

from cosmu.research import equity_taa_cohort as cohort
from cosmu.research import equity_taa_ensemble as ens
from cosmu.research.equity_taa_cohort import StratStreams


def _months(n: int):
    out, m = [], (2004, 1)
    for _ in range(n):
        out.append(m)
        t = m[0] * 12 + (m[1] - 1) + 1
        m = (t // 12, t % 12 + 1)
    return out


def _member(key: str, phase: float) -> StratStreams:
    n = 240
    # same positive mean + amplitude, DIFFERENT phase -> the 1/N average partially cancels -> lower vol.
    net = [0.012 + 0.03 * math.sin(i * 0.6 + phase) for i in range(n)]
    bench = [0.004 + 0.01 * math.sin(i * 0.5) for i in range(n)]
    return StratStreams(key, f"member {key}", _months(n), net, bench)


def _fake_members():
    keys = ["daa", "vaa", "accel_dual_momentum", "paa", "faber_gtaa", "risk_parity", "tsmom_trend", "haa"]
    return {k: (lambda k=k, ph=i * 0.9: _member(k, ph)) for i, k in enumerate(keys)}


def _fake_null():
    n = 240
    flat = [0.0008 * math.sin(i) for i in range(n)]
    return StratStreams("buy_hold_spy", "Buy & Hold SPY (NULL)", _months(n), flat, flat)


def test_ensemble_diversification_beats_members(monkeypatch):
    monkeypatch.setattr(ens, "_MEMBER_ADAPTERS", _fake_members())
    monkeypatch.setattr(cohort, "_s_spy_null", _fake_null)
    v = ens.run(persist=False)

    ens_rows = [r for r in v.rows if r.kind == "ensemble"]
    member_rows = [r for r in v.rows if r.kind == "member"]
    assert len(ens_rows) == 3  # core3, defensive4, all7 all built
    assert member_rows  # the strict reference members are present

    # The diversification free lunch: the best ensemble's annualized Sharpe exceeds the best single member's
    # (out-of-phase members partially cancel -> lower vol -> higher Sharpe).
    best_ens_sr = max(r.ann_sharpe for r in ens_rows)
    best_mem_sr = max(r.ann_sharpe for r in member_rows)
    assert best_ens_sr > best_mem_sr, (best_ens_sr, best_mem_sr)

    # The null disconfirmer is present and never promoted.
    null = next(r for r in v.rows if r.kind == "null")
    assert not null.promoted_strict


def test_ensemble_deterministic(monkeypatch):
    monkeypatch.setattr(ens, "_MEMBER_ADAPTERS", _fake_members())
    monkeypatch.setattr(cohort, "_s_spy_null", _fake_null)
    a = {(r.name, r.deflated_sharpe_prob, r.holdout_dsr) for r in ens.run(persist=False).rows}
    b = {(r.name, r.deflated_sharpe_prob, r.holdout_dsr) for r in ens.run(persist=False).rows}
    assert a == b
