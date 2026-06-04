# intent: the ONE managed-data control surface — `fetch` / `backfill` / `verify` / `update` over BOTH the
# alt-data store and the multi-venue bar cache, so data is a capability not a pile of one-off scripts;
# inputs: the catalog of managed sources + the injectable `Providers` set + the two stores (alt store +
# bar-cache dir); outputs: append counts (fetch/backfill/update) and a coverage report (verify); invariants:
# idempotent + point-in-time (dedup on (provider,symbol,metric,ts) for alt, on ts for bars — a re-run writes
# 0), each (source,symbol,window) fetched ONCE, free where possible (key-gated sources degrade to []),
# offline-testable (inject providers + a bar-backfiller factory + the clock; no live network in tests), and
# NOTHING here re-implements an ingest primitive — it composes run_once / backfill_funding / the catalog.

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cosmu.ingest import catalog
from cosmu.ingest.bars import CcxtBarBackfiller, StooqBarBackfiller, bar_cache_path, read_cached_bars, write_bars_cache
from cosmu.ingest.coverage import (
    CoverageReport,
    build_alt_coverage,
    build_bar_coverage,
    build_panel_coverage,
)
from cosmu.ingest.ml_panel import DEFAULT_ALT_FEATURES, build_ml_panel, write_ml_panel
from cosmu.ingest.pipeline import BackfillResult, backfill_funding

logger = logging.getLogger("cosmu.ingest.manage")

DEFAULT_MARKET_DATA_DIR = ".cosmu/market_data"
DEFAULT_PANEL_DIR = ".cosmu/ml_panels"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _default_bar_backfiller(venue: str):  # noqa: ANN202 — CcxtBarBackfiller | StooqBarBackfiller
    """Pick the bar backfiller for a venue: `stooq` → the free non-crypto daily CSV (stocks/FX/metals/index);
    every other venue (binance/kraken/bybit/okx) → ccxt OHLCV. Keeps `backfill bars:<venue>` venue-agnostic."""
    return StooqBarBackfiller() if venue == "stooq" else CcxtBarBackfiller(venue)


@dataclass
class BarBackfillResult:
    """Per (venue, symbol) bar-backfill outcome — the bar analogue of pipeline.BackfillResult."""

    venue: str
    symbol: str
    timeframe: str
    written: int
    total: int
    start: datetime | None
    end: datetime | None

    @property
    def span_days(self) -> float:
        if self.start is None or self.end is None:
            return 0.0
        return (self.end - self.start).total_seconds() / 86400.0


class DataManager:
    """The managed-data capability. One object holds the two stores (alt + bar cache) and the provider set,
    and exposes the four verbs. Everything is injectable so a test drives the whole surface offline."""

    def __init__(
        self,
        *,
        store: Any = None,  # AltDataStore | PgAltDataStore; default = the same backend the API uses
        providers: Any = None,  # Providers; default = real free providers from settings
        market_data_dir: Path | str = DEFAULT_MARKET_DATA_DIR,
        panel_dir: Path | str = DEFAULT_PANEL_DIR,
        clock: Callable[[], datetime] = _now,
        bar_backfiller_factory: Callable[[str], Any] | None = None,
        funding_history: Any = None,  # a provider exposing fetch_history; default = live Binance history
    ) -> None:
        self._store = store
        self._providers = providers
        self.market_data_dir = Path(market_data_dir)
        self.panel_dir = Path(panel_dir)
        self._clock = clock
        self._bar_backfiller_factory = bar_backfiller_factory or _default_bar_backfiller
        self._funding_history = funding_history

    # ---- lazy defaults (kept out of __init__ so tests never trigger a DB / settings read) ----

    def _get_store(self) -> Any:
        if self._store is None:
            from cosmu.ingest.run import _default_store

            store = _default_store()
            if not hasattr(store, "append"):  # a knowledge Store → wrap as the DB-backed alt store
                from cosmu.data.altdata import PgAltDataStore

                store = PgAltDataStore(store)
            self._store = store
        return self._store

    def _get_providers(self) -> Any:
        if self._providers is None:
            from cosmu.config.settings import get_settings
            from cosmu.ingest.run import Providers

            self._providers = Providers.from_settings(get_settings())
        return self._providers

    # ------------------------------------------------------------------ verbs

    def fetch(self, source: str, symbols: list[str]) -> int:
        """Pull ONE managed alt source by name into the store (incremental, idempotent). Returns appended
        count. Unknown source → ValueError (the CLI lists valid names)."""
        sources = catalog.managed_sources()
        if source not in sources:
            raise ValueError(f"unknown source {source!r}; known: {', '.join(catalog.source_names())}")
        spec = sources[source]
        return spec.fetch(self._get_store(), symbols, self._get_providers())

    def update(self, symbols: list[str] | None = None) -> dict[str, int]:
        """Incremental pass over EVERY managed source = the cron tick. Delegates to run_once (the canonical
        one-pass ingest) so there is exactly one full-sweep implementation."""
        from cosmu.ingest.run import run_once

        return run_once(self._get_store(), symbols=symbols, providers=self._providers)

    def backfill(self, source: str, *, days: int, symbols: list[str], timeframes: tuple[str, ...] = (catalog.DEFAULT_BAR_TIMEFRAME,)) -> dict[str, Any]:
        """Walk deep history for one source. `funding` → the paginated Binance funding history; `bars` (or
        `bars:<venue>`) → paginated multi-venue OHLCV via ccxt across EVERY requested timeframe. Any other alt
        source has no paginated history endpoint, so backfill falls back to a single incremental fetch (the
        honest deepest pull available)."""
        start_ms = int((self._clock().timestamp() - days * 86400) * 1000)
        if source == "funding":
            provider = self._funding_history
            if provider is None:
                from cosmu.data.altdata import BinanceFundingHistoryProvider

                provider = BinanceFundingHistoryProvider()
            results = backfill_funding(self._get_store(), provider, symbols, start_ms=start_ms)
            return {"kind": "funding", "results": results}
        if source == "bars" or source.startswith("bars:"):
            venues = (source.split(":", 1)[1],) if ":" in source else catalog.DEFAULT_BAR_VENUES
            return {"kind": "bars", "results": self.backfill_bars(venues=venues, symbols=symbols, timeframes=timeframes, start_ms=start_ms)}
        # No paginated endpoint → the deepest honest pull is one incremental fetch.
        logger.info("source %s has no paginated history; backfill falls back to one incremental fetch", source)
        return {"kind": "incremental", "written": self.fetch(source, symbols)}

    def backfill_bars(self, *, venues: tuple[str, ...], symbols: list[str], timeframes: tuple[str, ...], start_ms: int) -> dict[tuple[str, str, str], BarBackfillResult]:
        """Paginated OHLCV history per (venue, symbol, timeframe), merged into the bar cache append-only +
        deduped on ts (a re-run writes 0). Each (venue, symbol, timeframe) is fetched ONCE — the backfiller
        paginates internally. The result is keyed by the full (venue, symbol, timeframe) triple so multiple
        resolutions never collide."""
        out: dict[tuple[str, str, str], BarBackfillResult] = {}
        for venue in venues:
            backfiller = self._bar_backfiller_factory(venue)
            for symbol in symbols:
                for timeframe in timeframes:
                    bars = backfiller.fetch_history(symbol, timeframe, start_ms=start_ms)
                    path = bar_cache_path(self.market_data_dir / venue, symbol, timeframe)
                    written = write_bars_cache(path, bars)
                    out[(venue, symbol, timeframe)] = BarBackfillResult(
                        venue=venue, symbol=symbol, timeframe=timeframe, written=written, total=len(bars),
                        start=bars[0].ts if bars else None, end=bars[-1].ts if bars else None,
                    )
        return out

    def build_panels(
        self,
        symbols: list[str],
        *,
        timeframes: tuple[str, ...] = catalog.DEFAULT_BAR_TIMEFRAMES,
        alt_features: tuple[str, ...] = DEFAULT_ALT_FEATURES,
        venue: str = "binance",
    ) -> dict[tuple[str, str], int]:
        """Build + persist the ML-ready standardized point-in-time panels from the bar cache + alt store. For
        each (symbol, timeframe) it reads the cached bars (a missing/empty cache is skipped — honest, never a
        fabricated panel), joins the alt features POINT-IN-TIME, z-scores every column with an expanding window
        (no look-ahead), and append-merges the rows deduped on ts (a re-run writes 0). Returns {(symbol,
        timeframe): new_rows_written}."""
        store = self._get_store()
        out: dict[tuple[str, str], int] = {}
        for symbol in symbols:
            for timeframe in timeframes:
                bars = read_cached_bars(bar_cache_path(self.market_data_dir / venue, symbol, timeframe))
                if not bars:
                    out[(symbol, timeframe)] = 0  # no bars → no panel (honest gap; verify flags it missing)
                    continue
                panel = build_ml_panel(store, bars, symbol=symbol, timeframe=timeframe, alt_features=alt_features)
                out[(symbol, timeframe)] = write_ml_panel(self.panel_dir, panel)
        return out

    def verify(
        self,
        symbols: list[str],
        *,
        venues: tuple[str, ...] = catalog.DEFAULT_BAR_VENUES,
        timeframes: tuple[str, ...] = catalog.DEFAULT_BAR_TIMEFRAMES,
        include_bars: bool = True,
        include_panels: bool = False,
        venue: str = "binance",
    ) -> CoverageReport:
        """The data-quality report: every expected alt series (from the canonical store map) + every expected
        bar series (across all timeframes) + (optionally) every ML panel, each scored for rows / span /
        freshness / gaps / look-ahead. Read-only."""
        now = self._clock()
        series = build_alt_coverage(self._get_store(), catalog.expected_alt_specs(symbols, venue=venue), now=now)
        if include_bars:
            series += build_bar_coverage(self.market_data_dir, catalog.expected_bar_specs(symbols, venues=venues, timeframes=timeframes), now=now)
        if include_panels:
            specs = [(sym, tf) for sym in symbols for tf in timeframes]
            series += build_panel_coverage(self.panel_dir, specs, now=now)
        return CoverageReport(generated_at=now, series=series)


# --------------------------------------------------------------------------- CLI


def _report_funding(results: dict[str, BackfillResult]) -> None:
    print("FUNDING BACKFILL — Binance USDⓈ-M fundingRate history (free, no key)")
    print(f"  {'symbol':<12}{'new':>8}{'total':>8}{'days':>8}  span")
    for sym, r in results.items():
        span = f"{r.start.date()} → {r.end.date()}" if r.start and r.end else "(no data)"
        print(f"  {sym:<12}{r.written:>8}{r.total:>8}{r.span_days:>8.0f}  {span}")


def _report_bars(results: dict[tuple[str, str, str], BarBackfillResult]) -> None:
    print("BAR BACKFILL — multi-venue, multi-timeframe OHLCV history via ccxt (free, no key)")
    print(f"  {'venue':<10}{'symbol':<12}{'tf':<5}{'new':>8}{'total':>8}{'days':>8}  span")
    for (venue, sym, tf), r in results.items():
        span = f"{r.start.date()} → {r.end.date()}" if r.start and r.end else "(no data)"
        print(f"  {venue:<10}{sym:<12}{tf:<5}{r.written:>8}{r.total:>8}{r.span_days:>8.0f}  {span}")


def _symbols(arg: str) -> list[str]:
    """The widened liquid perp universe by default (carry-verdict next action: 5 → ~30 symbols), or the
    operator's explicit comma list. Deduped/normalized so a hand-typed list can never double-fetch a symbol."""
    from cosmu.data.universe import dedupe_symbols, perp_universe

    if not arg:
        return perp_universe()
    return list(dedupe_symbols(arg.split(",")))


def _timeframes(arg: str) -> tuple[str, ...]:
    """Parse a comma-separated `--timeframe` into the managed-timeframe tuple. Empty → the default managed set
    (1d/4h/1h); a single value (`--timeframe 1d`) → just that one. Deduped, order-preserving."""
    if not arg:
        return catalog.DEFAULT_BAR_TIMEFRAMES
    seen: dict[str, None] = {}
    for tf in arg.split(","):
        t = tf.strip()
        if t:
            seen.setdefault(t, None)
    return tuple(seen) or catalog.DEFAULT_BAR_TIMEFRAMES


def _main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="manage-data", description="Managed data: fetch / backfill / verify / update.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list the managed sources")  # noqa: F841

    _SYM_HELP = "comma-separated symbols (default = the ~30-symbol liquid perp universe)"
    _TF_HELP = "comma-separated timeframes (default 1d,4h,1h); a single value pulls just that resolution"

    p_fetch = sub.add_parser("fetch", help="incremental fetch of ONE source")
    p_fetch.add_argument("source", help=f"source name ({', '.join(catalog.source_names())})")
    p_fetch.add_argument("--symbols", default="", help=_SYM_HELP)

    p_back = sub.add_parser("backfill", help="deep history for a source (funding | bars[:venue])")
    p_back.add_argument("source", help="funding | bars | bars:binance | bars:kraken | <alt source>")
    p_back.add_argument("--days", type=int, default=400, help="lookback window in days (default 400 → ≥1yr)")
    p_back.add_argument("--symbols", default="", help=_SYM_HELP)
    p_back.add_argument("--timeframe", default="", help=_TF_HELP)

    p_verify = sub.add_parser("verify", help="data-quality coverage report")
    p_verify.add_argument("--symbols", default="", help=_SYM_HELP)
    p_verify.add_argument("--timeframe", default="", help=_TF_HELP)
    p_verify.add_argument("--no-bars", action="store_true", help="skip the bar-cache coverage")
    p_verify.add_argument("--panels", action="store_true", help="also report ML-panel coverage")
    p_verify.add_argument("--json", action="store_true", help="emit the report as JSON")

    p_update = sub.add_parser("update", help="incremental pass over ALL sources (the cron tick)")
    p_update.add_argument("--symbols", default="", help=_SYM_HELP)

    p_panels = sub.add_parser("panels", help="build the ML-ready standardized point-in-time panels")
    p_panels.add_argument("--symbols", default="", help=_SYM_HELP)
    p_panels.add_argument("--timeframe", default="", help=_TF_HELP)

    args = parser.parse_args(argv)

    if args.cmd == "list":
        for name, spec in sorted(catalog.managed_sources().items()):
            print(f"  {name:<16}{','.join(spec.metrics)}")
        return 0

    mgr = DataManager()
    symbols = _symbols(args.symbols)

    if args.cmd == "fetch":
        n = mgr.fetch(args.source, symbols)
        print(f"fetched {args.source}: {n} points")
        return 0

    if args.cmd == "backfill":
        result = mgr.backfill(args.source, days=args.days, symbols=symbols, timeframes=_timeframes(args.timeframe))
        if result["kind"] == "funding":
            _report_funding(result["results"])
        elif result["kind"] == "bars":
            _report_bars(result["results"])
        else:
            print(f"backfilled {args.source} (incremental): {result['written']} points")
        return 0

    if args.cmd == "verify":
        report = mgr.verify(symbols, timeframes=_timeframes(args.timeframe), include_bars=not args.no_bars, include_panels=args.panels)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.to_text())
        return 0

    if args.cmd == "update":
        counts = mgr.update(symbols)
        print("DATA UPDATE — one incremental pass complete")
        for source, n in counts.items():
            print(f"  {source:<18}{n:>6} points")
        print(f"  {'TOTAL':<18}{sum(counts.values()):>6} points")
        return 0

    if args.cmd == "panels":
        written = mgr.build_panels(symbols, timeframes=_timeframes(args.timeframe))
        print("ML PANELS — standardized point-in-time feature matrices built")
        for (sym, tf), n in written.items():
            print(f"  {sym:<12}{tf:<5}{n:>8} new rows")
        print(f"  {'TOTAL':<17}{sum(written.values()):>8} new rows")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
