# Light offline test for the H1 aggressive-trade-imbalance research harness. NO network: it builds a tiny
# synthetic FlowBar stream with a PLANTED fade edge (a sustained one-sided aggressor burst followed by a
# snap-back) and asserts the harness end-to-end:
#   - the signal/sim generate trades
#   - the planted edge beats its OWN shuffle-null (the sign carries real info here)
#   - the locked BRUT Gate path runs and (on this generous synthetic) promotes
# This guards the reusable harness plumbing; the REAL-data verdict lives in the committed report.

from __future__ import annotations

import importlib.util
import random
from datetime import UTC, datetime
from pathlib import Path

from cosmu.config.settings import GateSettings
from cosmu.data.intraday_aggtrades import FlowBar

_HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "research" / "h1_orderflow_imbalance_2026_06_28.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("h1_harness", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["h1_harness"] = mod  # so dataclasses defined in the module resolve their own __module__
    spec.loader.exec_module(mod)
    return mod


def _synthetic_bars(h1) -> list[FlowBar]:
    rng = random.Random(1)
    bars: list[FlowBar] = []
    price = 100.0
    open_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    cycle = 40
    for i in range(3000):
        phase = i % cycle
        drift = rng.gauss(0, 0.0004)
        if phase < 20:  # sustained aggressive-buy overshoot fills the trailing window
            buy, sell = 900.0, 100.0
            drift += 0.0010
        elif phase < 26:  # the snap-back down (the fade pays here)
            buy, sell = 200.0, 200.0
            drift += -0.0035
        else:
            buy = max(1.0, rng.gauss(200, 50))
            sell = max(1.0, rng.gauss(200, 50))
        price *= 1.0 + drift
        bars.append(FlowBar(open_ms=open_ms + i * 60_000, close=price, buy_vol=buy, sell_vol=sell, n_trades=int(buy + sell)))
    return bars


def test_h1_planted_edge_beats_shuffle_and_runs_gate():
    h1 = _load_harness()
    bars = _synthetic_bars(h1)
    cell = h1._run_cell("SYNTH", bars, maker_round_trip_bps=4.0, gates=GateSettings())
    assert cell is not None
    assert cell.n_trades > 0
    # planted sign-information must beat the shuffle-null
    assert cell.net_edge > cell.shuffle_mean_net_edge
    assert cell.shuffle_p_value < 0.5


def test_h1_rolling_imbalance_matches_naive():
    h1 = _load_harness()
    rng = random.Random(7)
    bars = [
        FlowBar(open_ms=i * 60_000, close=100.0, buy_vol=max(1.0, rng.gauss(200, 80)),
                sell_vol=max(1.0, rng.gauss(200, 80)), n_trades=10)
        for i in range(400)
    ]
    w = 15
    roll = h1._trailing_imbalance(bars, w)
    naive: list[float | None] = [None] * len(bars)
    for t in range(w - 1, len(bars)):
        b = sum(x.buy_vol for x in bars[t - w + 1 : t + 1])
        s = sum(x.sell_vol for x in bars[t - w + 1 : t + 1])
        tot = b + s
        naive[t] = (b - s) / tot if tot > 0 else 0.0
    mx = max(abs((roll[i] or 0.0) - (naive[i] or 0.0)) for i in range(len(bars)))
    assert mx < 1e-9
