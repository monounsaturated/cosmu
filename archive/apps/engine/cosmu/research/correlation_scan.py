# intent: the HONEST alt-data correlation engine — "look for correlations" across EVERY ingested alt-data feature
# without lying. For each (feature × asset × forward-horizon) it computes the point-in-time INFORMATION COEFFICIENT
# (Spearman rank correlation of the feature value KNOWN AT t against the FORWARD return t→t+h), then controls the
# multiple-testing the naive "scan everything" invites: a BH-FDR pass over the whole grid's p-values flags which
# correlations survive (q=0.10) vs are noise you'd expect from testing N features. Invariants: PIT — the feature is
# read via align_asof (available_at ≤ bar t) and the return is strictly FUTURE, so ZERO look-ahead; PROPOSE-ONLY —
# a surviving IC is a *candidate hypothesis*, NEVER an edge (the deterministic Gate + a real purged holdout is what
# disposes; a raw correlation is not tradeable). This is the unbiased scanner that turns the data lake into ranked,
# trial-counted hypotheses for `promote_cohort`; it never moves money and runs no LLM. TRACKING: pass a
# CorrelationPersist (opt-in, default off so tests stay clean) and every ranked finding is written to
# `correlation_findings` under one stamped run_id — so correlations are remembered + decay-tracked across runs, not
# just printed. `run_correlation_sweep` / `--sweep` is the "find everything, track everything" front door: the FULL
# grid (every enabled feature × the configured asset universe × a broad horizon grid), persisted, degrading
# gracefully (a feature with no store data is an honest skip, never fabricated).

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
from cosmu.knowledge.store import Store
from cosmu.master.fdr import benjamini_hochberg

if TYPE_CHECKING:
    from cosmu.master.correlation_ledger import CorrelationPersist


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


def scan_universe(features: list[str] | None = None) -> list[tuple[str, str]]:
    """The scan's feature universe as (name, source) pairs, READ FROM THE FEATURE REGISTRY — the single source of
    truth — so EVERY enabled feature is scanned the moment it is registered (a newly-wired alt-data source is picked
    up automatically; no hardcoded list to drift out of date). Every enabled FeatureDefinition qualifies; a missing
    store series is an honest skip downstream (scan_feature_asset), never fabricated. `features`, when given,
    restricts to that subset (still gated on enabled), for targeted re-scans."""
    return [(f.name, f.source) for f in FEATURE_REGISTRY if f.enabled and (features is None or f.name in features)]


def run_correlation_scan(store: Store, market: dict[str, list[Bar]], *,
                         horizons: tuple[int, ...] = (1, 5, 20), fdr_q: float = 0.10,
                         features: list[str] | None = None,
                         persist: "CorrelationPersist | None" = None) -> ScanReport:
    """Scan EVERY enabled alt feature × asset × horizon for a PIT forward-return IC, then BH-FDR over the whole
    grid. Returns ranked results with survived_fdr flagged. PROPOSE-ONLY — survivors are candidate hypotheses for
    the Gate, not edges. Deterministic for a fixed store + bars. When `persist` is given (opt-in, exactly like
    promote_cohort opts into verdict_log), the ranked findings are TRACKED to `correlation_findings` best-effort —
    a persist failure NEVER changes the returned report or breaks the scan."""
    provider = StoreBackedAltProvider(PgAltDataStore(store))
    feats = scan_universe(features)
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
    if persist is not None:
        from cosmu.master.correlation_ledger import persist_findings  # lazy: keep the scan importable w/o the ledger

        persist_findings(persist, flagged)  # best-effort + offline-safe — never raises, never alters the report
    return ScanReport(n_tests=len(flagged), n_survived_fdr=sum(1 for r in flagged if r.survived_fdr), results=flagged)


_DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"]
_SWEEP_HORIZONS = (1, 3, 5, 10, 20, 60)  # the broad horizon grid for the "find everything, track everything" run


def _sweep_universe() -> list[str]:
    """The full sweep asset universe, READ FROM CONFIG (reuses matrix_sweep_assets — the single configured asset
    universe, so the operator widens the grid in one place with no scanner edit), falling back to the built-in
    majors offline. Mirrors matrix_search._default_assets so the two sweeps visit the SAME universe."""
    try:
        from cosmu.config.settings import get_settings

        cfg = get_settings()
        if cfg.matrix_sweep_assets:
            return list(cfg.matrix_sweep_assets)
    except Exception:  # noqa: BLE001 — offline/test context: fall through to the built-in majors
        pass
    return list(_DEFAULT_UNIVERSE)


def new_run_id(prefix: str = "corrscan") -> str:
    """A unique, sortable run_id stamping every finding of ONE scan together (so a run is queryable as a unit and
    runs are comparable over time for decay-tracking). UTC timestamp + a short random suffix; deterministic format,
    not deterministic value (each run is its own row group, exactly like a matrix sweep)."""
    import secrets
    from datetime import UTC, datetime

    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def run_correlation_sweep(*, assets: list[str] | None = None, horizons: tuple[int, ...] = _SWEEP_HORIZONS,
                          fdr_q: float = 0.10, persist: bool = True, bars_limit: int = 1500,
                          run_id: str | None = None) -> ScanReport:
    """The "find everything, track everything" run: scan the FULL grid — EVERY enabled feature_registry feature ×
    the configured asset universe × the broad horizon grid — for a PIT forward-return IC, BH-FDR over the whole
    grid, and (opt-in, default ON for this front door) PERSIST every finding to `correlation_findings` under one
    stamped run_id so the correlations are TRACKED across runs. PROPOSE-ONLY — survivors are candidate hypotheses
    for the Gate, never edges. Degrades gracefully: a feature with no store data is an honest skip downstream
    (scan_feature_asset returns empty), never fabricated; an asset whose bars fail to load is skipped. The same
    honest non-overlapping stride-sampling + BH-FDR as the single scan."""
    from cosmu.config.settings import get_settings
    from cosmu.data.market import default_crypto_reference
    from cosmu.knowledge.store import Store

    prov = default_crypto_reference()
    universe = assets or _sweep_universe()
    market: dict[str, list[Bar]] = {}
    for sym in universe:
        try:
            market[sym] = prov.fetch_bars(sym, "1d", limit=bars_limit)
        except Exception:  # noqa: BLE001 — an unfetchable asset is an honest skip, never a fabricated series
            continue

    store = Store(get_settings())
    persist_spec: "CorrelationPersist | None" = None
    if persist:
        from cosmu.master.correlation_ledger import CorrelationPersist

        persist_spec = CorrelationPersist(store=store, run_id=run_id or new_run_id("sweep"), data_source="live")
    return run_correlation_scan(store, market, horizons=horizons, fdr_q=fdr_q, persist=persist_spec)


def _print_report(rep: ScanReport, header: str) -> None:
    print(f"{header} — {rep.n_tests} tests · {rep.n_survived_fdr} survived BH-FDR (q=0.10) · PROPOSE-ONLY (the Gate disposes)")
    print(f"{'feature':28s} {'source':14s} {'asset':9s} {'h':>3s} {'IC':>8s} {'n':>5s} {'p':>8s}  FDR")
    for r in rep.results[:40]:
        print(f"  {r.feature[:26]:26s} {r.source[:12]:12s} {r.asset:9s} {r.horizon:>3d} {r.ic:>+8.4f} {r.n_obs:>5d} {r.p_value:>8.4f}  {'✓' if r.survived_fdr else ''}")


def _main() -> int:
    """Run the scan against the configured store (prod Postgres on Modal/Railway, where the alt_data lives) and
    print the strongest forward-return correlations + which survive BH-FDR. PROPOSE-ONLY — survivors feed the Gate.

    `--sweep` runs the FULL grid (every enabled feature × the configured asset universe × the broad horizon grid)
    and PERSISTS every finding to `correlation_findings` under one stamped run_id — the "find everything, track
    everything" run, mirroring `matrix_search --sweep`. CLI overrides: `--assets BTC,ETH`, `--horizons 1,5,20`,
    `--no-persist`. The default (no `--sweep`) is the print-only majors scan and does NOT persist."""
    import os
    import sys

    from cosmu.config.settings import get_settings
    from cosmu.data.market import default_crypto_reference
    from cosmu.knowledge.store import Store

    do_sweep = "--sweep" in sys.argv or os.environ.get("CORRELATION_SWEEP") == "1"
    persist = "--no-persist" not in sys.argv and os.environ.get("CORRELATION_PERSIST", "1") == "1"

    cli_assets: list[str] | None = None
    cli_horizons: tuple[int, ...] | None = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--assets" and i < len(sys.argv):
            cli_assets = [a.strip() for a in sys.argv[i + 1].split(",") if a.strip()]
        if arg == "--horizons" and i < len(sys.argv):
            cli_horizons = tuple(int(h) for h in sys.argv[i + 1].split(",") if h.strip())

    if do_sweep:
        rep = run_correlation_sweep(
            assets=cli_assets, horizons=cli_horizons or _SWEEP_HORIZONS, persist=persist,
        )
        _print_report(rep, "CORRELATION SWEEP (full grid · tracked)")
        return 0

    prov = default_crypto_reference()
    universe = cli_assets or os.environ.get("SCAN_UNIVERSE", ",".join(_DEFAULT_UNIVERSE)).split(",")
    market = {s: prov.fetch_bars(s, "1d", limit=1500) for s in universe}
    persist_spec: "CorrelationPersist | None" = None
    if persist and "--persist" in sys.argv:  # the single scan persists ONLY when explicitly asked (--persist)
        from cosmu.master.correlation_ledger import CorrelationPersist

        persist_spec = CorrelationPersist(store=Store(get_settings()), run_id=new_run_id(), data_source="live")
    rep = run_correlation_scan(Store(get_settings()), market, horizons=cli_horizons or (1, 5, 20), persist=persist_spec)
    _print_report(rep, "CORRELATION SCAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
