# intent: STAGE 1 of the UNIVERSAL PRICE LAYER — turn the venue-tagged `universe_pairs` rows into the (pair ×
# venue) CELLS the crypto screen runs over, computing each pair's price ONCE and reusing it across venues that
# the alignment check says are the SAME price (UNIFY), while a divergent/illiquid venue keeps its OWN bars
# (FALLBACK). This is what de-collapses the venue axis: today backtest_symbols is 100% Binance because the
# screen only ever fetched Binance bars; here every liquid crypto venue in universe_pairs becomes its own cell,
# but a UNIFY cell points at the SHARED reference series so the backtest runs ONCE per pair and the per-venue
# difference is ONLY the fee/depth overlay (added later in master/screen_universe.build_cost_context).
#
# The #1 risk is FALSE-UNIFY: silently reusing the reference for a venue whose prices diverge is a LEAKAGE bug
# upstream of the Gate. So this module BIASES TO FALLBACK — any missing/empty bars, any failed alignment, any
# threshold miss → the venue gets its OWN bars (never the reference). The leakage guard is structural: a FALLBACK
# cell's `bars` are the venue's own series and `reuses_reference` is False, so a backtest can never silently score
# a FALLBACK venue on the reference.
#
# invariants: BINANCE-ONLY / EMPTY-TABLE PATH IS BYTE-IDENTICAL TO BEFORE — when universe_pairs has no rows (or
# only the Binance venue is enabled) the builder returns plain symbol-keyed cells over PERP_UNIVERSE with the bare
# symbol as the key and venue 'binance', so the finder's existing crypto path is unchanged. Deterministic for a
# fixed store + provider responses; offline-safe (a venue whose bars won't load is skipped, never fabricated);
# ZERO LLM. Persisting the alignment verdict is opt-in (pass a store) and best-effort.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.data.market import (
    Bar,
    BinanceSpotOHLCVProvider,
    KrakenSpotOHLCVProvider,
    MarketDataProvider,
    UniversalOHLCVProvider,
)
from cosmu.data.reference import AlignmentDecision as _AlignmentDecision
from cosmu.data.reference import (
    CanonicalPair,
    cross_venue_alignment,
    decide,
    pair_for,
    persist_decision,
)
from cosmu.data.universe import PERP_UNIVERSE, load_universe

# The reference venue: the deepest keyless crypto book = the natural canonical price. A cell on THIS venue is the
# reference itself (always "UNIFY", trivially — it IS the reference), so its bars come straight from the universal
# provider and no alignment check is needed.
REFERENCE_VENUE = "binance"


@dataclass(frozen=True)
class PriceCell:
    """One (pair × venue) screen cell. `key` is the market-dict key the backtest runs over (the bare symbol for
    the byte-identical Binance path, else 'PAIR@venue'); `symbol` is the canonical pair stamped on backtest_symbols;
    `venue_id` is the venue the fee/depth overlay prices against. `bars` is the series this cell is scored on — the
    SHARED reference for a UNIFY cell, the venue's OWN series for a FALLBACK cell. `reuses_reference` is the
    leakage-guard flag: True ONLY when `bars` IS the reference series (a FALLBACK cell is ALWAYS False)."""

    key: str
    symbol: str
    venue_id: str
    bars: list[Bar]
    reuses_reference: bool
    decision: _AlignmentDecision | None = None  # None for the reference venue itself (no cross-venue check)


def cell_key(symbol: str, venue_id: str) -> str:
    """The market-dict key for a (symbol, venue) cell. The Binance reference venue keeps the BARE symbol (so the
    existing crypto path is byte-identical); every other venue is namespaced 'symbol@venue' so two venues of the
    same pair are distinct per-symbol runs."""
    return symbol if venue_id == REFERENCE_VENUE else f"{symbol}@{venue_id}"


# Keyless OHLCV providers per crypto venue, for FALLBACK bars (a venue whose prices diverge from the reference is
# screened on its OWN series). Only keyless venues are wired in Stage 1 (crypto, FREE). A venue absent here has no
# keyless data route → its non-reference cells can't FALLBACK to real bars, so they are SKIPPED (never fabricated).
def _fallback_provider(venue_id: str) -> MarketDataProvider | None:
    if venue_id == "kraken":
        return KrakenSpotOHLCVProvider()
    if venue_id == "binance":
        return BinanceSpotOHLCVProvider()
    return None


def _venue_fetch_symbol(venue_id: str, row_symbol: str, pair: CanonicalPair) -> str:
    """The symbol to fetch a venue's OWN bars by. Kraken's REST wants its pair spelling (XBTUSD), which the
    universe row already carries in `row_symbol`; default to the row's own venue spelling."""
    return row_symbol


def build_crypto_cells(
    store: object | None,
    *,
    timeframe: str,
    limit: int,
    enabled_venues: set[str] | None = None,
    reference: UniversalOHLCVProvider | None = None,
    persist: bool = True,
    fallback_symbols: tuple[str, ...] = PERP_UNIVERSE,
) -> list[PriceCell]:
    """Build the crypto screen cells from the venue-tagged `universe_pairs` rows (via load_universe), computing
    each pair's reference price ONCE and deciding UNIFY/FALLBACK per non-reference venue.

    For each (pair, venue):
      - REFERENCE venue (binance): the cell IS the reference — bars from the universal provider, reuses_reference
        True, no alignment check.
      - other venue: fetch its OWN bars (keyless), run cross_venue_alignment vs the reference, `decide`:
          UNIFY    → bars = the SHARED reference series, reuses_reference True (one backtest, fee overlay only).
          FALLBACK → bars = the venue's OWN series, reuses_reference False (the safe default).
        The verdict + its stats are persisted to price_alignment (opt-in, best-effort) so it's inspectable.

    BYTE-IDENTICAL FALLBACK PATH: when `store` is None OR universe_pairs has no crypto rows, returns one cell per
    `fallback_symbols` (the caller's legacy Binance screen set — the finder's PERP_UNIVERSE, the FarmLoop's
    CRYPTO_SCREEN_UNIVERSE) on the Binance reference (bare-symbol key, venue 'binance') — exactly the old screen
    set. A venue not in `enabled_venues` (the store's effective universe gate) is skipped; a row whose bars won't
    load is skipped (offline-safe, never fabricated)."""
    ref = reference or UniversalOHLCVProvider()

    rows = load_universe(store, asset_class="crypto") if store is not None else []
    # No universe table (fresh store / offline) → the caller's legacy Binance-only set, byte-identical to before.
    if not rows:
        return [
            PriceCell(key=sym, symbol=sym, venue_id=REFERENCE_VENUE,
                      bars=ref.fetch_reference(pair_for(sym, REFERENCE_VENUE).id, timeframe, limit=limit),
                      reuses_reference=True)
            for sym in fallback_symbols
        ]

    # Group rows by canonical pair so the reference is fetched once per pair and shared across its venues.
    by_pair: dict[str, list[tuple[str, str, CanonicalPair]]] = {}  # pair_id -> [(venue, row_symbol, pair)]
    for r in rows:
        if enabled_venues is not None and r.venue not in enabled_venues:
            continue
        pair = pair_for(r.symbol, r.venue, base=r.base, quote=r.quote)
        by_pair.setdefault(pair.id, []).append((r.venue, r.symbol, pair))

    cells: list[PriceCell] = []
    for pair_id, venue_rows in by_pair.items():
        pair = venue_rows[0][2]
        reference_bars = ref.fetch_reference(pair_id, timeframe, limit=limit)
        # Deterministic, reference-first ordering so a re-run produces cells in a stable sequence.
        for venue, row_symbol, _p in sorted(venue_rows, key=lambda t: (t[0] != REFERENCE_VENUE, t[0])):
            if venue == REFERENCE_VENUE:
                if reference_bars:
                    cells.append(PriceCell(key=cell_key(pair.id, venue), symbol=pair.id, venue_id=venue,
                                           bars=reference_bars, reuses_reference=True))
                continue
            provider = _fallback_provider(venue)
            if provider is None:
                continue  # no keyless data route for this venue → skip (never fabricate bars)
            try:
                venue_bars = provider.fetch_bars(_venue_fetch_symbol(venue, row_symbol, pair), timeframe, limit=limit)
            except Exception:  # noqa: BLE001 — offline/refused: this venue's cell can't be priced → skip honestly
                venue_bars = []
            if not venue_bars or not reference_bars:
                continue  # BIAS TO FALLBACK is moot with no bars at all → the cell can't be scored; skip
            stats = cross_venue_alignment(reference_bars, venue_bars)
            verdict = decide(stats)
            dec = _AlignmentDecision(pair=pair.id, venue=venue, verdict=verdict, stats=stats)
            if persist and store is not None:
                persist_decision(store, dec)
            # UNIFY → reuse the SHARED reference series (price once, fee overlay only). FALLBACK → the venue's OWN
            # bars (the leakage-safe default). reuses_reference is the structural guard: a FALLBACK cell can NEVER
            # carry the reference series.
            unify = verdict == "UNIFY"
            cells.append(PriceCell(
                key=cell_key(pair.id, venue), symbol=pair.id, venue_id=venue,
                bars=reference_bars if unify else venue_bars, reuses_reference=unify, decision=dec,
            ))
    return cells
