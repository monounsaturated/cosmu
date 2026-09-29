# intent: ONE pre-registered hypothesis — does an Aave (v3) on-chain money-market STRESS spike LEAD a 24-72h
# realized-vol cascade on crypto majors, enough to make a maker-feasible spot DE-RISK overlay survive the BRUT
# Gate net of fees? Inputs: an Aave stress proxy series (supply-APY spike, keyless DefiLlama — see the LOUD PIT
# CAVEAT below) joined POINT-IN-TIME to BTC/ETH daily bars + their funding. Outputs: per (symbol x venue) BRUT
# verdicts + REQUIRED disconfirmers (IC-over-vol/funding · shuffle/lag placebos · PIT honesty). Invariants:
# Gate LOCKED (metrics_for_run -> promote_brut, GateSettings defaults, judged BRUT per cell on its OWN data); no
# constant changed; PIT join only (stress[t] known by bar[t]); real venue maker fee; NEVER synthetic-fill real data.
#
# ============================== LOUD PIT CAVEAT (read before trusting any number) ==============================
# The PIT-honest stress source is the Aave SUBGRAPH (block-timestamped, immutable). At experiment time it is
# UNREACHABLE keyless: the legacy hosted subgraph is dead (301), and the decentralized Graph gateway returns
# `auth error: missing authorization header` with no Graph API key in .env.local. The only reachable keyless
# on-chain stress series is DefiLlama's yield chart (supply APY + TVL). DefiLlama is EXPLICITLY PIT-COMPROMISED
# (it BACKFILLS / RECOMPUTES history; its yield-chart timestamps are SCRAPE times, not block times) AND its
# borrow-side / utilization HISTORY (chartLendBorrow) is PAYWALLED. So the stress proxy used here is the daily
# SUPPLY-APY SPIKE (a supply-APY jump is a faithful proxy for a utilization/borrow-rate jump, since supply APY ~=
# borrow APY x utilization x (1 - reserve factor)). Any SURVIVOR from this module is PROVISIONAL and MUST be
# re-run on the block-timestamped Aave subgraph (paid Graph key) before it can be believed. A KILL here is robust
# regardless of PIT (a signal that can't clear the Gate even on the recompute-friendly series won't clear on a
# stricter one).
# ==============================================================================================================

from __future__ import annotations

import json
import math
import ssl
import statistics
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cosmu.data.backtest import (
    SymbolRun,
    Trade,
    _fold_returns,
    _regime_labels,
    _sharpe,
    _sortino,
    metrics_for_run,
)
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider, default_crypto_reference
from cosmu.master.cohort import Candidate, promote_brut
from cosmu.spine.venue import default_catalog

# ---------------------------------------------------------------------------------------------------------------
# PRE-REGISTERED HYPOTHESIS (fixed BEFORE looking — changing it after a run is itself a new trial)
# ---------------------------------------------------------------------------------------------------------------
# H1: An Aave money-market STRESS spike (stress z-score > K on day t) LEADS an elevated-realized-vol / drawdown
#     CASCADE on crypto majors over the next HORIZON_DAYS (24-72h). DIRECTION: stress -> risk-OFF.
# THE TRADE (maker-feasible, spot, long-only de-risk overlay): hold the major (long) by DEFAULT; when stress
#     z > K on day t, STEP OUT (go flat) for the next HORIZON_DAYS, then re-enter. Exits/entries are LIMIT
#     (maker) fills modelled at the venue MAKER fee. This is directional (it avoids the cascade drawdown) and
#     spot-tradeable (no vol instrument needed).
# PASS BAR: each (symbol x venue) cell must clear the LOCKED BRUT Gate (metrics_for_run -> promote_brut,
#     GateSettings defaults) net of the real maker fee, AND beat all three REQUIRED disconfirmers:
#       (a) ADD IC over plain trailing-realized-vol + funding controls (else it's a repackaged vol proxy -> KILL);
#       (b) a SHUFFLED and a LAGGED placebo of the stress series must NOT survive the Gate;
#       (c) PIT honesty (documented above — provisional on the subgraph re-run).
STRESS_Z_K: float = 1.5          # pre-registered stress-spike threshold (z-score)
HORIZON_DAYS: int = 3            # 24-72h de-risk window (3 daily bars)
STRESS_LOOKBACK: int = 30        # rolling window for the stress z-score
VENUE_ID: str = "binance"        # spot, FR-legal, real maker fee from the catalog
SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
BARS_TIMEFRAME: str = "1d"
BARS_LIMIT: int = 2000
# Absolute local Binance spot bar cache (the M2 store) — read through the BinanceSpotOHLCVProvider seam, exactly
# like the perp harness reads its cache. Absolute so a run from any cwd resolves the real cache (a relative
# default would miss it and trigger a geo-blocked live fetch).
BARS_CACHE = "<repo>/.cosmu/market_data/binance"

# REAL maker fee (fraction) from the venue catalog — NOT a magic number. The de-risk overlay trades with LIMIT
# orders (step out / step back in), so it is charged the MAKER rate.
MAKER_FEE: float = float(default_catalog().venue(VENUE_ID).maker_fee_bps) / 10000.0

# Keyless DefiLlama yield-chart pool ids for the four MAJOR Aave-v3 (Ethereum) markets (USDC/USDT/WETH/WBTC).
# These are the deepest pools; their supply-APY spikes are the aggregate money-market stress proxy.
_AAVE_POOLS: dict[str, str] = {
    "USDC": "aa70268e-4b52-42bf-a116-608b370f9501",
    "USDT": "f981a304-bb6c-45b8-b0c5-fd2f515ad23a",
    "WETH": "e880e828-ca59-4ec6-8d4f-27182a4dc23d",
    "WBTC": "7e382157-b1bc-406d-b17b-facba43b716e",
}
_DEFILLAMA_CHART = "https://yields.llama.fi/chart/{pool}"

PERIODS_PER_YEAR: float = 365.0  # daily crypto bars


# ---------------------------------------------------------------------------------------------------------------
# data: the Aave stress proxy (keyless DefiLlama supply-APY) + crypto bars
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class StressSeries:
    """A daily aggregate Aave stress proxy: date (UTC) -> z-scoreable stress LEVEL (mean supply APY across the
    major markets). `available_at` is the SCRAPE time we treat the value as known by (PIT join floor = end of the
    UTC day, conservative). NEVER block time — see the module PIT caveat."""

    dates: list[datetime]
    level: list[float]
    source: str  # "defillama_supply_apy" (PIT-compromised) | "synthetic" (test)


def _ssl_context() -> ssl.SSLContext:
    """A verifying SSL context backed by certifi (the engine's pinned CA bundle) — robust to a Python install whose
    default trust store can't find the system root certs. Never disables verification."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — certifi missing: fall back to the system default context (still verifies)
        return ssl.create_default_context()


def _http_json(url: str, *, timeout: int = 45) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310 — fixed https hosts
        return json.loads(resp.read().decode("utf-8"))


def fetch_aave_stress(*, pools: dict[str, str] | None = None) -> StressSeries | None:
    """Fetch the aggregate Aave money-market stress proxy from the keyless DefiLlama yield chart: for each major
    pool, the daily supply APY; the cross-pool MEAN per UTC day is the aggregate stress LEVEL (a spike = a
    utilization/borrow-rate spike). Returns None on any network/parse failure (honest skip, NEVER synthetic-fill
    a real run). PIT-COMPROMISED source — see the module caveat; provisional until re-run on the subgraph."""
    pools = pools or _AAVE_POOLS
    by_day: dict[str, list[float]] = {}
    got = 0
    for _sym, pid in pools.items():
        try:
            payload = _http_json(_DEFILLAMA_CHART.format(pool=pid))
        except Exception:  # noqa: BLE001 — offline / rate-limited: honest skip
            continue
        rows = payload.get("data") or []
        if not rows:
            continue
        got += 1
        for r in rows:
            apy = r.get("apyBase")
            ts = r.get("timestamp")
            if apy is None or ts is None:
                continue
            day = str(ts)[:10]  # UTC date bucket; the value is known only by END of that day (PIT floor)
            by_day.setdefault(day, []).append(float(apy))
    if got == 0 or not by_day:
        return None
    dates = sorted(by_day)
    out_dates = [datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC) for d in dates]
    level = [statistics.fmean(by_day[d]) for d in dates]
    return StressSeries(dates=out_dates, level=level, source="defillama_supply_apy")


def load_majors(symbols: tuple[str, ...] = SYMBOLS) -> dict[str, list[Bar]]:
    """Cached REAL daily bars for the crypto majors. A symbol with no cache is simply absent — never synthetic."""
    ref = default_crypto_reference()
    provider = ref if not isinstance(ref, BinanceSpotOHLCVProvider) else BinanceSpotOHLCVProvider(cache_dir=BARS_CACHE)
    out: dict[str, list[Bar]] = {}
    for sym in symbols:
        try:
            bars = provider.fetch_bars(sym, BARS_TIMEFRAME, limit=BARS_LIMIT)
        except Exception:  # noqa: BLE001
            continue
        if bars:
            out[sym] = bars
    return out


# ---------------------------------------------------------------------------------------------------------------
# signal engineering (PIT throughout)
# ---------------------------------------------------------------------------------------------------------------
def _rolling_z(level: list[float], lookback: int) -> list[float | None]:
    """Causal rolling z-score: z[i] uses level[i-lookback:i] (STRICTLY past) so the spike flag at day i is known
    by the close of day i — no look-ahead. None until the window fills."""
    out: list[float | None] = []
    for i in range(len(level)):
        window = level[max(0, i - lookback):i]
        if len(window) < lookback:
            out.append(None)
            continue
        mu = statistics.fmean(window)
        sd = statistics.pstdev(window)
        out.append((level[i] - mu) / sd if sd > 0 else 0.0)
    return out


def _align_stress_to_bars(bars: list[Bar], stress: StressSeries, z: list[float | None]) -> list[float | None]:
    """PIT join: for each bar, the LATEST stress z whose UTC day is <= the bar's UTC day. The stress z for day D
    is known by the END of day D, and a daily bar closes at the end of its day, so using day D's z on bar D is
    causal (the bar's own forward return is days D+1..). Missing -> None (pass-through, no synthetic-fill)."""
    pairs = sorted(zip([d.date() for d in stress.dates], z, strict=True), key=lambda p: p[0])
    out: list[float | None] = []
    j = 0
    last: float | None = None
    for b in bars:
        bd = b.ts.astimezone(UTC).date() if b.ts.tzinfo else b.ts.date()
        while j < len(pairs) and pairs[j][0] <= bd:
            last = pairs[j][1]
            j += 1
        out.append(last)
    return out


def _realized_vol(closes: list[float], lookback: int = 14) -> list[float | None]:
    """Trailing realized vol (stdev of past `lookback` daily log-returns) — the control the stress signal must
    BEAT. v[i] uses returns ending at i-1 (strictly past), so it is PIT for a decision made at bar i."""
    rets = [math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0 for i in range(1, len(closes))]
    out: list[float | None] = [None]  # no vol defined at bar 0
    for i in range(1, len(closes)):
        window = rets[max(0, i - lookback):i]
        out.append(statistics.pstdev(window) if len(window) >= 2 else None)
    return out


# ---------------------------------------------------------------------------------------------------------------
# the de-risk-overlay simulation (net of the real MAKER fee)
# ---------------------------------------------------------------------------------------------------------------
def _simulate_overlay(
    bars: list[Bar],
    spike: list[bool],
    *,
    horizon: int = HORIZON_DAYS,
    maker_fee: float = MAKER_FEE,
) -> tuple[list[float], list[str], list[Trade]]:
    """Default-long the major; on a stress spike at day t, STEP OUT (flat) for `horizon` days, then re-enter.
    Each step-out and each step-back-in is one LIMIT (maker) fill, charged `maker_fee`. Returns (equity, bar_ts,
    trades). The equity stream is NET-of-fee; its bar returns are the streams the BRUT gate scores on.

    Bar return convention: position held over (t, t+1] earns close[t+1]/close[t]-1; a fee is debited on the bar
    where position changes. This mirrors the crypto backtest's mark-to-market-then-charge-on-turn discipline."""
    closes = [float(b.close) for b in bars]
    regimes = _regime_labels(closes)
    equity = [100000.0]
    bar_ts: list[str] = []
    trades: list[Trade] = []
    pos = 1.0  # start long (default exposure)
    flat_until = -1
    entry_px = closes[0]
    entry_idx = 0
    for i in range(1, len(bars)):
        # decide today's position from YESTERDAY's known spike flag (PIT — spike[i-1] known by close i-1)
        if i - 1 < len(spike) and spike[i - 1] and pos > 0:
            flat_until = (i - 1) + horizon
        want = 0.0 if i <= flat_until else 1.0
        prev_eq = equity[-1]
        # mark the period (t-1, t] at the position held INTO it
        gross = (closes[i] / closes[i - 1] - 1.0) if closes[i - 1] else 0.0
        new_eq = prev_eq * (1.0 + pos * gross)
        # turn: charge maker fee on the notional that changes hands when pos flips
        if want != pos:
            turn = abs(want - pos)  # 1.0 for a full flip
            new_eq *= (1.0 - maker_fee * turn)
            if want == 0.0 and pos > 0.0:  # closing the long -> record a trade
                trades.append(Trade(entry=entry_px, exit=closes[i], pnl_pct=closes[i] / entry_px - 1.0, regime=regimes[entry_idx]))
            if want > 0.0 and pos == 0.0:  # re-opening the long
                entry_px = closes[i]
                entry_idx = i
            pos = want
        equity.append(new_eq)
        bar_ts.append(_iso(bars[i].ts))
    if pos > 0.0:  # close any open long at the end so the trade ledger is complete
        trades.append(Trade(entry=entry_px, exit=closes[-1], pnl_pct=closes[-1] / entry_px - 1.0, regime=regimes[entry_idx]))
    return equity, bar_ts, trades


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat() if ts.tzinfo else ts.replace(tzinfo=UTC).isoformat()


def _build_symbol_run(equity: list[float], bar_ts: list[str], trades: list[Trade]) -> SymbolRun:
    """Assemble a faithful SymbolRun from a NET-of-fee equity stream — the EXACT shape metrics_for_run consumes,
    using the SAME helpers (_sharpe/_sortino/_fold_returns/_regime accounting) the crypto backtest uses."""
    returns = [(equity[i] / equity[i - 1] - 1.0) if equity[i - 1] else 0.0 for i in range(1, len(equity))]
    total_return = equity[-1] / 100000.0 - 1.0
    high = equity[0]
    max_dd = 0.0
    for v in equity:
        high = max(high, v)
        if high:
            max_dd = max(max_dd, (high - v) / high)
    regime_pnl: dict[str, float] = {}
    for t in trades:
        regime_pnl[t.regime] = regime_pnl.get(t.regime, 0.0) + t.pnl_pct
    return SymbolRun(
        total_return=total_return,
        sharpe=_sharpe(returns, PERIODS_PER_YEAR),
        sortino=_sortino(returns, PERIODS_PER_YEAR),
        max_drawdown=max_dd,
        trades=trades,
        bar_returns=returns,
        bar_ts=bar_ts[:len(returns)],
        fold_returns=_fold_returns(equity),
        regime_pnl=regime_pnl,
        periods_per_year=PERIODS_PER_YEAR,
    )


# ---------------------------------------------------------------------------------------------------------------
# disconfirmers (pass ALL or KILL)
# ---------------------------------------------------------------------------------------------------------------
def _forward_vol(closes: list[float], horizon: int) -> list[float | None]:
    """Realized vol REALIZED over the next `horizon` bars (the cascade target). v[i] = stdev of log-returns over
    (i, i+horizon]. The LAST `horizon` entries are None (no future). Used ONLY for the IC test, never traded."""
    logret = [math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0 for i in range(1, len(closes))]
    out: list[float | None] = []
    for i in range(len(closes)):
        seg = logret[i:i + horizon]  # returns realized AFTER bar i
        out.append(statistics.pstdev(seg) if len(seg) >= 2 else None)
    return out


def _partial_ic(
    x: list[float], y: list[float], controls: list[list[float]]
) -> tuple[float, float, int]:
    """Partial Spearman-style IC of x vs y after linearly removing `controls` from BOTH (rank-transform first for
    robustness). Returns (raw_ic, partial_ic, n). partial_ic ~ 0 means the stress signal carries NO information
    about forward vol beyond the controls (trailing vol + funding) -> 'repackaged vol proxy' -> KILL."""
    n = len(x)
    if n < 20:
        return 0.0, 0.0, n
    rx, ry = _rankz(x), _rankz(y)
    rc = [_rankz(c) for c in controls]
    raw = _pearson(rx, ry)
    # residualize rx and ry against the (rank) controls via least squares, then correlate residuals
    res_x = _residual(rx, rc)
    res_y = _residual(ry, rc)
    partial = _pearson(res_x, res_y)
    return raw, partial, n


def _rankz(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    for r, i in enumerate(order):
        ranks[i] = float(r)
    mu = statistics.fmean(ranks)
    sd = statistics.pstdev(ranks) or 1.0
    return [(r - mu) / sd for r in ranks]


def _pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 2:
        return 0.0
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da > 0 and db > 0 else 0.0


def _residual(y: list[float], xs: list[list[float]]) -> list[float]:
    """OLS residual of y on [1, *xs] via normal equations (small, well-conditioned: <=2 controls). Falls back to
    y demeaned if the system is singular."""
    if not xs:
        return [v - statistics.fmean(y) for v in y]
    n = len(y)
    design = [[1.0] + [xs[k][i] for k in range(len(xs))] for i in range(n)]
    p = len(design[0])
    xtx = [[sum(design[i][a] * design[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    xty = [sum(design[i][a] * y[i] for i in range(n)) for a in range(p)]
    beta = _solve(xtx, xty)
    if beta is None:
        return [v - statistics.fmean(y) for v in y]
    return [y[i] - sum(beta[a] * design[i][a] for a in range(p)) for i in range(n)]


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Tiny Gaussian elimination for the OLS normal equations. None if singular."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        pivot = m[col][col]
        m[col] = [v / pivot for v in m[col]]
        for r in range(n):
            if r != col and abs(m[r][col]) > 0:
                factor = m[r][col]
                m[r] = [m[r][k] - factor * m[col][k] for k in range(n + 1)]
    return [m[i][n] for i in range(n)]


def _shuffle(values: list[float], seed: int) -> list[float]:
    """Deterministic Fisher-Yates shuffle (no global RNG) — the stress-series shuffle placebo."""
    out = values[:]
    state = seed & 0xFFFFFFFF
    for i in range(len(out) - 1, 0, -1):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        j = state % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


# ---------------------------------------------------------------------------------------------------------------
# the experiment: per (symbol x venue) BRUT gate + disconfirmers
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class CellResult:
    symbol: str
    venue: str
    promoted: bool
    deflated_sharpe_prob: float
    num_trades: int
    net_return: float
    sharpe: float
    max_drawdown: float
    reasons: list[str]
    raw_ic: float          # stress-z (at spike days) vs forward realized vol
    partial_ic_over_vol_funding: float  # IC after removing trailing vol + funding controls
    shuffle_promoted: bool
    lag_promoted: bool


@dataclass
class Verdict:
    decision: str          # "SURVIVOR" | "KILL"
    wall: str              # the specific reason a KILL hit (empty for SURVIVOR)
    adds_ic_over_controls: bool
    pit_honest: bool       # the subgraph (block-time) source was used (else PROVISIONAL on a PIT-compromised proxy)
    source: str
    cells: list[CellResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _gate_settings():  # noqa: ANN202
    from cosmu.config.settings import get_settings

    return get_settings().gates


FUNDING_CACHE = "<repo>/.cosmu/market_data/binance_funding"


def _funding_control(symbol: str, bars: list[Bar]) -> list[float | None]:
    """Trailing perp funding rate aligned PIT to bars (a control the stress signal must beat). Read straight from
    the local funding cache ([{fundingTime, fundingRate}]); a bar gets the LATEST settlement <= its timestamp.
    Absent / pre-funding window -> None (the control degrades to vol-only on that span, honest — never fabricated)."""
    import os

    path = os.path.join(FUNDING_CACHE, f"{symbol}.json")
    if not os.path.exists(path):
        return [None] * len(bars)
    try:
        with open(path) as fh:
            rows = json.load(fh)
    except Exception:  # noqa: BLE001
        return [None] * len(bars)
    pairs = sorted(
        (
            (datetime.fromtimestamp(int(r["fundingTime"]) / 1000.0, tz=UTC), float(r["fundingRate"]))
            for r in rows
            if r.get("fundingTime") is not None and r.get("fundingRate") is not None
        ),
        key=lambda x: x[0],
    )
    out: list[float | None] = []
    j = 0
    last: float | None = None
    for b in bars:
        bt = b.ts if b.ts.tzinfo else b.ts.replace(tzinfo=UTC)
        while j < len(pairs) and pairs[j][0] <= bt:
            last = pairs[j][1]
            j += 1
        out.append(last)
    return out


def run_experiment(
    *,
    stress: StressSeries | None = None,
    market: dict[str, list[Bar]] | None = None,
) -> Verdict:
    """Run the pre-registered H1 per (symbol x venue) through the LOCKED BRUT Gate net of the maker fee, plus all
    three disconfirmers. Returns a SURVIVOR/KILL verdict. `stress`/`market` injectable for offline tests; a real
    run fetches the keyless DefiLlama proxy + the cached majors."""
    stress = stress if stress is not None else fetch_aave_stress()
    market = market if market is not None else load_majors()
    notes: list[str] = []
    if stress is None:
        return Verdict("KILL", "no_stress_data", False, False, "none",
                       notes=["Aave stress series unreachable (subgraph needs a Graph key; DefiLlama fetch failed)."])
    if not market:
        return Verdict("KILL", "no_market_data", False, False, stress.source,
                       notes=["no cached majors bars to join the stress series to"])

    pit_honest = stress.source.startswith("aave_subgraph")
    if not pit_honest:
        notes.append(
            "PIT-PROVISIONAL: stress proxy = DefiLlama supply-APY (recomputed history, scrape-time stamps). "
            "Any survivor MUST be re-confirmed on the block-timestamped Aave subgraph."
        )

    z = _rolling_z(stress.level, STRESS_LOOKBACK)
    gates = _gate_settings()
    cells: list[CellResult] = []
    any_promoted = False
    any_adds_ic = False

    for symbol in sorted(market):
        bars = market[symbol]
        if len(bars) < 120:
            continue
        z_aligned = _align_stress_to_bars(bars, stress, z)
        spike = [(zi is not None and zi > STRESS_Z_K) for zi in z_aligned]
        n_spikes = sum(spike)

        equity, bar_ts, trades = _simulate_overlay(bars, spike)
        run = _build_symbol_run(equity, bar_ts, trades)
        closes = [float(b.close) for b in bars]
        # this cell's OWN net-of-fee buy-and-hold over its window (the brut beat-B&H benchmark)
        bnh = closes[-1] / closes[0] - 1.0 - 2 * MAKER_FEE
        metrics = metrics_for_run(run, trials=1, buy_and_hold=bnh, holdout_run=None)
        cand = Candidate(id=f"aave_stress::{symbol}::{VENUE_ID}", metrics=metrics,
                         net_profit=float(metrics.oos_return), source="aave_stress")
        promo = promote_brut([cand], gates)[0]

        # ---- disconfirmer (a): IC over trailing-vol + funding controls --------------------------------------
        fwd_vol = _forward_vol(closes, HORIZON_DAYS)
        trail_vol = _realized_vol(closes)
        funding = _funding_control(symbol, bars)
        xs: list[float] = []   # stress z on decision day
        ys: list[float] = []   # forward realized vol
        c_vol: list[float] = []
        c_fund: list[float] = []
        for i in range(len(bars)):
            zi = z_aligned[i]
            fv = fwd_vol[i]
            tv = trail_vol[i]
            if zi is None or fv is None or tv is None:
                continue
            xs.append(zi)
            ys.append(fv)
            c_vol.append(tv)
            c_fund.append(funding[i] if funding[i] is not None else 0.0)
        controls = [c_vol]
        if any(f != 0.0 for f in c_fund):
            controls.append(c_fund)
        raw_ic, partial_ic, n_ic = _partial_ic(xs, ys, controls)
        # "adds IC over vol/funding" = the partial IC is materially non-zero (>=0.05 in magnitude) and keeps the
        # sign of the raw IC (the stress signal still carries forward-vol info after the controls are removed).
        adds_ic = abs(partial_ic) >= 0.05 and (partial_ic * raw_ic > 0) and n_ic >= 30

        # ---- disconfirmer (b): shuffle + lag placebos must NOT survive --------------------------------------
        z_shuf = _rolling_z(_shuffle(stress.level, seed=1234567), STRESS_LOOKBACK)
        z_shuf_al = _align_stress_to_bars(bars, stress, z_shuf)
        spike_shuf = [(zi is not None and zi > STRESS_Z_K) for zi in z_shuf_al]
        eq_s, ts_s, tr_s = _simulate_overlay(bars, spike_shuf)
        run_s = _build_symbol_run(eq_s, ts_s, tr_s)
        m_s = metrics_for_run(run_s, trials=1, buy_and_hold=bnh, holdout_run=None)
        shuf_promo = promote_brut([Candidate(id=f"shuf::{symbol}", metrics=m_s, net_profit=float(m_s.oos_return), source="aave_stress_shuffle")], gates)[0]

        # lag the stress LEVEL by a large offset (decouples it from the bar it would have led) -> placebo
        lag = 17
        lvl_lag = ([stress.level[0]] * lag + stress.level)[:len(stress.level)] if len(stress.level) > lag else stress.level
        z_lag = _rolling_z(lvl_lag, STRESS_LOOKBACK)
        z_lag_al = _align_stress_to_bars(bars, stress, z_lag)
        spike_lag = [(zi is not None and zi > STRESS_Z_K) for zi in z_lag_al]
        eq_l, ts_l, tr_l = _simulate_overlay(bars, spike_lag)
        run_l = _build_symbol_run(eq_l, ts_l, tr_l)
        m_l = metrics_for_run(run_l, trials=1, buy_and_hold=bnh, holdout_run=None)
        lag_promo = promote_brut([Candidate(id=f"lag::{symbol}", metrics=m_l, net_profit=float(m_l.oos_return), source="aave_stress_lag")], gates)[0]

        cells.append(CellResult(
            symbol=symbol, venue=VENUE_ID, promoted=promo.promoted,
            deflated_sharpe_prob=round(promo.deflated_sharpe_prob, 6), num_trades=metrics.num_trades,
            net_return=round(float(metrics.oos_return), 6), sharpe=round(float(metrics.sharpe), 4),
            max_drawdown=round(float(metrics.max_drawdown), 6), reasons=list(promo.reasons),
            raw_ic=round(raw_ic, 4), partial_ic_over_vol_funding=round(partial_ic, 4),
            shuffle_promoted=shuf_promo.promoted, lag_promoted=lag_promo.promoted,
        ))
        notes.append(f"{symbol}: {n_spikes} stress spikes (z>{STRESS_Z_K}) over {len(bars)} bars")
        any_promoted = any_promoted or promo.promoted
        any_adds_ic = any_adds_ic or adds_ic

    if not cells:
        return Verdict("KILL", "no_usable_cells", False, pit_honest, stress.source, notes=notes)

    # ---- pre-registered verdict resolution -------------------------------------------------------------------
    placebo_survived = any(c.shuffle_promoted or c.lag_promoted for c in cells)
    if not any_promoted:
        wall = "no_signal"  # no cell cleared the locked BRUT gate net of maker fees
    elif placebo_survived:
        wall = "placebo_survives"  # a shuffled/lagged stress series also passes -> it's not the stress that pays
    elif not any_adds_ic:
        wall = "explained_by_vol_funding"  # the partial IC over trailing vol + funding is ~0 -> repackaged vol proxy
    else:
        wall = ""

    decision = "SURVIVOR" if wall == "" else "KILL"
    return Verdict(
        decision=decision, wall=wall, adds_ic_over_controls=any_adds_ic, pit_honest=pit_honest,
        source=stress.source, cells=cells, notes=notes,
    )


def _print_verdict(v: Verdict) -> None:
    print(f"AAVE STRESS -> 24-72h VOL CASCADE  —  {v.decision}" + (f"  (wall: {v.wall})" if v.wall else ""))
    print(f"  source: {v.source}  ·  PIT-honest(subgraph): {v.pit_honest}  ·  adds-IC-over-vol/funding: {v.adds_ic_over_controls}")
    print(f"  trade: long-by-default, step OUT {HORIZON_DAYS}d on stress z>{STRESS_Z_K}; maker fee {MAKER_FEE*10000:.0f}bps/side")
    for c in v.cells:
        flag = "PROMOTED" if c.promoted else "stop"
        print(f"  [{c.symbol} x {c.venue}] {flag:8s} DSR={c.deflated_sharpe_prob:.4f} "
              f"net={c.net_return:+.4f} sharpe={c.sharpe:+.3f} maxDD={c.max_drawdown:.3f} "
              f"trades={c.num_trades} rawIC={c.raw_ic:+.3f} partialIC={c.partial_ic_over_vol_funding:+.3f} "
              f"shufPass={c.shuffle_promoted} lagPass={c.lag_promoted}"
              + (f" reasons={c.reasons}" if c.reasons else ""))
    for n in v.notes:
        print(f"  · {n}")
    if v.decision == "SURVIVOR":
        print("\n  SURVIVOR — flag LOUDLY. Re-confirm on the block-timestamped Aave subgraph + a Modal sweep before trusting.")
    else:
        print(f"\n  KILL — wall: {v.wall}. Valid negative result; do not torture the data.")


def _main() -> int:
    v = run_experiment()
    _print_verdict(v)
    return 0 if v.decision == "SURVIVOR" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
