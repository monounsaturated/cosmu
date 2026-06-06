# intent: an UNBIASED lead-lag PROBE (scan-signals) over the DEEP, scale-stable LunarCrush cross-sectional
# attention shares — social_dominance (a coin's % share of ALL crypto social volume) and market_dominance
# (its % share of total market cap) — plus alt_rank, vs an absolute-level control (social_volume_accel). For
# each candidate signal we compute the CROSS-SECTIONAL decile spread of FUTURE k-day return (top-decile minus
# bottom-decile, equal-weight) at k in {1,2,3,5,7}, with a paired t-stat across days. PIT throughout: the signal
# at bar t is joined via available_at (next-day social bucket) and the forward return is r_{t→t+k} (strictly
# future). NO look-ahead, NO synthetic/zero-fill (a coin with no social/return at t is dropped from that day's
# cross-section). PROPOSE-ONLY: this surfaces ONE hypothesis with a sign; the deterministic Gate disposes.
#
# Why these signals: raw social_volume LEVEL drifts ~160x over 2020-26 so a fitted level threshold is always-
# true (the phase0 §4 trap), and social_volume_accel / excess_attention were already probed. social_dominance
# is a BOUNDED SHARE (∈[0,1]-ish), so its trailing-z and its day-over-day CHANGE are genuinely scale-stable and
# binding across the whole sample — and NO spec rests on it yet. The probe asks: does a coin GAINING relative
# attention share (Δ dominance, or rising trailing-z of dominance) lead its OWN future cross-sectional return?

from __future__ import annotations

import glob
import math
import os
import os.path as _p
import statistics
from dataclasses import dataclass

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint
from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
from cosmu.knowledge.store import Store

_KS = (1, 2, 3, 5, 7)
_Z_WIN = 30  # trailing within-asset z window (days); same as social_norm._Z_WINDOW
_Z_MIN = 10


def _coin(symbol: str) -> str:
    return symbol[:-4] if symbol.upper().endswith("USDT") else symbol.upper()


def _universe() -> list[str]:
    return sorted({_p.basename(f).replace("_1d.json", "") for f in glob.glob(".cosmu/market_data/binance/*_1d.json")})


def _trailing_z(points: list[AltDataPoint]) -> list[AltDataPoint]:
    """Within-asset TRAILING z of a level series — uses only points up to and including each point (no look-ahead).
    available_at is preserved so the PIT join is honest."""
    out: list[AltDataPoint] = []
    vals: list[float] = []
    for p in points:
        vals.append(p.value)
        if len(vals) >= _Z_MIN:
            window = vals[-_Z_WIN:]
            mu = statistics.fmean(window)
            sd = statistics.pstdev(window)
            if sd > 0:
                out.append(AltDataPoint(ts=p.ts, available_at=p.available_at, value=(p.value - mu) / sd))
    return out


def _delta(points: list[AltDataPoint]) -> list[AltDataPoint]:
    """Day-over-day CHANGE (level difference) of a bounded share series. available_at of the later point (the
    change is only knowable once the later point is available — no look-ahead)."""
    out: list[AltDataPoint] = []
    for i in range(1, len(points)):
        out.append(AltDataPoint(ts=points[i].ts, available_at=points[i].available_at, value=points[i].value - points[i - 1].value))
    return out


def _accel(points: list[AltDataPoint]) -> list[AltDataPoint]:
    """ln(v_t / v_{t-1}) — the absolute-level CONTROL (social_volume_accel), already probed elsewhere."""
    out: list[AltDataPoint] = []
    for i in range(1, len(points)):
        a, b = points[i - 1].value, points[i].value
        if a > 0 and b > 0:
            out.append(AltDataPoint(ts=points[i].ts, available_at=points[i].available_at, value=math.log(b / a)))
    return out


@dataclass
class ProbeRow:
    signal: str
    k: int
    spread: float  # mean(top-decile fwd ret) - mean(bottom-decile fwd ret), per-day averaged
    t_stat: float  # paired across days
    n_days: int


def _fwd_returns(bars: list[Bar], k: int) -> dict[str, float]:
    """r_{t→t+k} keyed by bar[t].ts.isoformat() — STRICTLY future (uses close at t and t+k only)."""
    out: dict[str, float] = {}
    for i in range(len(bars) - k):
        c0 = float(bars[i].close)
        ck = float(bars[i + k].close)
        if c0 > 0 and ck > 0:
            out[bars[i].ts.isoformat()] = ck / c0 - 1.0
    return out


def _decile_spread_series(
    sig_by_sym: dict[str, dict[str, float]],  # signal value keyed by bar.ts.isoformat()
    fwd_by_sym: dict[str, dict[str, float]],  # forward k-ret keyed by bar.ts.isoformat()
    dates: list[str],
) -> list[float]:
    """For each date, rank the cross-section of symbols by the signal, take the top vs bottom TERCILE (robust on a
    ~30-name universe), and record (mean top fwd ret) - (mean bottom fwd ret). NO synthetic fill — a date needs
    >=6 symbols with BOTH a signal and a forward return, else it is skipped."""
    spreads: list[float] = []
    for d in dates:
        pairs = [
            (sig_by_sym[s][d], fwd_by_sym[s][d])
            for s in sig_by_sym
            if d in sig_by_sym[s] and s in fwd_by_sym and d in fwd_by_sym[s]
        ]
        if len(pairs) < 6:
            continue
        pairs.sort(key=lambda x: x[0])
        n = len(pairs)
        cut = max(1, n // 3)
        bottom = [r for _, r in pairs[:cut]]
        top = [r for _, r in pairs[-cut:]]
        spreads.append(statistics.fmean(top) - statistics.fmean(bottom))
    return spreads


def _probe_signal(name: str, sig_by_sym: dict[str, dict[str, float]], market: dict[str, list[Bar]]) -> list[ProbeRow]:
    rows: list[ProbeRow] = []
    for k in _KS:
        fwd_by_sym = {s: _fwd_returns(b, k) for s, b in market.items()}
        all_dates = sorted({d for s in sig_by_sym for d in sig_by_sym[s]})
        spreads = _decile_spread_series(sig_by_sym, fwd_by_sym, all_dates)
        if len(spreads) < 20:
            rows.append(ProbeRow(name, k, float("nan"), float("nan"), len(spreads)))
            continue
        mu = statistics.fmean(spreads)
        sd = statistics.pstdev(spreads) or 1e-12
        t = mu / (sd / math.sqrt(len(spreads)))
        rows.append(ProbeRow(name, k, mu, t, len(spreads)))
    return rows


def main() -> int:
    db = os.environ.get("DATABASE_URL")
    store = Store(Settings(database_url=db, openrouter_api_key=None))
    provider = StoreBackedAltProvider(PgAltDataStore(store))
    prov = BinanceSpotOHLCVProvider()

    syms = _universe()
    market: dict[str, list[Bar]] = {}
    for s in syms:
        try:
            bars = prov.fetch_bars(s, "1d", limit=1000)
            if bars:
                market[s] = bars
        except Exception:  # noqa: BLE001
            continue
    print(f"universe: {len(market)} symbols with 1d bars")

    # Build each candidate signal, joined point-in-time onto each symbol's bars.
    # social_dominance / market_dominance / alt_rank are stored under the bare COIN symbol (e.g. BTC, not BTCUSDT).
    raw_metrics = {
        "social_dominance": "social_dominance",
        "market_dominance": "market_dominance",
        "alt_rank": "alt_rank",
        "social_volume": "social_volume",
    }
    raw_series: dict[str, dict[str, list[AltDataPoint]]] = {m: {} for m in raw_metrics}
    for s, bars in market.items():
        coin = _coin(s)
        for m in raw_metrics:
            pts = provider.fetch_series(coin, m, limit=len(bars) + 2400)
            if pts:
                raw_series[m][s] = pts

    # Candidate transforms (each → per-symbol PIT-joined dict keyed by bar.ts.isoformat()):
    candidates: dict[str, dict[str, dict[str, float]]] = {}

    def _join(transformed: dict[str, list[AltDataPoint]]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for s, pts in transformed.items():
            j = align_asof(pts, market[s])
            if j:
                out[s] = j
        return out

    # 1) social_dominance trailing-z LEVEL  (high share, scale-stable)
    candidates["social_dom_z"] = _join({s: _trailing_z(p) for s, p in raw_series["social_dominance"].items()})
    # 2) social_dominance day-over-day CHANGE (gaining share)
    candidates["social_dom_delta"] = _join({s: _delta(p) for s, p in raw_series["social_dominance"].items()})
    # 3) market_dominance trailing-z LEVEL (contains price mechanically — a disconfirmer control)
    candidates["market_dom_z"] = _join({s: _trailing_z(p) for s, p in raw_series["market_dominance"].items()})
    # 4) market_dominance CHANGE
    candidates["market_dom_delta"] = _join({s: _delta(p) for s, p in raw_series["market_dominance"].items()})
    # 5) alt_rank LEVEL (lower = better; negate so "higher signal = better rank" for a consistent decile read)
    candidates["alt_rank_neg"] = _join({s: [AltDataPoint(ts=q.ts, available_at=q.available_at, value=-q.value) for q in p] for s, p in raw_series["alt_rank"].items()})
    # 6) social_volume_accel — the already-probed absolute-level CONTROL
    candidates["social_volume_accel(control)"] = _join({s: _accel(p) for s, p in raw_series["social_volume"].items()})

    print(f"\n{'signal':<30} {'k':>3} {'spread%':>9} {'t':>7} {'days':>6}")
    print("-" * 60)
    results: dict[str, list[ProbeRow]] = {}
    for name, sig in candidates.items():
        rows = _probe_signal(name, sig, market)
        results[name] = rows
        for r in rows:
            sp = "nan" if math.isnan(r.spread) else f"{r.spread * 100:+.3f}"
            tt = "nan" if math.isnan(r.t_stat) else f"{r.t_stat:+.2f}"
            print(f"{r.signal:<30} {r.k:>3} {sp:>9} {tt:>7} {r.n_days:>6}")

    # Highlight the strongest |t| at any k for each signal.
    print("\nSTRONGEST |t| PER SIGNAL:")
    for name, rows in results.items():
        valid = [r for r in rows if not math.isnan(r.t_stat)]
        if valid:
            best = max(valid, key=lambda r: abs(r.t_stat))
            print(f"  {name:<30} k={best.k} spread={best.spread*100:+.3f}% t={best.t_stat:+.2f} days={best.n_days}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
