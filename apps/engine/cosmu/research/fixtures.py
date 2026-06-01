# intent: deterministic synthetic bars + alt-data so the edge gate runs offline (CLI demo + tests); inputs: a seed and an `edge` flag; outputs: a market dict + a FixtureAltDataProvider; invariants: with edge=True a genuine social→return relationship exists for the wall to find; with edge=False the social series is pure noise and the gate must STOP.

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint, FixtureAltDataProvider
from cosmu.data.market import Bar

_SYMBOLS = ("BTCUSDT", "ETHUSDT", "ALTUSDT")


def _regime_drift(idx: int, n: int) -> float:
    third = n // 3
    if idx < third:
        return 0.002  # bull
    if idx < 2 * third:
        return -0.0015  # bear
    return 0.0  # chop


def _zscore(values: list[float], idx: int, lookback: int = 30) -> float:
    if idx < lookback:
        return 0.0
    window = values[idx - lookback : idx]
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    sd = var**0.5
    return (values[idx] - mean) / sd if sd else 0.0


def _make_symbol(symbol: str, *, edge: bool, seed: int, n: int) -> tuple[list[Bar], list[AltDataPoint]]:
    rng = random.Random(f"{symbol}-{seed}")  # str seed is process-stable (unlike hash(), which is salted)
    start = datetime(2023, 1, 1, tzinfo=UTC)

    # Social series: a random walk (the "galaxy_score").
    social: list[float] = []
    level = 50.0
    for _ in range(n):
        level = max(1.0, level + rng.gauss(0, 4))
        social.append(level)

    price = 100.0
    bars: list[Bar] = []
    points: list[AltDataPoint] = []
    for i in range(n):
        z = _zscore(social, i - 1) if i > 0 else 0.0  # lagged: known before the bar
        edge_term = 0.02 * z if edge else 0.0
        ret = _regime_drift(i, n) + edge_term + rng.gauss(0, 0.01)
        open_ = price
        price = max(0.01, price * (1 + ret))
        high = max(open_, price) * 1.005
        low = min(open_, price) * 0.995
        ts = start + timedelta(days=i)
        bars.append(
            Bar(
                ts=ts,
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(high, 6))),
                low=Decimal(str(round(low, 6))),
                close=Decimal(str(round(price, 6))),
                volume=Decimal("1000000"),
            )
        )
        points.append(AltDataPoint(ts=ts, available_at=ts, value=round(social[i], 4)))
    return bars, points


def synthetic_gate_inputs(*, edge: bool = True, seed: int = 7, n: int = 600) -> tuple[dict[str, list[Bar]], FixtureAltDataProvider]:
    market: dict[str, list[Bar]] = {}
    series: dict[tuple[str, str], list[AltDataPoint]] = {}
    for symbol in _SYMBOLS:
        bars, points = _make_symbol(symbol, edge=edge, seed=seed, n=n)
        market[symbol] = bars
        series[(symbol, "galaxy_score")] = points
    return market, FixtureAltDataProvider(series)
