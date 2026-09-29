# intent: the CROSSING engine — find correlations BETWEEN alt-data sources, not just feature→return. The single-
# feature correlation_scan asks "does feature A predict the forward return of asset X"; THIS asks the orthogonal,
# creative question: "which SOURCES move together, and which LEAD each other?" For every unordered PAIR of enabled
# features (A, B) it PIT-aligns both onto the SAME bar timeline (align_asof — each series carries the value KNOWN AT
# bar t, never a future revision), then computes their Spearman cross-correlation at a CONTEMPORANEOUS lag (0) and at
# POSITIVE lags k>0 (does A_t lead B_{t+k}? — strictly past→future, zero look-ahead), and BH-FDR over the WHOLE pair
# grid so "scan every pair" can't manufacture a coincidence by sheer count. Invariants mirror correlation_scan:
# HONEST n — the lagged samples are STRIDE-SAMPLED by (lag+1) so adjacent windows don't overlap and inflate the
# effective n / deflate the p (a lag-0 pair is sampled every bar; a lag-k pair every k+1 bars); PIT — both legs read
# via align_asof, the lead leg only ever looks BACKWARD in time, so there is no peeking; PROPOSE-ONLY — a surviving
# pair correlation is a TRACKED observation about the data lake's structure, NEVER an edge and NEVER a gate decision
# (the deterministic Gate is the disposal layer). NON-CAUSAL pairs are ACCEPTED and FLAGGED, not dropped: if EITHER
# constituent is a registered non-causal / orthogonality control, the persisted finding carries that honest note so
# the UI can track the pair without ever letting a known-false relationship masquerade as structure. TRACKING: every
# ranked pair finding is written to the SAME `correlation_findings` table the single scan uses (reusing the ledger's
# CorrelationPersist + column order + event), encoding the pair as feature="A~B", source="cross-feature", and
# horizon=lag — so the existing read side (latest_findings / feature_history) and the API surface pair findings with
# zero schema change. `run_cross_feature_sweep` / `--sweep` is the "find every pair, track every pair" front door.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
from cosmu.knowledge.store import Store
from cosmu.master.fdr import benjamini_hochberg
from cosmu.research.correlation_scan import scan_universe, spearman_ic

if TYPE_CHECKING:
    from cosmu.master.correlation_ledger import CorrelationPersist

log = logging.getLogger(__name__)

# The separator that encodes an unordered feature PAIR in the `correlation_findings.feature` column. A single-feature
# scan row never contains it, so the API/UI can split a pair row ("A~B") from a feature→return row purely on this
# character. `~` is illegal in a feature_registry name (names are snake_case), so the encoding is collision-free.
PAIR_SEP = "~"
# The constant `source` tag that marks a row as a cross-feature pair finding (vs a feature's real registry source on
# a single-feature scan row). Lets the read side filter the CROSSING view from the feature→return view in one column.
CROSS_SOURCE = "cross-feature"


def encode_pair(a: str, b: str) -> str:
    """Encode an unordered feature pair into the `feature` column as "A~B" with the two names SORTED — so the pair
    (A, B) and (B, A) always land under the SAME key and a pair is tracked as one series across runs, never split."""
    lo, hi = sorted((a, b))
    return f"{lo}{PAIR_SEP}{hi}"


def decode_pair(encoded: str) -> tuple[str, str] | None:
    """Split a "A~B" feature key back into its two constituent feature names; None if it is not a pair encoding (a
    plain single-feature scan row). Lets the API/UI read the two sources of a CROSSING finding with no schema change."""
    if PAIR_SEP not in encoded:
        return None
    a, b = encoded.split(PAIR_SEP, 1)
    return a, b


@dataclass(frozen=True)
class PairICResult:
    """One cross-feature finding: the Spearman cross-correlation of feature `a` (at bar t) against feature `b` (at
    bar t+lag) on `asset`'s timeline. lag=0 is contemporaneous ("move together"); lag>0 is a LEAD ("a leads b by
    lag bars", strictly past→future). `feature` is the persisted pair key (encode_pair) so this object drops straight
    into the ledger's column order. PROPOSE-ONLY: a finding is a tracked observation about the data, never an edge."""

    a: str
    b: str
    asset: str
    lag: int
    ic: float          # Spearman rank correlation, a_t vs b_{t+lag}
    n_obs: int
    p_value: float
    survived_fdr: bool = False
    deflated_note: str = ""

    @property
    def feature(self) -> str:
        """The persisted pair key "A~B" (sorted) — the encoding the ledger/API read as one tracked pair series."""
        return encode_pair(self.a, self.b)


def _aligned_pair(a_vals: dict[str, float], b_vals: dict[str, float], bars: list[Bar],
                  lag: int) -> tuple[list[float], list[float]]:
    """Build the (a_t, b_{t+lag}) sample for one lag on the SHARED bar timeline, STRIDE-SAMPLED by (lag+1) so the
    windows don't overlap (honest n, honest p — overlapping lagged windows are autocorrelated, which would deflate
    the p-value and inflate any FDR built on it). Chronological: bars are visited in time order, so a positive lag
    pairs a PAST a-value with a STRICTLY LATER b-value — the lead leg never looks into the future. Only bars where
    BOTH legs have a PIT value contribute (a bar missing either series is an honest skip, never fabricated)."""
    keys = [b.ts.isoformat() for b in sorted(bars, key=lambda x: x.ts)]
    xs: list[float] = []
    ys: list[float] = []
    stride = lag + 1  # lag 0 → every bar; lag k → every k+1 bars, so consecutive samples share no window
    for i in range(0, len(keys) - lag, stride):
        ka, kb = keys[i], keys[i + lag]
        if ka in a_vals and kb in b_vals:
            xs.append(a_vals[ka])
            ys.append(b_vals[kb])
    return xs, ys


def _fetch_aligned(provider: StoreBackedAltProvider, feature: str, asset: str,
                   bars: list[Bar]) -> dict[str, float]:
    """PIT-join ONE feature's series onto the bar timeline (bar.ts.isoformat() → the value KNOWN AT that bar). Tries
    the asset symbol then the market-wide 'MARKET' scope (most alt series are market-wide), exactly like the single
    scan. Empty dict when the store has no series for this feature (an honest skip, never a fabricated series)."""
    for sym in (asset, "MARKET"):
        try:
            pts = provider.fetch_series(sym, feature, limit=len(bars) + 2400)
        except Exception:  # noqa: BLE001 — a missing/unreadable/unrouted series is an honest skip
            pts = []
        if pts:
            joined = align_asof(pts, bars)
            if joined:
                return joined
    return {}


def _pair_note(a: str, b: str) -> str:
    """The HONEST non-causal note for a PAIR: a pair is flagged the moment EITHER constituent is a registered
    non-causal / orthogonality control (a strong cross-correlation that involves a known-false baseline is a
    data-snooping red flag about the data's structure, NOT a relationship to trust). Reuses the ledger's
    per-feature note (single source of causal-honesty truth); the pair carries it prefixed with which leg it came
    from. Empty when both legs are plain causal features."""
    from cosmu.master.correlation_ledger import deflated_note_for

    na, nb = deflated_note_for(a), deflated_note_for(b)
    if na and nb:
        return f"{a}: {na} | {b}: {nb}"
    if na:
        return f"{a}: {na}"
    if nb:
        return f"{b}: {nb}"
    return ""


def scan_pair(a_vals: dict[str, float], b_vals: dict[str, float], a: str, b: str, asset: str,
              bars: list[Bar], lags: tuple[int, ...], *, min_obs: int = 20) -> list[PairICResult]:
    """One feature pair on one asset's timeline: the Spearman cross-correlation at each lag (0 = contemporaneous,
    k>0 = a leads b by k bars). Honest n (non-overlapping stride-sample) and PIT (the lead leg only looks back).
    Skips a lag with too few non-overlapping samples (< min_obs) — never a fabricated correlation on thin data."""
    note = _pair_note(a, b)
    results: list[PairICResult] = []
    for lag in lags:
        xs, ys = _aligned_pair(a_vals, b_vals, bars, lag)
        if len(xs) < min_obs:
            continue
        ic, p, n = spearman_ic(xs, ys)
        results.append(PairICResult(a=a, b=b, asset=asset, lag=lag, ic=ic, n_obs=n, p_value=p, deflated_note=note))
    return results


@dataclass(frozen=True)
class CrossScanReport:
    n_tests: int
    n_survived_fdr: int
    results: list[PairICResult]  # ALL, sorted by |ic| desc; survived_fdr flagged


def run_cross_feature_scan(store: Store, market: dict[str, list[Bar]], *,
                           lags: tuple[int, ...] = (0, 1, 5), fdr_q: float = 0.10,
                           features: list[str] | None = None, min_obs: int = 20,
                           persist: "CorrelationPersist | None" = None) -> CrossScanReport:
    """Scan EVERY unordered pair of enabled features × asset × lag for a PIT cross-correlation, then BH-FDR over the
    WHOLE pair grid. Returns ranked results (|ic| desc) with survived_fdr flagged. PROPOSE-ONLY — survivors are
    tracked observations about how sources move together / lead each other, NEVER edges (the Gate disposes). NON-
    CAUSAL pairs are kept + flagged (deflated_note). Deterministic for a fixed store + bars. When `persist` is given
    (opt-in, exactly like the single scan), every ranked pair is TRACKED to `correlation_findings` best-effort — a
    persist failure NEVER changes the returned report or breaks the scan."""
    provider = StoreBackedAltProvider(PgAltDataStore(store))
    feats = [name for name, _ in scan_universe(features)]
    all_results: list[PairICResult] = []
    for _asset, bars in market.items():
        if len(bars) < 40:
            continue
        # PIT-join every feature ONCE per asset (not once per pair) — the align is the expensive part; the pair loop
        # then reuses the cached series. A feature with no store data joins to {} and simply never pairs.
        joined: dict[str, dict[str, float]] = {f: _fetch_aligned(provider, f, _asset, bars) for f in feats}
        present = [f for f in feats if joined[f]]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = present[i], present[j]
                all_results.extend(
                    scan_pair(joined[a], joined[b], a, b, _asset, bars, lags, min_obs=min_obs)
                )

    if not all_results:
        return CrossScanReport(0, 0, [])
    mask = benjamini_hochberg([r.p_value for r in all_results], q=fdr_q)
    flagged = [
        PairICResult(r.a, r.b, r.asset, r.lag, r.ic, r.n_obs, r.p_value,
                     survived_fdr=bool(s), deflated_note=r.deflated_note)
        for r, s in zip(all_results, mask, strict=True)
    ]
    flagged.sort(key=lambda r: abs(r.ic), reverse=True)
    if persist is not None:
        persist_pair_findings(persist, flagged)  # best-effort + offline-safe — never raises, never alters the report
    return CrossScanReport(n_tests=len(flagged), n_survived_fdr=sum(1 for r in flagged if r.survived_fdr), results=flagged)


# ── persistence: reuse the SAME correlation_findings table + the ledger's CorrelationPersist (READ-ONLY ledger) ──
# We do NOT edit correlation_ledger; we reuse its persistence contract (CorrelationPersist + the column order + the
# scan-run event) and write a pair row in the IDENTICAL shape — the only difference is the pair-aware deflated_note,
# which the ledger's per-feature persist can't compute for an "A~B" key (a registry lookup on a pair name misses).
# Encoding: feature="A~B" (sorted), source="cross-feature", asset=the alignment scope, horizon=lag.

def _pair_columns(run_id: str, ts: str, data_source: str, r: PairICResult) -> tuple[object, ...]:
    """Flatten one PairICResult into the `correlation_findings` column order (the ledger's _COLUMNS), encoding the
    pair as feature="A~B" / source="cross-feature" / horizon=lag and carrying the pair-aware non-causal note."""
    return (
        run_id,
        ts,
        r.feature,        # "A~B" — the encoded, sorted pair key
        CROSS_SOURCE,     # constant tag: this is a cross-feature pair row, not a feature→return row
        str(r.asset),     # the PIT-alignment scope the pair was measured on
        int(r.lag),       # horizon column carries the LAG (0 = contemporaneous, k>0 = a leads b by k bars)
        float(r.ic),
        int(r.n_obs),
        float(r.p_value),
        1 if bool(r.survived_fdr) else 0,
        r.deflated_note,
        data_source,
    )


def persist_pair_findings(persist: "CorrelationPersist", results: list[PairICResult]) -> int:
    """Write one `correlation_findings` row PER pair finding (one transaction) + a `cross_feature_scan_run` event,
    reusing the ledger's CorrelationPersist + column order + Store batch — no ledger edit, no schema change. Returns
    rows written (0 on empty or on ANY failure, which it swallows + logs: a findings-persist must NEVER break a scan
    run). PROPOSE-ONLY: tracked correlation memory, never a gate decision and never money. Best-effort + offline-safe,
    mirroring the ledger's own persist_findings."""
    if not results:
        return 0
    try:
        from cosmu.knowledge.store import utcnow
        from cosmu.master.correlation_ledger import _COLUMNS  # reuse the EXACT column order (one source of truth)

        ts = utcnow()
        rows = [_pair_columns(persist.run_id, ts, persist.data_source, r) for r in results]
        with persist.store.batch() as writer:
            writer.insert_many("correlation_findings", _COLUMNS, rows)
            n_survived = sum(1 for r in results if r.survived_fdr)
            writer.append_event(
                actor="master",
                kind="cross_feature_scan_run",
                ref_type="cross_feature_scan",
                ref_id=persist.run_id,
                payload={"n_pairs": len(rows), "n_survived_fdr": n_survived, "data_source": persist.data_source},
            )
        return len(rows)
    except Exception:  # noqa: BLE001 — a findings-persist failure must never break the research/scan path.
        log.warning("persist_pair_findings failed for run_id=%s (%d results)", persist.run_id, len(results),
                    exc_info=True)
        return 0


# ── the "find every pair, track every pair" sweep front door ────────────────────────────────────────────────────
_SWEEP_LAGS = (0, 1, 3, 5, 10)  # contemporaneous + a broad lead grid for the full pair sweep


def new_run_id(prefix: str = "crossscan") -> str:
    """A unique, sortable run_id stamping every pair finding of ONE scan together (so a run is queryable as a unit
    and runs compare over time for decay-tracking). Reuses the single-scan id format for consistency."""
    from cosmu.research.correlation_scan import new_run_id as _single_run_id

    return _single_run_id(prefix)


def run_cross_feature_sweep(*, assets: list[str] | None = None, lags: tuple[int, ...] = _SWEEP_LAGS,
                            fdr_q: float = 0.10, persist: bool = True, bars_limit: int = 1500,
                            run_id: str | None = None) -> CrossScanReport:
    """The "find every pair, track every pair" run: scan the FULL pair grid — every unordered pair of enabled
    features × the configured asset universe × the broad lag grid — for a PIT cross-correlation, BH-FDR over the whole
    grid, and (opt-in, default ON for this front door) PERSIST every pair to `correlation_findings` under one stamped
    run_id so the CROSSING is TRACKED across runs. PROPOSE-ONLY — survivors are tracked observations, never edges.
    Degrades gracefully: a feature with no store data never pairs; an asset whose bars fail to load is skipped. Reuses
    the single scan's configured asset universe so the two sweeps visit the SAME universe."""
    from cosmu.config.settings import get_settings
    from cosmu.data.market import default_crypto_reference
    from cosmu.research.correlation_scan import _sweep_universe

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

        persist_spec = CorrelationPersist(store=store, run_id=run_id or new_run_id("crosssweep"), data_source="live")
    return run_cross_feature_scan(store, market, lags=lags, fdr_q=fdr_q, persist=persist_spec)


def _print_report(rep: CrossScanReport, header: str) -> None:
    print(f"{header} — {rep.n_tests} pair-tests · {rep.n_survived_fdr} survived BH-FDR (q=0.10) · PROPOSE-ONLY (the Gate disposes)")
    print(f"{'pair (a ~ b)':40s} {'asset':9s} {'lag':>4s} {'IC':>8s} {'n':>5s} {'p':>8s}  FDR  note")
    for r in rep.results[:40]:
        flag = "OK" if r.survived_fdr else ""
        nc = "  [non-causal]" if r.deflated_note else ""
        print(f"  {r.feature[:38]:38s} {r.asset:9s} {r.lag:>4d} {r.ic:>+8.4f} {r.n_obs:>5d} {r.p_value:>8.4f}  {flag:>3s}{nc}")


def _main() -> int:
    """Run the cross-feature scan against the configured store (prod Postgres on Modal/Railway, where the alt_data
    lives) and print the strongest pair correlations + which survive BH-FDR. PROPOSE-ONLY — survivors are tracked
    observations about the data's structure, not edges.

    `--sweep` runs the FULL pair grid (every enabled feature pair × the configured asset universe × the broad lag
    grid) and PERSISTS every pair to `correlation_findings` under one stamped run_id — the "find every pair, track
    every pair" run, mirroring `correlation_scan --sweep`. CLI overrides: `--assets BTC,ETH`, `--lags 0,1,5`,
    `--no-persist`. The default (no `--sweep`) is the print-only majors scan and does NOT persist."""
    import os
    import sys

    from cosmu.config.settings import get_settings
    from cosmu.data.market import default_crypto_reference
    from cosmu.research.correlation_scan import _DEFAULT_UNIVERSE

    do_sweep = "--sweep" in sys.argv or os.environ.get("CROSS_FEATURE_SWEEP") == "1"
    persist = "--no-persist" not in sys.argv and os.environ.get("CROSS_FEATURE_PERSIST", "1") == "1"

    cli_assets: list[str] | None = None
    cli_lags: tuple[int, ...] | None = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--assets" and i < len(sys.argv):
            cli_assets = [a.strip() for a in sys.argv[i + 1].split(",") if a.strip()]
        if arg == "--lags" and i < len(sys.argv):
            cli_lags = tuple(int(h) for h in sys.argv[i + 1].split(",") if h.strip())

    if do_sweep:
        rep = run_cross_feature_sweep(assets=cli_assets, lags=cli_lags or _SWEEP_LAGS, persist=persist)
        _print_report(rep, "CROSS-FEATURE SWEEP (full pair grid · tracked)")
        return 0

    prov = default_crypto_reference()
    universe = cli_assets or os.environ.get("SCAN_UNIVERSE", ",".join(_DEFAULT_UNIVERSE)).split(",")
    market = {s: prov.fetch_bars(s, "1d", limit=1500) for s in universe}
    persist_spec: "CorrelationPersist | None" = None
    if persist and "--persist" in sys.argv:  # the single scan persists ONLY when explicitly asked (--persist)
        from cosmu.master.correlation_ledger import CorrelationPersist

        persist_spec = CorrelationPersist(store=Store(get_settings()), run_id=new_run_id(), data_source="live")
    rep = run_cross_feature_scan(Store(get_settings()), market, lags=cli_lags or (0, 1, 5), persist=persist_spec)
    _print_report(rep, "CROSS-FEATURE SCAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
