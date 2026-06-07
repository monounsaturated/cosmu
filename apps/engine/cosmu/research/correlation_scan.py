# intent: the HONEST alt-data correlation engine — "look for correlations" across EVERY ingested alt-data feature
# without lying. For each (feature × asset × forward-horizon) it computes the point-in-time INFORMATION COEFFICIENT
# (Spearman rank correlation of the feature value KNOWN AT t against the FORWARD return t→t+h), then controls the
# multiple-testing the naive "scan everything" invites: a BH-FDR pass over the whole grid's p-values flags which
# correlations survive (q=0.10) vs are noise you'd expect from testing N features. Invariants: PIT — the feature is
# read via align_asof (available_at ≤ bar t) and the return is strictly FUTURE, so ZERO look-ahead; PROPOSE-ONLY —
# a surviving IC is a *candidate hypothesis*, NEVER an edge (the deterministic Gate + a real purged holdout is what
# disposes; a raw correlation is not tradeable). This is the unbiased scanner that turns the data lake into ranked,
# trial-counted hypotheses for `promote_cohort`; it never moves money and runs no LLM.

from __future__ import annotations

import math
from dataclasses import dataclass

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
from cosmu.knowledge.store import Store
from cosmu.master.fdr import benjamini_hochberg


@dataclass(frozen=True)
class ICResult:
    feature: str
    source: str
    asset: str
    horizon: int
    ic: float          # Spearman rank correlation, feature_t vs forward return t→t+h
    n_obs: int
    p_value: float
    survived_fdr: bool = False


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # average rank for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_ic(xs: list[float], ys: list[float]) -> tuple[float, float, int]:
    """Spearman rank correlation + a two-sided t-based p-value. Returns (ic, p, n). Fail-closed (0, 1, n) when
    degenerate (n<10 or zero variance) — never a fabricated correlation."""
    n = len(xs)
    if n < 10:
        return 0.0, 1.0, n
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = math.sqrt(sum((v - mx) ** 2 for v in rx))
    vy = math.sqrt(sum((v - my) ** 2 for v in ry))
    if vx == 0 or vy == 0:
        return 0.0, 1.0, n
    ic = cov / (vx * vy)
    ic = max(-0.999999, min(0.999999, ic))
    t = ic * math.sqrt((n - 2) / (1 - ic * ic))
    # two-sided p via a normal approximation to the t (n is large in practice) — good enough for ranking + FDR.
    p = 2.0 * (1.0 - _norm_cdf(abs(t)))
    return round(ic, 5), round(p, 6), n


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _forward_returns(bars: list[Bar], horizon: int) -> dict[str, float]:
    """ts.isoformat() → the forward return close_t → close_{t+horizon} (strictly future; no look-ahead)."""
    out: dict[str, float] = {}
    for i in range(len(bars) - horizon):
        p0, p1 = float(bars[i].close), float(bars[i + horizon].close)
        if p0 > 0:
            out[bars[i].ts.isoformat()] = (p1 / p0) - 1.0
    return out


def scan_feature_asset(provider: StoreBackedAltProvider, feature: str, source: str, asset: str,
                       bars: list[Bar], horizons: tuple[int, ...]) -> list[ICResult]:
    """One feature × one asset: PIT-join the feature onto the bars, then IC vs each forward horizon. Tries the
    asset symbol then the market-wide 'MARKET' scope (many alt series are market-wide). Empty if no data."""
    joined: dict[str, float] = {}
    for sym in (asset, "MARKET"):
        try:
            pts = provider.fetch_series(sym, feature, limit=len(bars) + 2400)
        except Exception:  # noqa: BLE001 — a missing/unreadable series is an honest skip
            pts = []
        if pts:
            joined = align_asof(pts, bars)
            if joined:
                break
    results: list[ICResult] = []
    for h in horizons:
        fwd = _forward_returns(bars, h)
        keys = [k for k in joined if k in fwd]  # chronological (align_asof preserves bar order)
        # STRIDE-SAMPLE by the horizon so the forward windows DON'T OVERLAP — overlapping h-day returns make
        # adjacent obs massively autocorrelated, shrinking the EFFECTIVE n far below the raw count and making the
        # p-value (and any FDR built on it) wildly over-optimistic. Non-overlapping sampling = honest n, honest p.
        keys = keys[::h] if h > 1 else keys
        if len(keys) < 20:
            continue
        ic, p, n = spearman_ic([joined[k] for k in keys], [fwd[k] for k in keys])
        results.append(ICResult(feature=feature, source=source, asset=asset, horizon=h, ic=ic, n_obs=n, p_value=p))
    return results


@dataclass(frozen=True)
class ScanReport:
    n_tests: int
    n_survived_fdr: int
    results: list[ICResult]  # ALL, sorted by |ic| desc; survived_fdr flagged


def run_correlation_scan(store: Store, market: dict[str, list[Bar]], *,
                         horizons: tuple[int, ...] = (1, 5, 20), fdr_q: float = 0.10,
                         features: list[str] | None = None) -> ScanReport:
    """Scan EVERY enabled alt feature × asset × horizon for a PIT forward-return IC, then BH-FDR over the whole
    grid. Returns ranked results with survived_fdr flagged. PROPOSE-ONLY — survivors are candidate hypotheses for
    the Gate, not edges. Deterministic for a fixed store + bars."""
    provider = StoreBackedAltProvider(PgAltDataStore(store))
    feats = [(f.name, f.source) for f in FEATURE_REGISTRY if f.enabled and (features is None or f.name in features)]
    all_results: list[ICResult] = []
    for asset, bars in market.items():
        if len(bars) < 40:
            continue
        for name, source in feats:
            all_results.extend(scan_feature_asset(provider, name, source, asset, bars, horizons))

    if not all_results:
        return ScanReport(0, 0, [])
    mask = benjamini_hochberg([r.p_value for r in all_results], q=fdr_q)
    flagged = [
        ICResult(r.feature, r.source, r.asset, r.horizon, r.ic, r.n_obs, r.p_value, survived_fdr=bool(s))
        for r, s in zip(all_results, mask, strict=True)
    ]
    flagged.sort(key=lambda r: abs(r.ic), reverse=True)
    return ScanReport(n_tests=len(flagged), n_survived_fdr=sum(1 for r in flagged if r.survived_fdr), results=flagged)


_DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"]


def _main() -> int:
    """Run the scan against the configured store (prod Postgres on Modal/Railway, where the alt_data lives) and
    print the strongest forward-return correlations + which survive BH-FDR. PROPOSE-ONLY — survivors feed the Gate."""
    import os

    from cosmu.config.settings import get_settings
    from cosmu.data.market import BinanceSpotOHLCVProvider
    from cosmu.knowledge.store import Store

    prov = BinanceSpotOHLCVProvider()
    universe = os.environ.get("SCAN_UNIVERSE", ",".join(_DEFAULT_UNIVERSE)).split(",")
    market = {s: prov.fetch_bars(s, "1d", limit=1500) for s in universe}
    rep = run_correlation_scan(Store(get_settings()), market)
    print(f"CORRELATION SCAN — {rep.n_tests} tests · {rep.n_survived_fdr} survived BH-FDR (q=0.10) · PROPOSE-ONLY (the Gate disposes)")
    print(f"{'feature':28s} {'source':14s} {'asset':9s} {'h':>3s} {'IC':>8s} {'n':>5s} {'p':>8s}  FDR")
    for r in rep.results[:40]:
        print(f"  {r.feature[:26]:26s} {r.source[:12]:12s} {r.asset:9s} {r.horizon:>3d} {r.ic:>+8.4f} {r.n_obs:>5d} {r.p_value:>8.4f}  {'✓' if r.survived_fdr else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
