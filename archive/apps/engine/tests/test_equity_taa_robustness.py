# Offline, deterministic test for the TAA replicability machinery (no cache). We monkeypatch _build_grid with
# synthetic streams so run()'s scoring + replicability aggregation is pinned without the equities cache. The
# real-data variant generators are integration-tested by running the module.

from __future__ import annotations

import math

from cosmu.research import equity_taa_robustness as rob
from cosmu.research.equity_taa_cohort import StratStreams


def _months(n: int):
    out, m = [], (2004, 1)
    for _ in range(n):
        out.append(m)
        t = m[0] * 12 + (m[1] - 1) + 1
        m = (t // 12, t % 12 + 1)
    return out


def _strong(label, mean=0.014):
    n = 240
    net = [mean + 0.012 * math.sin(i * 1.3) for i in range(n)]
    bench = [0.006 + 0.012 * math.sin(i * 0.7) for i in range(n)]
    return StratStreams("test", label, _months(n), net, bench)


def _weak(label):
    n = 240
    flat = [0.0008 * math.sin(i) for i in range(n)]
    return StratStreams("test", label, _months(n), flat, flat)


def test_replicability_fraction_and_verdict(monkeypatch):
    # 3 strong (clear) + 1 weak (fails) -> 75% replicability -> REPLICABLE (>=70%).
    grid = {"test": [_strong("fee=1 shift=0 a"), _strong("fee=2 shift=0 b"),
                     _strong("fee=3 shift=0 c"), _weak("fee=5 shift=0 d")]}
    monkeypatch.setattr(rob, "_build_grid", lambda: grid)
    out = rob.run()
    r = out["test"]
    assert r.n_variants == 4
    assert r.n_clear == 3
    assert r.replicability == 0.75
    assert r.canonical_clears  # canonical = the "fee=1 shift=0" variant, which is strong
    # the weak variant must be flagged not-clear with a real reason
    weak = next(v for v in r.variants if v.label.endswith("d"))
    assert not weak.clears and weak.reasons


def test_all_fragile_when_all_weak(monkeypatch):
    grid = {"test": [_weak("fee=1 shift=0 a"), _weak("fee=2 shift=0 b"), _weak("fee=3 shift=0 c")]}
    monkeypatch.setattr(rob, "_build_grid", lambda: grid)
    out = rob.run()
    assert out["test"].n_clear == 0
    assert out["test"].replicability == 0.0
