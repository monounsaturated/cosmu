#!/usr/bin/env python3
# intent: BACKFILL backtest_symbols.oos_window_days for legacy cells (NULL window) — so the screener's per-cell
# "Return /yr" (CAGR) annualizes EACH cell over ITS OWN validation window, not the parent backtest's shared
# (longest-cell) window. For every cell with a NULL window we recompute its OWN validation window from its OWN
# symbol's bars (first ~80% = validation, matching the screen's `_oos_window_from_market` convention) and set the
# per-cell window in calendar days. inputs: the configured store (DATABASE_URL) + the keyless market providers;
# outputs: UPDATEd backtest_symbols.oos_window_days. invariants: DISPLAY-only (the locked gate math is untouched),
# idempotent (only NULL windows are filled), offline-safe (a cell whose bars won't load stays NULL — honest),
# dry-run by default (pass --apply to write). Mirrors the schema-adaptive forward path in finder/loop _persist.
#
# PROD: connect via DATABASE_URL from <repo>/.env.local (strip a trailing ` #comment` + `?pgbouncer=true`,
# use port 5432). Run AFTER the 2026-06-19_backtest_symbols_oos_window migration is applied (the column must exist).

from __future__ import annotations

import argparse
import sys

from cosmu.config.settings import Settings
from cosmu.data.market import (
    BinanceSpotOHLCVProvider,
    EquityOHLCVProvider,
    HyperliquidOHLCVProvider,
    KrakenSpotOHLCVProvider,
    MarketDataProvider,
)
from cosmu.knowledge.store import Store, backtest_symbols_has_oos_window

# Validation fraction — the leading slice of bars the screen treats as the OOS/validation window (matches
# lab/finder.py::_oos_window_from_market, so the backfill re-windows on the SAME convention the forward path uses).
_VALIDATION_FRACTION = 0.8
# A coarse bar pull per cell — enough to span the longest cell's history (the screen fetches ≤1500).
_BAR_LIMIT = 1500


def _provider_for(venue_id: str | None) -> MarketDataProvider | None:
    """The keyless provider that serves a venue's OWN bars. Equity/HL read their local cache; crypto venues fetch
    keyless (cache fallback). An unknown venue (or a venue with no keyless path) → None (the cell stays NULL)."""
    v = (venue_id or "binance").lower()
    if v in ("binance", ""):
        return BinanceSpotOHLCVProvider()
    if v == "kraken":
        return KrakenSpotOHLCVProvider()
    if v == "hyperliquid":
        return HyperliquidOHLCVProvider()
    if v in ("ibkr", "alpaca", "equity"):
        return EquityOHLCVProvider()
    # Default to the keyless crypto reference — most non-equity cells unify onto it.
    return BinanceSpotOHLCVProvider()


def _bar_size_for_version(store: Store, version_id: str, cache: dict[str, str]) -> str:
    """The version's bar_size from its persisted spec (default '1d'). Cached per version_id."""
    if version_id in cache:
        return cache[version_id]
    row = store.row("SELECT spec FROM strategy_versions WHERE id = ?", (version_id,))
    bar_size = "1d"
    if row and row["spec"]:
        spec = row["spec"]
        if isinstance(spec, str):
            import json

            try:
                spec = json.loads(spec)
            except json.JSONDecodeError:
                spec = {}
        try:
            bar_size = ((spec or {}).get("horizon") or {}).get("bar_size") or "1d"
        except AttributeError:
            bar_size = "1d"
    cache[version_id] = bar_size
    return bar_size


def _window_days_for_cell(provider: MarketDataProvider, fetch_symbol: str, bar_size: str) -> float | None:
    """Calendar-day span of the cell's OWN validation window: fetch its bars, take the first ~80% (the screen's
    validation slice), and return last_val_ts − first_val_ts in days. None when < 2 validation bars load."""
    try:
        bars = provider.fetch_bars(fetch_symbol, bar_size, limit=_BAR_LIMIT)
    except Exception:  # noqa: BLE001 — offline / unknown symbol: leave the cell NULL (honest), never fabricate
        return None
    if len(bars) < 2:
        return None
    val = bars[: int(len(bars) * _VALIDATION_FRACTION)] or bars
    if len(val) < 2:
        return None
    span = (val[-1].ts - val[0].ts).total_seconds() / 86400.0
    return span if span > 0 else None


def backfill(store: Store, *, apply: bool, limit: int | None = None) -> dict[str, int]:
    """Fill oos_window_days for every cell whose window is NULL, from that cell's OWN bars. Returns a counts dict."""
    if not backtest_symbols_has_oos_window(store):
        print("ERROR: backtest_symbols.oos_window_days does not exist — apply the migration first.", file=sys.stderr)
        raise SystemExit(2)
    rows = store.rows(
        "SELECT id, strategy_version_id, symbol, venue_id FROM backtest_symbols WHERE oos_window_days IS NULL"
    )
    if limit is not None:
        rows = rows[:limit]
    counts = {"candidates": len(rows), "rewindowed": 0, "skipped_no_bars": 0}
    bar_size_cache: dict[str, str] = {}
    # One provider instance per venue (the equity/HL caches + the universal memo are reused across cells).
    providers: dict[str, MarketDataProvider | None] = {}
    # The window depends ONLY on (venue, symbol, bar_size) — not on the version — so compute it ONCE per distinct
    # triple and reuse it across every cell that shares it (3285 cells collapse to ≈40 fetches, not 3285).
    window_cache: dict[tuple[str | None, str, str], float | None] = {}
    updates: list[tuple[float, str]] = []  # (window_days, cell_id) to apply in ONE transaction
    for r in rows:
        venue = r["venue_id"]
        if venue not in providers:
            providers[venue] = _provider_for(venue)
        provider = providers[venue]
        if provider is None:
            counts["skipped_no_bars"] += 1
            continue
        bar_size = _bar_size_for_version(store, r["strategy_version_id"], bar_size_cache)
        wkey = (venue, r["symbol"], bar_size)
        if wkey not in window_cache:
            window_cache[wkey] = _window_days_for_cell(provider, r["symbol"], bar_size)
        window = window_cache[wkey]
        if window is None:
            counts["skipped_no_bars"] += 1
            continue
        counts["rewindowed"] += 1
        updates.append((round(window, 4), r["id"]))
    if apply and updates:
        with store.batch() as b:
            for window, cell_id in updates:
                b.execute("UPDATE backtest_symbols SET oos_window_days = ? WHERE id = ?", (window, cell_id))
    return counts


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill backtest_symbols.oos_window_days per-cell (dry-run by default).")
    parser.add_argument("--apply", action="store_true", help="WRITE the recomputed per-cell windows (default: dry-run)")
    parser.add_argument("--limit", type=int, default=None, help="cap the number of cells processed (for a probe run)")
    args = parser.parse_args(argv)

    store = Store(Settings())
    counts = backfill(store, apply=args.apply, limit=args.limit)
    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"[{mode}] cells with NULL window: {counts['candidates']}")
    print(f"  re-windowed from own bars: {counts['rewindowed']}")
    print(f"  left NULL (no bars / offline): {counts['skipped_no_bars']}")
    if not args.apply and counts["rewindowed"]:
        print("Re-run with --apply to persist the recomputed per-cell windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
