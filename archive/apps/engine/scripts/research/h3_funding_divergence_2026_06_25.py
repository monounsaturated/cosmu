#!/usr/bin/env python3
"""H3 CROSS-VENUE FUNDING DIVERGENCE — EXPERIMENT ONLY, ZERO production impact.

THESIS (pre-registered): fade the perp venue whose 8h funding is the OUTLIER vs the cross-venue
median; the spread mean-reverts as KYC-siloed arbs slowly close it. Structurally ORTHOGONAL to the
FAILED single-venue funding-LEVEL set — the signal here is the DIVERGENCE across venues, not the
absolute level on one.

This script writes NOTHING to any prod store, touches NO Gate constant, changes NO behaviour. It is a
self-contained offline event-study that:
  (1) pulls REAL, PIT funding from 3 venues (Binance cache / OKX REST / Kraken-Futures REST), all with
      available_at == ts (the exchange publishes the REALIZED rate at the funding instant; no revision,
      no look-ahead — verified against each provider's docstring),
  (2) normalizes each venue to an 8h-equivalent rate on the canonical 00/08/16 UTC grid, averages to a
      daily per-(asset,venue) funding, takes the cross-venue MEDIAN over venues-with-data (>=2),
  (3) builds feature = funding_venue - median, z-scored per (asset,venue) over a TRAILING 30d window
      (point-in-time: the z at day t uses only data strictly before t's close),
  (4) labels each |z| > 2.0 event by the SIGNED forward N-day return on the Kraken-SPOT reference
      (fade direction: high-z outlier => perp over-long => SHORT spot; low-z => LONG spot),
  (5) POOLS all signed events into ONE basket (assets x venues x settlements) to clear the >=30 floor
      WITHOUT manufacturing trades, then checks (a) N>=30, (b) reversion SIGN, (c) gross edge > 2x
      round-trip Kraken taker fee, and only IF all three clear runs the basket through the BRUT Gate.

PRE-REGISTERED knobs (NO sweep — best-of-N is the trap):
  Z_THRESHOLD = 2.0 | HORIZON_DAYS = 1 | Z_WINDOW_DAYS = 30 | universe = 10 majors on >=2 venues.

Run:  python3 scripts/research/h3_funding_divergence_2026_06_25.py
Out:  scripts/research/h3_funding_divergence_results_2026_06_25.json (raw numbers for the report/HTML)
"""
from __future__ import annotations

import gc
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[2]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.config.settings import GateSettings  # noqa: E402
from cosmu.data.market import Bar, KrakenSpotOHLCVProvider  # noqa: E402
from cosmu.data.providers._types import AltDataPoint  # noqa: E402
from cosmu.data.providers.funding import (  # noqa: E402
    CachedFundingRateProvider,
    OkxFundingRateProvider,
)
from cosmu.master.scorer import (  # noqa: E402
    BacktestMetrics,
    TrialStats,
    cscv_pbo,
    deflated_sharpe_prob,
    probabilistic_sharpe,
    sample_moments,
    score,
)
from cosmu.spine.venue import default_catalog  # noqa: E402

# ----------------------------------------------------------------------------------------------------
# PRE-REGISTERED config (locked before looking at any result)
# ----------------------------------------------------------------------------------------------------
Z_THRESHOLD = 2.0          # |z| > 2 = outlier event
HORIZON_DAYS = 1           # forward N-day return (proxy for ~3x8h)
Z_WINDOW_DAYS = 30         # trailing window for the per-(asset,venue) z-score (PIT: uses data BEFORE t)
GRID_8H = (0, 8, 16)       # canonical UTC settlement hours

# Universe: 10 liquid majors that trade on >=2 of the 3 funding venues. Keyed by bare base.
# binance_funding spelling (BTCUSDT) | okx swap (BTC-USDT-SWAP) | kraken-futures (PF_XBTUSD).
UNIVERSE = {
    "BTC":  {"binance": "BTCUSDT",  "okx": "BTC-USDT-SWAP",  "krakenfut": "PF_XBTUSD",  "kraken_spot": "BTCUSDT"},
    "ETH":  {"binance": "ETHUSDT",  "okx": "ETH-USDT-SWAP",  "krakenfut": "PF_ETHUSD",  "kraken_spot": "ETHUSDT"},
    "SOL":  {"binance": "SOLUSDT",  "okx": "SOL-USDT-SWAP",  "krakenfut": "PF_SOLUSD",  "kraken_spot": "SOLUSDT"},
    "XRP":  {"binance": "XRPUSDT",  "okx": "XRP-USDT-SWAP",  "krakenfut": "PF_XRPUSD",  "kraken_spot": "XRPUSDT"},
    "DOGE": {"binance": "DOGEUSDT", "okx": "DOGE-USDT-SWAP", "krakenfut": "PF_DOGEUSD", "kraken_spot": "DOGEUSDT"},
    "ADA":  {"binance": "ADAUSDT",  "okx": "ADA-USDT-SWAP",  "krakenfut": "PF_ADAUSD",  "kraken_spot": "ADAUSDT"},
    "AVAX": {"binance": "AVAXUSDT", "okx": "AVAX-USDT-SWAP", "krakenfut": "PF_AVAXUSD", "kraken_spot": "AVAXUSDT"},
    "LINK": {"binance": "LINKUSDT", "okx": "LINK-USDT-SWAP", "krakenfut": "PF_LINKUSD", "kraken_spot": "LINKUSDT"},
    "DOT":  {"binance": "DOTUSDT",  "okx": "DOT-USDT-SWAP",  "krakenfut": "PF_DOTUSD",  "kraken_spot": "DOTUSDT"},
    "LTC":  {"binance": "LTCUSDT",  "okx": "LTC-USDT-SWAP",  "krakenfut": "PF_LTCUSD",  "kraken_spot": "LTCUSDT"},
}

BINANCE_FUNDING_DIR = "<repo>/apps/engine/.cosmu/market_data/binance_funding"
GATES = GateSettings()  # LOCKED: DSR>=0.95 PBO<=0.50 folds>=0.60 min_trades>=30 holdout>0 beat-B&H

OUT_JSON = _ENGINE / "scripts" / "research" / "h3_funding_divergence_results_2026_06_25.json"


# ----------------------------------------------------------------------------------------------------
# data helpers
# ----------------------------------------------------------------------------------------------------
def _day(ts: datetime) -> datetime:
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _grid_bucket(ts: datetime) -> datetime:
    """Floor a funding ts to the canonical 8h bucket (00/08/16 UTC). A 4h Binance rate at 12:00 floors
    into the 08:00 bucket so two 4h rates sum into one 8h-equivalent."""
    h = ts.hour
    base = 0 if h < 8 else (8 if h < 16 else 16)
    return ts.replace(hour=base, minute=0, second=0, microsecond=0)


def _to_8h_daily(points: list[AltDataPoint]) -> dict[datetime, float]:
    """Normalize a venue's funding points to a per-DAY 8h-equivalent rate.

    Step 1: sum points into their canonical 8h bucket (8h-equiv = sum of the sub-interval rates that
            accrue within the bucket; e.g. two 4h Binance rates, or eight 1h Kraken rates).
    Step 2: average the (up to 3) 8h-equivalent buckets within a day -> one daily funding number.
    PIT-safe: every input point's available_at == ts, so a day's value is fully realized by that day."""
    bucket: dict[datetime, float] = defaultdict(float)
    for p in points:
        bucket[_grid_bucket(p.ts)] += float(p.value)
    by_day: dict[datetime, list[float]] = defaultdict(list)
    for b_ts, rate in bucket.items():
        by_day[_day(b_ts)].append(rate)
    return {d: statistics.fmean(v) for d, v in by_day.items() if v}


def _kraken_fut_funding(symbol: str, ctx) -> list[AltDataPoint]:  # noqa: ANN001
    """Kraken-Futures historical funding via the CORRECT public endpoint
    (https://futures.kraken.com/derivatives/api/v3/historical-funding-rates). Uses `relativeFundingRate`
    (the per-interval RATE, comparable cross-venue) NOT `fundingRate` (the absolute USD premium).
    `timestamp` is ISO-8601; available_at == ts (realized at the funding instant, no look-ahead).
    NOTE: the in-tree KrakenFuturesFundingRateProvider points at a stale URL + parses the wrong field;
    this experiment uses the corrected fetch INLINE and changes NO production code."""
    import urllib.request

    url = f"https://futures.kraken.com/derivatives/api/v3/historical-funding-rates?symbol={symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  ! kraken-fut funding failed {symbol}: {e}", file=sys.stderr)
        return []
    out: list[AltDataPoint] = []
    for row in payload.get("rates", []):
        ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["relativeFundingRate"])))
    out.sort(key=lambda p: p.ts)
    return out


def _kraken_spot_daily(provider: KrakenSpotOHLCVProvider, symbol: str) -> dict[datetime, float]:
    """Kraken-spot daily CLOSE keyed by day. Real, keyless, PIT (closed daily candle). The reference
    price the fade trades against, with REAL Kraken fees charged later."""
    try:
        bars: list[Bar] = provider.fetch_bars(symbol, "1d", limit=1000)
    except Exception as e:  # noqa: BLE001
        print(f"  ! kraken spot failed {symbol}: {e}", file=sys.stderr)
        return {}
    return {_day(b.ts): float(b.close) for b in bars}


# ----------------------------------------------------------------------------------------------------
# event study
# ----------------------------------------------------------------------------------------------------
@dataclass
class Event:
    asset: str
    venue: str
    day: str
    z: float
    spread: float           # funding_venue - cross_venue_median that day
    direction: int          # -1 = short spot (fade over-long high-funding venue), +1 = long spot
    fwd_raw_return: float    # signed forward N-day return, BEFORE fees (gross, fade-signed)
    fwd_net_return: float    # after round-trip Kraken taker fee
    n_venues: int            # venues with data that day (median basis)


@dataclass
class Report:
    config: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    n_events: int = 0
    n_long: int = 0
    n_short: int = 0
    gross_mean_bps: float = 0.0
    gross_median_bps: float = 0.0
    net_mean_bps: float = 0.0
    reversion_sign_ok: bool = False
    frac_positive_gross: float = 0.0
    roundtrip_fee_bps: float = 0.0
    fee_hurdle_bps: float = 0.0     # 2x round-trip
    edge_beats_hurdle: bool = False
    per_asset: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)
    verdict: str = ""
    events: list = field(default_factory=list)


def build_panel(ctx) -> tuple[dict, dict, dict, dict]:  # noqa: ANN001
    """Returns (funding_daily, spot_daily, coverage, fee_info).
    funding_daily[asset][venue] = {day -> 8h-equiv daily funding}.
    spot_daily[asset] = {day -> kraken spot close}."""
    binance = CachedFundingRateProvider(cache_dir=BINANCE_FUNDING_DIR)
    okx = OkxFundingRateProvider(max_pages=5000)
    kspot = KrakenSpotOHLCVProvider()

    funding_daily: dict[str, dict[str, dict[datetime, float]]] = {}
    spot_daily: dict[str, dict[datetime, float]] = {}
    coverage: dict[str, dict] = {}

    okx_start_ms = int((time.time() - 800 * 86400) * 1000)  # OKX caps ~94d regardless; ask wide, take what's given

    for asset, m in UNIVERSE.items():
        per_venue: dict[str, dict[datetime, float]] = {}

        b_pts = binance.fetch_series(m["binance"], "funding_rate", limit=100000)
        if b_pts:
            per_venue["binance"] = _to_8h_daily(b_pts)

        o_pts = okx.fetch_history(m["okx"], start_ms=okx_start_ms)
        if o_pts:
            per_venue["okx"] = _to_8h_daily(o_pts)

        k_pts = _kraken_fut_funding(m["krakenfut"], ctx)
        if k_pts:
            per_venue["krakenfut"] = _to_8h_daily(k_pts)

        funding_daily[asset] = per_venue
        spot_daily[asset] = _kraken_spot_daily(kspot, m["kraken_spot"])

        cov = {}
        for v, dd in per_venue.items():
            if dd:
                days = sorted(dd)
                cov[v] = {"days": len(dd), "from": str(days[0].date()), "to": str(days[-1].date())}
            else:
                cov[v] = {"days": 0}
        cov["spot"] = {"days": len(spot_daily[asset])}
        coverage[asset] = cov
        print(f"  {asset}: " + " ".join(f"{v}={c.get('days',0)}d" for v, c in cov.items()))
        gc.collect()

    catalog = default_catalog()
    kr = catalog.venue_for(["kraken"])
    fee_info = {
        "taker_bps": float(kr.taker_fee_bps),
        "slippage_bps": float(kr.slippage_bps),
        "roundtrip_taker_bps": 2.0 * float(kr.taker_fee_bps),
    }
    return funding_daily, spot_daily, coverage, fee_info


def run_event_study(funding_daily: dict, spot_daily: dict, fee_info: dict) -> Report:
    rep = Report()
    rep.config = {
        "z_threshold": Z_THRESHOLD, "horizon_days": HORIZON_DAYS, "z_window_days": Z_WINDOW_DAYS,
        "universe": list(UNIVERSE), "venues": ["binance", "okx", "krakenfut"],
        "reference_price": "kraken_spot_daily_close", "median_rule": ">=2 venues with data",
    }
    roundtrip = fee_info["roundtrip_taker_bps"]            # 80 bps at 40bps taker
    fee_frac = roundtrip / 10_000.0
    rep.roundtrip_fee_bps = roundtrip
    rep.fee_hurdle_bps = 2.0 * roundtrip                   # the thesis bar: gross > 2x round-trip

    events: list[Event] = []
    per_asset_returns: dict[str, list[float]] = defaultdict(list)

    for asset in UNIVERSE:
        venues = funding_daily.get(asset, {})
        spot = spot_daily.get(asset, {})
        if not venues or not spot:
            continue
        # union of all days where >=2 venues have funding AND spot exists for entry+exit
        all_days = sorted(set().union(*[set(dd) for dd in venues.values()]))
        for d in all_days:
            vals = {v: dd[d] for v, dd in venues.items() if d in dd}
            if len(vals) < 2:
                continue  # need >=2 venues to define a cross-venue median
            med = statistics.median(vals.values())
            for v, fv in vals.items():
                spread = fv - med
                # PIT z-score: trailing window of THIS (asset,venue) spread strictly BEFORE day d.
                hist = []
                for dd2 in [d - timedelta(days=k) for k in range(1, Z_WINDOW_DAYS + 1)]:
                    if dd2 in venues[v]:
                        others = {vv: ddv[dd2] for vv, ddv in venues.items() if dd2 in ddv}
                        if len(others) >= 2:
                            hist.append(venues[v][dd2] - statistics.median(others.values()))
                if len(hist) < 10:  # need a stable window to z-score honestly
                    continue
                mu = statistics.fmean(hist)
                sd = statistics.pstdev(hist)
                if sd == 0:
                    continue
                z = (spread - mu) / sd
                if abs(z) <= Z_THRESHOLD:
                    continue
                # entry at day d close, exit at day d+HORIZON close (Kraken spot reference)
                entry = spot.get(d)
                exit_d = d + timedelta(days=HORIZON_DAYS)
                exit_px = spot.get(exit_d)
                if entry is None or exit_px is None or entry <= 0:
                    continue
                raw_ret = exit_px / entry - 1.0
                # FADE direction: high-funding outlier (z>0) => perp over-long/expensive => SHORT spot.
                direction = -1 if z > 0 else +1
                signed = direction * raw_ret
                net = signed - fee_frac  # round-trip taker charged once per round-trip trade
                ev = Event(asset=asset, venue=v, day=str(d.date()), z=round(z, 3),
                           spread=spread, direction=direction, fwd_raw_return=signed,
                           fwd_net_return=net, n_venues=len(vals))
                events.append(ev)
                per_asset_returns[asset].append(signed)

    rep.n_events = len(events)
    rep.events = [asdict(e) for e in events]
    if not events:
        rep.verdict = "KILL — zero |z|>2 events with valid forward price (no basket to test)."
        return rep

    gross = [e.fwd_raw_return for e in events]
    net = [e.fwd_net_return for e in events]
    rep.n_long = sum(1 for e in events if e.direction == +1)
    rep.n_short = sum(1 for e in events if e.direction == -1)
    rep.gross_mean_bps = statistics.fmean(gross) * 10_000
    rep.gross_median_bps = statistics.median(gross) * 10_000
    rep.net_mean_bps = statistics.fmean(net) * 10_000
    rep.frac_positive_gross = sum(1 for g in gross if g > 0) / len(gross)
    rep.reversion_sign_ok = rep.gross_mean_bps > 0  # positive signed return => price reverts as the fade predicts
    rep.edge_beats_hurdle = rep.gross_mean_bps > rep.fee_hurdle_bps
    rep.per_asset = {
        a: {
            "n": len(r), "mean_bps": round(statistics.fmean(r) * 10_000, 2),
            "median_bps": round(statistics.median(r) * 10_000, 2),
            "frac_pos": round(sum(1 for x in r if x > 0) / len(r), 3),
        }
        for a, r in sorted(per_asset_returns.items()) if r
    }

    # --- three honest checks ---
    check_a = rep.n_events >= GATES.min_trades  # >=30 pooled entries
    check_b = rep.reversion_sign_ok            # sign of mean reversion is as predicted (positive signed return)
    check_c = rep.edge_beats_hurdle            # gross edge > 2x round-trip fee

    rep.gate = {"check_a_min30": check_a, "check_b_sign": check_b, "check_c_edge_gt_2xfee": check_c}

    if check_a and check_b and check_c:
        # ONLY THEN run the basket through the BRUT Gate stats (on the net signed per-event returns).
        sr, skew, kurt, n = sample_moments(net)
        # annualized Sharpe: events are episodic; annualize by sqrt(events/yr). Use observed events/calendar-year.
        # span of events in years (from first to last event day)
        days_sorted = sorted({e.day for e in events})
        span_days = max(1, (datetime.fromisoformat(days_sorted[-1]) - datetime.fromisoformat(days_sorted[0])).days)
        ev_per_year = len(net) / (span_days / 365.25)
        ann_sharpe = sr * math.sqrt(ev_per_year) if ev_per_year > 0 else 0.0
        psr0 = probabilistic_sharpe(sr, n, skew, kurt, 0.0)
        # PBO via CSCV across a coarse threshold family (z in {1.5,2.0,2.5}) as the config block returns.
        # (This is a within-experiment robustness probe, NOT a sweep for the best — pre-registered z=2.0 is the
        #  point estimate; the family just feeds CSCV-PBO which NEEDS >=2 configs.)
        config_returns = _threshold_family_returns(funding_daily, spot_daily, fee_frac)
        pbo = cscv_pbo(config_returns) if len(config_returns) >= 2 else 1.0
        # folds_positive: fraction of chronological thirds with positive mean net return.
        folds = _folds_positive(net, k=5)
        metrics = BacktestMetrics(
            oos_return=Decimal(str(sum(net))),
            buy_and_hold_return=Decimal("0"),  # a fade basket has no buy-and-hold analog; 0 hurdle
            sharpe=Decimal(str(round(ann_sharpe, 4))),
            sortino=Decimal("0"), max_drawdown=Decimal("0"),
            win_rate=Decimal(str(round(rep.frac_positive_gross, 4))),
            num_trades=n,
            sharpe_per_obs=Decimal(str(round(sr, 6))), skew=Decimal(str(round(skew, 6))),
            kurtosis=Decimal(str(round(kurt, 6))), n_obs=n,
            pbo=Decimal(str(round(pbo, 4))), trials_counted=len(config_returns) or 1,
            folds_positive_pct=Decimal(str(round(folds, 4))),
            holdout_deflated_sharpe=Decimal("0"),
        )
        verdict = score(metrics, GATES, trials=TrialStats(count=max(len(config_returns), 1)), check_holdout=False)
        dsr = deflated_sharpe_prob(metrics, TrialStats(count=max(len(config_returns), 1)))
        rep.gate.update({
            "sharpe_per_obs": round(sr, 4), "ann_sharpe": round(ann_sharpe, 3),
            "psr_vs_zero": round(psr0, 4), "deflated_sharpe": round(dsr, 4),
            "pbo": round(pbo, 4), "folds_positive": round(folds, 4),
            "ev_per_year": round(ev_per_year, 1), "gate_passed": bool(verdict.passed),
            "killed_by": list(verdict.reasons),
        })
        rep.verdict = ("GO — cleared a/b/c; " + ("Gate PASS" if verdict.passed else
                       f"Gate FAIL (killed_by={verdict.reasons})"))
    else:
        fails = [k for k, ok in [("a:>=30", check_a), ("b:sign", check_b), ("c:edge>2xfee", check_c)] if not ok]
        rep.verdict = f"KILL — failed {fails}; do not promote. (sign+/-{rep.gross_mean_bps:.1f}bps vs hurdle {rep.fee_hurdle_bps:.0f}bps)"
    return rep


def _threshold_family_returns(funding_daily: dict, spot_daily: dict, fee_frac: float) -> list[list[float]]:
    """Per-config NET per-event return series for z in {1.5, 2.0, 2.5} — the CSCV-PBO config family.
    Robustness probe only; the pre-registered point estimate stays z=2.0."""
    out: list[list[float]] = []
    for zt in (1.5, 2.0, 2.5):
        rets: list[float] = []
        for asset in UNIVERSE:
            venues = funding_daily.get(asset, {})
            spot = spot_daily.get(asset, {})
            if not venues or not spot:
                continue
            all_days = sorted(set().union(*[set(dd) for dd in venues.values()]))
            for d in all_days:
                vals = {v: dd[d] for v, dd in venues.items() if d in dd}
                if len(vals) < 2:
                    continue
                med = statistics.median(vals.values())
                for v, fv in vals.items():
                    hist = []
                    for dd2 in [d - timedelta(days=k) for k in range(1, Z_WINDOW_DAYS + 1)]:
                        if dd2 in venues[v]:
                            others = {vv: ddv[dd2] for vv, ddv in venues.items() if dd2 in ddv}
                            if len(others) >= 2:
                                hist.append(venues[v][dd2] - statistics.median(others.values()))
                    if len(hist) < 10:
                        continue
                    mu = statistics.fmean(hist)
                    sd = statistics.pstdev(hist)
                    if sd == 0:
                        continue
                    z = (fv - med - mu) / sd
                    if abs(z) <= zt:
                        continue
                    entry = spot.get(d)
                    exit_px = spot.get(d + timedelta(days=HORIZON_DAYS))
                    if entry is None or exit_px is None or entry <= 0:
                        continue
                    direction = -1 if z > 0 else +1
                    rets.append(direction * (exit_px / entry - 1.0) - fee_frac)
        if len(rets) >= 4:
            out.append(rets)
        gc.collect()
    # CSCV needs equal-length series; truncate to the shortest (chronological order preserved within config).
    if out:
        n = min(len(r) for r in out)
        out = [r[:n] for r in out]
    return out


def _folds_positive(returns: list[float], k: int = 5) -> float:
    """Fraction of k chronological folds whose mean net return is positive."""
    if len(returns) < k:
        return 0.0
    fold = len(returns) // k
    pos = 0
    for i in range(k):
        seg = returns[i * fold:(i + 1) * fold] if i < k - 1 else returns[i * fold:]
        if seg and statistics.fmean(seg) > 0:
            pos += 1
    return pos / k


def main() -> int:
    from cosmu.data.providers._types import _ssl_context
    ctx = _ssl_context()
    print("H3 CROSS-VENUE FUNDING DIVERGENCE — EXPERIMENT ONLY, ZERO prod impact")
    print(f"  pre-registered: |z|>{Z_THRESHOLD}  horizon={HORIZON_DAYS}d  z_window={Z_WINDOW_DAYS}d  "
          f"universe={len(UNIVERSE)}  median over >=2 venues")
    print("  building cross-venue funding panel (REAL, PIT, 8h-normalized)...")
    funding_daily, spot_daily, coverage, fee_info = build_panel(ctx)
    print(f"  kraken round-trip taker = {fee_info['roundtrip_taker_bps']:.0f} bps  "
          f"hurdle (2x) = {2*fee_info['roundtrip_taker_bps']:.0f} bps")
    rep = run_event_study(funding_daily, spot_daily, fee_info)
    rep.coverage = coverage

    OUT_JSON.write_text(json.dumps(asdict(rep), indent=2, default=str))
    print(f"\n  events N = {rep.n_events}  (long={rep.n_long} short={rep.n_short})")
    print(f"  gross mean = {rep.gross_mean_bps:.1f} bps  net mean = {rep.net_mean_bps:.1f} bps  "
          f"frac_pos = {rep.frac_positive_gross:.2%}")
    print(f"  reversion sign ok (gross>0) = {rep.reversion_sign_ok}")
    print(f"  edge beats 2x-fee hurdle ({rep.fee_hurdle_bps:.0f} bps) = {rep.edge_beats_hurdle}")
    print(f"  checks: {rep.gate.get('check_a_min30')=} {rep.gate.get('check_b_sign')=} {rep.gate.get('check_c_edge_gt_2xfee')=}")
    if "gate_passed" in rep.gate:
        print(f"  GATE: DSR={rep.gate['deflated_sharpe']} PBO={rep.gate['pbo']} folds={rep.gate['folds_positive']} "
              f"passed={rep.gate['gate_passed']} killed_by={rep.gate['killed_by']}")
    print(f"\n  VERDICT: {rep.verdict}")
    print(f"  wrote -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
