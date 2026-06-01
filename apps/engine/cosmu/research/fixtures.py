# intent: deterministic synthetic bars + alt-data so the edge gate runs offline (CLI demo + tests); inputs: a seed and an `edge` flag; outputs: a market dict + a FixtureAltDataProvider; invariants: with edge=True a genuine social→return relationship exists for the wall to find; with edge=False the social series is pure noise and the gate must STOP.

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint, FixtureAltDataProvider, FixtureNewsProvider, NewsItem
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


# --- Phase 1.5 ablation fixtures -------------------------------------------------------------
# A latent signal drives BOTH next-bar returns AND the alt sources (news strongest), so the
# alt-data arm should beat price-only and the drop-one report should rank news first.

_BULL = (
    "Bitcoin surges as ETF inflows hit record",
    "Major exchange announces partnership and adoption push",
    "Network upgrade approval drives a fresh rally",
)
_BEAR = (
    "Exchange hack triggers a broad selloff",
    "Regulator weighs ban as the market plunges",
    "Large liquidations spark crash fears",
)
_NEUTRAL = (
    "Market trades sideways amid mixed signals",
    "Analysts debate the next move",
    "Volumes hold steady into the weekend",
)


def _make_ablation_symbol(symbol: str, *, edge: bool, seed: int, n: int):
    rng = random.Random(f"abl-{symbol}-{seed}")
    start = datetime(2023, 1, 1, tzinfo=UTC)
    # Mean-reverting (AR(1)) latent so it oscillates around 0 → a sideways market (buy-and-hold ~flat)
    # where timing matters and the news filter can add edge by avoiding the down-latent stretches.
    latent: list[float] = []
    level = 0.0
    for _ in range(n):
        level = 0.88 * level + rng.gauss(0, 0.5)
        latent.append(level)

    # Demean the deterministic edge so the asset is driftless (buy-and-hold ≈ flat regardless of
    # seed luck). All the return then sits in *timing* the latent — which the alt arm can exploit
    # by staying out of the down-latent stretches that buy-and-hold must eat.
    raw_edge = [0.03 * math.tanh(latent[i - 1] if i > 0 else 0.0) if edge else 0.0 for i in range(n)]
    mu = sum(raw_edge) / n

    price = 100.0
    bars: list[Bar] = []
    funding: list[AltDataPoint] = []
    fear_greed: list[AltDataPoint] = []
    news: list[NewsItem] = []
    for i in range(n):
        ret = (raw_edge[i] - mu) + rng.gauss(0, 0.012)
        open_ = price
        price = max(0.01, price * (1 + ret))
        ts = start + timedelta(days=i)
        bars.append(
            Bar(
                ts=ts,
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(max(open_, price) * 1.005, 6))),
                low=Decimal(str(round(min(open_, price) * 0.995, 6))),
                close=Decimal(str(round(price, 6))),
                volume=Decimal("1000000"),
            )
        )
        si = latent[i]
        if edge and si > 0.4:
            headline = rng.choice(_BULL)
        elif edge and si < -0.4:
            headline = rng.choice(_BEAR)
        else:
            headline = rng.choice(_NEUTRAL)
        news.append(NewsItem(ts=ts, available_at=ts, headline=headline))
        funding.append(AltDataPoint(ts=ts, available_at=ts, value=round(-0.0002 * si + rng.gauss(0, 0.00005), 8)))
        fg_val = (50.0 - 20.0 * math.tanh(si)) if edge else 50.0  # contrarian: fear when upside latent
        fear_greed.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=round(fg_val, 2)))
    return bars, funding, fear_greed, news


def synthetic_ablation_inputs(*, edge: bool = True, seed: int = 7, n: int = 600):
    market: dict[str, list[Bar]] = {}
    alt_series: dict[tuple[str, str], list[AltDataPoint]] = {}
    news: dict[str, list[NewsItem]] = {}
    for symbol in _SYMBOLS:
        bars, funding, fear_greed, items = _make_ablation_symbol(symbol, edge=edge, seed=seed, n=n)
        market[symbol] = bars
        alt_series[(symbol, "funding_rate")] = funding
        alt_series[(symbol, "fear_greed")] = fear_greed
        news[symbol] = items
    return market, FixtureAltDataProvider(alt_series), FixtureNewsProvider(news)
