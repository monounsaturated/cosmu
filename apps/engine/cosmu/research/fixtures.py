# intent: deterministic synthetic bars + alt-data so the edge gate runs offline (CLI demo + tests); inputs: a seed and an `edge` flag; outputs: a market dict + a FixtureAltDataProvider; invariants: with edge=True a genuine social→return relationship exists for the wall to find; with edge=False the social series is pure noise and the gate must STOP.

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint, FixtureAltDataProvider, FixtureNewsProvider, NewsItem
from cosmu.data.market import Bar

_SYMBOLS = ("BTCUSDT", "ETHUSDT", "ALTUSDT")


# --- Adversarial controls (label-permutation nulls) ------------------------------------------
# Prove the gate measures a real signal→return relationship and not an artefact (look-ahead,
# the feature's own autocorrelation, or undeflated multiple-testing). Take EDGE-BEARING inputs and
# permute each feature's VALUES across time while keeping every (ts, available_at) stamp — and the
# entire return path — fixed. The marginal distribution of every feature is preserved exactly; only
# its temporal alignment to returns is destroyed. Under this null a non-leaky gate MUST STOP. Any
# PASS on shuffled data is spurious and marks a leak to fix (never a test to weaken).


def shuffle_alt_provider(provider: FixtureAltDataProvider, *, seed: int = 0) -> FixtureAltDataProvider:
    """Return a fresh provider with each (symbol, metric) series' VALUES permuted across time. Stamps
    (ts/available_at) are untouched, so point-in-time alignment still works — the value landing on each
    bar is now a random draw from the same distribution, uncorrelated with that bar's return. The input
    provider is not mutated."""
    out: dict[tuple[str, str], list[AltDataPoint]] = {}
    for key, points in provider.series.items():
        rng = random.Random(f"shuffle-alt-{seed}-{key[0]}-{key[1]}")  # per-series → independent permutations
        values = [p.value for p in points]
        rng.shuffle(values)
        out[key] = [AltDataPoint(ts=p.ts, available_at=p.available_at, value=v) for p, v in zip(points, values)]
    return FixtureAltDataProvider(out)


def shuffle_news_provider(provider: FixtureNewsProvider, *, seed: int = 0) -> FixtureNewsProvider:
    """Companion to [shuffle_alt_provider] for headlines: permute each symbol's headlines across its
    timestamps, breaking any news→return relationship while preserving the headline-content distribution."""
    out: dict[str, list[NewsItem]] = {}
    for symbol, items in provider.news.items():
        rng = random.Random(f"shuffle-news-{seed}-{symbol}")
        heads = [it.headline for it in items]
        rng.shuffle(heads)
        out[symbol] = [NewsItem(ts=it.ts, available_at=it.available_at, headline=h) for it, h in zip(items, heads)]
    return FixtureNewsProvider(out)


_NULL_SYMBOLS = {"BTCUSDT": 30000.0, "ETHUSDT": 2000.0, "BNBUSDT": 300.0, "SOLUSDT": 25.0, "XRPUSDT": 0.5}


def permutation_null_market(
    *, correlated: bool = False, n: int = 400, seed: int = 13
) -> dict[str, list[Bar]]:
    """A label-permutation null for the price/TA FINDER (the companion to [shuffle_alt_provider] for the
    alt-data wall). Each symbol's bar-to-bar RETURNS are drawn, then PERMUTED in time before the price path
    is rebuilt: the marginal return distribution (drift, vol, fat tails) is preserved exactly, but every
    temporal structure a TA strategy could monetize — momentum, mean-reversion, breakout follow-through — is
    destroyed. There is NO signal→return relationship, so an honest finder MUST promote 0 survivors no matter
    how dense the grid; any survivor is a multiple-testing / look-ahead leak to fix (never a test to weaken).

    `correlated=True` drives every symbol from ONE shared shuffled factor (≈92% common beta), so the whole
    grid is highly cross-correlated — the adversarial regime where a naive trial count would inflate and the
    cluster / effective-N machinery has to do the work. `correlated=False` shuffles each symbol independently.
    Deterministic for a fixed (correlated, n, seed); pure-Python."""
    base = datetime(2023, 1, 1, tzinfo=UTC)
    shared: list[float] | None = None
    if correlated:
        fr = random.Random(f"perm-null-factor-{seed}")
        shared = [fr.gauss(0.0004, 0.012) for _ in range(n)]
        fr.shuffle(shared)  # shuffle the shared factor → no temporal signal survives
    out: dict[str, list[Bar]] = {}
    for sym, p0 in _NULL_SYMBOLS.items():
        rng = random.Random(f"perm-null-{seed}-{sym}")  # str seed is process-stable
        if shared is not None:
            rets = [0.92 * shared[i] + rng.gauss(0, 0.003) for i in range(n)]
        else:
            rets = [rng.gauss(0.0003, 0.012) for _ in range(n)]
            rng.shuffle(rets)  # permute this symbol's own labels
        bars: list[Bar] = []
        p = p0
        for r in rets:
            o = p
            p = max(1e-6, p * (1 + r))
            hi = max(o, p) * (1 + abs(rng.gauss(0, 0.002)))
            lo = min(o, p) * (1 - abs(rng.gauss(0, 0.002)))
            bars.append(
                Bar(
                    ts=base + timedelta(hours=len(bars)),
                    open=Decimal(str(o)),
                    high=Decimal(str(hi)),
                    low=Decimal(str(lo)),
                    close=Decimal(str(p)),
                    volume=Decimal("1000"),
                )
            )
        out[sym] = bars
    return out


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


def edge_bearing_screen_market(*, seed: int = 3, n: int = 900) -> dict[str, list[Bar]]:
    """A deterministic, EDGE-BEARING crypto market for the research/evolution SCREEN — designed so a trend/
    momentum seed clears the out-of-reach gate with midpoint params, exercising the survivor track-open path
    end-to-end. Construction: long bull regimes punctuated by short pullbacks, with positively autocorrelated
    returns (a real momentum signal a trend strategy can monetize). NO synthetic return is injected into the
    backtest — the bars themselves carry the edge and the deterministic backtest/scorer judge them honestly.
    The price path stays positive in the bull stretches across MULTIPLE regimes so regime_returns has breadth
    (used by the survival features and the live-eligibility passport). Reproducible for a fixed (seed, n)."""
    rng = random.Random(f"edge-screen-{seed}")
    start = datetime(2021, 1, 1, tzinfo=UTC)
    price = 100.0
    trend = 0.0
    bars: list[Bar] = []
    for i in range(n):
        drift = 0.004 if i % 120 < 80 else -0.001  # ~2/3 bull, 1/3 pullback — regime breadth, net up
        ret = drift + 0.3 * trend + rng.gauss(0, 0.012)  # momentum: returns positively autocorrelated
        trend = ret
        open_ = price
        price = max(0.01, price * (1 + ret))
        bars.append(
            Bar(
                ts=start + timedelta(days=i),
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(max(open_, price) * 1.004, 6))),
                low=Decimal(str(round(min(open_, price) * 0.996, 6))),
                close=Decimal(str(round(price, 6))),
                volume=Decimal("5000000"),
            )
        )
    return {symbol: bars for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")}


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


# --- Phase 1.6 cross-asset fixtures ----------------------------------------------------------
# The thesis under test: does COMBINING asset classes beat any single one? Construction: a single
# global RISK-REGIME latent drives a drag across crypto AND equity at the same times (risk-off bars
# hurt everything you hold). Each asset ALSO has its own local latent (revealed by its own
# news/funding/fear-greed — the single-asset alt edge). The global regime is NOT visible in any one
# asset's own data; it is priced by PREDICTION-MARKET odds (risk_on) and FRED MACRO (macro_regime).
# So the cross-asset arm — which adds those transfer features — can step out of the global risk-off
# stretches that single-asset arms must eat. With edge=False the regime is pure noise → no transfer
# edge → the gate must STOP.

_XA_CRYPTO = ("BTCUSDT", "ETHUSDT")
_XA_EQUITY = ("SPY", "QQQ")


def _xa_asset(symbol: str, *, klass: str, edge: bool, seed: int, n: int, risk: list[float]) -> tuple[list[Bar], list[AltDataPoint], list[AltDataPoint], list[NewsItem]]:
    rng = random.Random(f"xa-{klass}-{symbol}-{seed}")
    start = datetime(2023, 1, 1, tzinfo=UTC)
    # Own (idiosyncratic) latent — decorrelated across assets, so combining classes diversifies timing.
    own: list[float] = []
    level = 0.0
    for _ in range(n):
        level = 0.88 * level + rng.gauss(0, 0.5)
        own.append(level)
    raw_edge = [0.002 * math.tanh(own[i - 1] if i > 0 else 0.0) if edge else 0.0 for i in range(n)]
    mu = sum(raw_edge) / n  # demean own-timing so buy-and-hold is driftless from it alone

    price = 100.0
    bars: list[Bar] = []
    funding: list[AltDataPoint] = []
    fear_greed: list[AltDataPoint] = []
    news: list[NewsItem] = []
    for i in range(n):
        # Global RISK REGIME: a symmetric drift — positive in risk-on, negative in risk-off — that hits every
        # asset at once and is NOT visible in any single asset's own data (only via the cross-asset transfer
        # features). Symmetric + zero-mean regime ⇒ buy-and-hold ≈ flat (it can't time the regime); the
        # cross-asset arm captures the risk-on drift and sidesteps the risk-off drift.
        prior_risk = risk[i - 1] if i > 0 else 0.0
        regime = (0.013 if prior_risk > 0.0 else -0.013) if edge else 0.0
        ret = regime + (raw_edge[i] - mu) + rng.gauss(0, 0.012)
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
        si = own[i]
        if edge and si > 0.4:
            headline = rng.choice(_BULL)
        elif edge and si < -0.4:
            headline = rng.choice(_BEAR)
        else:
            headline = rng.choice(_NEUTRAL)
        news.append(NewsItem(ts=ts, available_at=ts, headline=headline))
        if klass == "crypto":  # funding/fear-greed are crypto-only single-asset alt sources
            funding.append(AltDataPoint(ts=ts, available_at=ts, value=round(-0.0002 * si + rng.gauss(0, 0.00005), 8)))
            fear_greed.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=round((50.0 - 20.0 * math.tanh(si)) if edge else 50.0, 2)))
    return bars, funding, fear_greed, news


def synthetic_cross_asset_inputs(*, edge: bool = True, seed: int = 7, n: int = 600):
    """Two traded classes (crypto + equity) under one global risk regime, with the regime exposed only
    through the cross-asset transfer features (prediction-market `risk_on` + FRED `macro_regime`).
    Returns (market_by_class, alt_provider, news_provider). Deterministic for a fixed (edge, seed, n)."""
    g = random.Random(f"xa-global-{seed}")
    start = datetime(2023, 1, 1, tzinfo=UTC)
    # Fast-switching regime (low AR persistence): a 20-bar price z-score CANNOT track it, so price momentum
    # is a poor proxy — only the lag-1 transfer features (risk_on / macro_regime) time it. That is what makes
    # the cross-asset arm's edge come from the TRANSFER features, not from price the single-asset arms already see.
    risk: list[float] = []
    level = 0.0
    for _ in range(n):
        level = 0.55 * level + g.gauss(0, 0.5)
        risk.append(level)

    market_by_class: dict[str, dict[str, list[Bar]]] = {"crypto": {}, "equity": {}}
    alt_series: dict[tuple[str, str], list[AltDataPoint]] = {}
    news: dict[str, list[NewsItem]] = {}
    for klass, symbols in (("crypto", _XA_CRYPTO), ("equity", _XA_EQUITY)):
        for symbol in symbols:
            bars, funding, fg, items = _xa_asset(symbol, klass=klass, edge=edge, seed=seed, n=n, risk=risk)
            market_by_class[klass][symbol] = bars
            news[symbol] = items
            if klass == "crypto":
                alt_series[(symbol, "funding_rate")] = funding
                alt_series[(symbol, "fear_greed")] = fg

    # Cross-asset transfer series (market-wide, key "MARKET"), each causal: index i encodes risk[i-1].
    # Each point at index i encodes the CURRENT regime risk[i], known at day i. The next day's return
    # carries regime f(risk[i]); a signal computed from risk_on[i] enters at day i+1 (causal, no look-ahead),
    # so the transfer feature is an EXACT lead on the regime drift while a 20-bar price z-score is not.
    risk_on: list[AltDataPoint] = []
    macro: list[AltDataPoint] = []
    for i in range(n):
        ts = start + timedelta(days=i)
        if edge:
            ron = round(min(1.0, max(0.0, 0.5 + 0.5 * math.tanh(risk[i]))), 4)  # prediction-market YES odds in [0,1]
            mac = round(math.tanh(risk[i]) + g.gauss(0, 0.05), 4)               # FRED regime tag (noisier proxy)
        else:
            ron = round(g.random(), 4)
            mac = round(g.gauss(0, 1), 4)
        risk_on.append(AltDataPoint(ts=ts, available_at=ts, value=ron))
        macro.append(AltDataPoint(ts=ts, available_at=ts, value=mac))
    # Key the prediction-market transfer series under the CANONICAL name the gate now requests
    # (gate.py: fetch_series("MARKET","pm_risk_on")) so the direct-fixture path matches the live/store path,
    # where ingest banks it as "pm_risk_on". (Was "risk_on" — which hid the P0 name-split bug offline.)
    alt_series[("MARKET", "pm_risk_on")] = risk_on
    alt_series[("MARKET", "macro_regime")] = macro

    return market_by_class, FixtureAltDataProvider(alt_series), FixtureNewsProvider(news)
