# Offline, deterministic test for the managed-futures overlay machinery (no cache). We monkeypatch the floor +
# satellite + benchmark monthly streams with synthetic data (the MF sleeve NEGATIVELY correlated to the floor) so
# the diversification logic — an 80/20 blend with lower vol -> higher Sharpe than the floor alone — is pinned.

from __future__ import annotations

import math

from cosmu.research import equity_managed_futures_overlay as mfo


def _by_month(values):
    out, m = {}, (2010, 1)
    for v in values:
        out[m] = v
        t = m[0] * 12 + (m[1] - 1) + 1
        m = (t // 12, t % 12 + 1)
    return out


def _floor():
    # positive-mean, moderate-vol floor
    return _by_month([0.011 + 0.02 * math.sin(i * 0.7) for i in range(120)])


def _mf(_sym):
    # positive-mean satellite, OUT OF PHASE with the floor (negative correlation) -> the blend cancels vol
    return _by_month([0.006 - 0.02 * math.sin(i * 0.7) for i in range(120)])


def _spy():
    return _by_month([0.008 + 0.03 * math.sin(i * 0.4) for i in range(120)])


def test_managed_futures_blend_diversifies(monkeypatch):
    monkeypatch.setattr(mfo, "_defensive5_by_month", _floor)
    monkeypatch.setattr(mfo, "_mf_monthly", _mf)
    monkeypatch.setattr(mfo, "_spy_monthly", _spy)
    v = mfo.run(persist=False)

    by = {r.name: r for r in v.rows}
    # for each MF sleeve, the 80/20 blend must out-Sharpe the floor on the same window (the diversification win)
    for sym in mfo.MF_ETFS:
        base = by[f"def5_on_{sym.lower()}_win"]
        blend = by[f"def5_plus20_{sym.lower()}"]
        assert blend.ann_sharpe > base.ann_sharpe, (sym, blend.ann_sharpe, base.ann_sharpe)
    assert "REAL diversifier" in v.headline


def test_overlay_deterministic(monkeypatch):
    monkeypatch.setattr(mfo, "_defensive5_by_month", _floor)
    monkeypatch.setattr(mfo, "_mf_monthly", _mf)
    monkeypatch.setattr(mfo, "_spy_monthly", _spy)
    a = {(r.name, r.dsr, r.holdout_dsr) for r in mfo.run(persist=False).rows}
    b = {(r.name, r.dsr, r.holdout_dsr) for r in mfo.run(persist=False).rows}
    assert a == b
