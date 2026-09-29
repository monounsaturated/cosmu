# Light offline test for the H1b LOW-TURNOVER aggressive-trade-imbalance research harness. NO network: it builds
# a tiny synthetic 1m FlowBar stream with a PLANTED fade edge (a sustained one-sided aggressor burst followed by
# a snap-back, scaled to the COARSE bar/hold), resamples 1m->15m, and asserts the harness end-to-end:
#   - the 1m->15m resample sums volume + carries the last close correctly, never zero-fills a gap minute
#   - the signal/sim generate trades on the coarse bars
#   - the planted edge beats its OWN shuffle-null (the sign carries real info here)
#   - the locked BRUT Gate path runs (on this generous synthetic it promotes)
# This guards the reusable harness plumbing + the new resampler; the REAL-data verdict lives in the report.

from __future__ import annotations

import importlib.util
import random
from datetime import UTC, datetime
from pathlib import Path

from cosmu.config.settings import GateSettings
from cosmu.data.intraday_aggtrades import FlowBar

_HARNESS = (
    Path(__file__).resolve().parents[1] / "scripts" / "research" / "h1b_orderflow_lowturnover_2026_06_28.py"
)


def _load_harness():
    spec = importlib.util.spec_from_file_location("h1b_harness", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["h1b_harness"] = mod  # so dataclasses defined in the module resolve their own __module__
    spec.loader.exec_module(mod)
    return mod


def test_h1b_resample_sums_volume_and_carries_last_close():
    h1b = _load_harness()
    # 30 contiguous 1m bars -> two 15m coarse bars; volumes must sum, close must be the last 1m close per bucket.
    bars = [
        FlowBar(open_ms=i * 60_000, close=100.0 + i, buy_vol=float(i + 1), sell_vol=2.0, n_trades=3)
        for i in range(30)
    ]
    coarse = h1b.resample_flow_bars(bars, 15)
    assert len(coarse) == 2
    # bucket 0 = minutes 0..14 ; bucket 1 = minutes 15..29
    assert coarse[0].buy_vol == sum(i + 1 for i in range(15))
    assert coarse[1].buy_vol == sum(i + 1 for i in range(15, 30))
    assert coarse[0].sell_vol == 2.0 * 15
    assert coarse[0].close == 100.0 + 14  # last 1m close in the first bucket
    assert coarse[1].close == 100.0 + 29  # last 1m close in the second bucket
    assert coarse[0].n_trades == 3 * 15


def test_h1b_resample_skips_gap_minutes_never_zero_fills():
    h1b = _load_harness()
    # Only two 1m bars present, in DIFFERENT 15m buckets, with empty buckets between -> resample emits exactly the
    # two non-empty coarse bars (the absent buckets are gaps, never zero-filled flat bars).
    bars = [
        FlowBar(open_ms=0, close=100.0, buy_vol=5.0, sell_vol=1.0, n_trades=2),
        FlowBar(open_ms=60 * 60_000, close=110.0, buy_vol=3.0, sell_vol=7.0, n_trades=4),  # minute 60 -> 4th bucket
    ]
    coarse = h1b.resample_flow_bars(bars, 15)
    assert len(coarse) == 2  # NOT 5 — gaps skipped
    assert coarse[0].open_ms == 0
    assert coarse[1].open_ms == 60 * 60_000


def _synthetic_1m_bars(h1b) -> list[FlowBar]:
    rng = random.Random(7)
    bars: list[FlowBar] = []
    price = 100.0
    open_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    coarse_cycle_bars = h1b.IMB_BARS + h1b.HOLD_BARS + 8
    cycle = coarse_cycle_bars * h1b.BAR_MINUTES
    up_minutes = (h1b.IMB_BARS + 4) * h1b.BAR_MINUTES
    snap_minutes = up_minutes + h1b.HOLD_BARS * h1b.BAR_MINUTES
    n_minutes = cycle * 40
    for i in range(n_minutes):
        phase = i % cycle
        drift = rng.gauss(0, 0.0003)
        if phase < up_minutes:  # sustained aggressive-buy overshoot fills the coarse trailing window
            buy, sell = 900.0, 100.0
            drift += 0.0004
        elif phase < snap_minutes:  # the snap-back down (the fade pays here over the long hold)
            buy, sell = 250.0, 250.0
            drift += -0.0006
        else:
            buy = max(1.0, rng.gauss(200, 50))
            sell = max(1.0, rng.gauss(200, 50))
        price *= 1.0 + drift
        bars.append(FlowBar(open_ms=open_ms + i * 60_000, close=price, buy_vol=buy, sell_vol=sell, n_trades=int(buy + sell)))
    return bars


def test_h1b_planted_edge_beats_shuffle_and_runs_gate():
    h1b = _load_harness()
    coarse = h1b.resample_flow_bars(_synthetic_1m_bars(h1b), h1b.BAR_MINUTES)
    cell = h1b._run_cell("SYNTH", coarse, maker_round_trip_bps=4.0, gates=GateSettings())
    assert cell is not None
    assert cell.n_trades > 0
    # planted sign-information must beat the shuffle-null
    assert cell.net_edge > cell.shuffle_mean_net_edge
    assert cell.shuffle_p_value < 0.5


def test_h1b_rolling_imbalance_matches_naive():
    h1b = _load_harness()
    rng = random.Random(7)
    bars = [
        FlowBar(open_ms=i * 60_000, close=100.0, buy_vol=max(1.0, rng.gauss(200, 80)),
                sell_vol=max(1.0, rng.gauss(200, 80)), n_trades=10)
        for i in range(400)
    ]
    w = h1b.IMB_BARS
    roll = h1b._trailing_imbalance(bars, w)
    naive: list[float | None] = [None] * len(bars)
    for t in range(w - 1, len(bars)):
        b = sum(x.buy_vol for x in bars[t - w + 1 : t + 1])
        s = sum(x.sell_vol for x in bars[t - w + 1 : t + 1])
        tot = b + s
        naive[t] = (b - s) / tot if tot > 0 else 0.0
    mx = max(abs((roll[i] or 0.0) - (naive[i] or 0.0)) for i in range(len(bars)))
    assert mx < 1e-9
