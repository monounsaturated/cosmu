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
# PER-VENUE NATIVE BARS (flag COSMU_PER_VENUE_BARS, DEFAULT OFF): the operator directive is "each bar per venue —
# don't take Kraken as source of truth for Hyperliquid". OFF → today's single-reference behaviour, BYTE-IDENTICAL
# (UNIFY collapses a corr~1 venue onto the shared reference series). ON → each non-reference cell is SCORED on its
# venue's OWN keyless-native bars (kraken→Kraken, bybit→Bybit, via market.keyless_venue_provider), with the
# reference used only as a FALLBACK when a venue's native series is missing/too-sparse. Because this changes a
# Gate INPUT (the bars a backtest scores), it is flag-gated so the default can never silently move existing results.
#
# invariants: BINANCE-ONLY / EMPTY-TABLE PATH IS BYTE-IDENTICAL TO BEFORE — when universe_pairs has no rows (or
# only the Binance venue is enabled) the builder returns plain symbol-keyed cells over PERP_UNIVERSE with the bare
# symbol as the key and venue 'binance', so the finder's existing crypto path is unchanged. Deterministic for a
# fixed store + provider responses; offline-safe (a venue whose bars won't load is skipped, never fabricated);
# ZERO LLM. Persisting the alignment verdict is opt-in (pass a store) and best-effort.

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from cosmu.data.market import (
    Bar,
    KrakenSpotOHLCVProvider,
    MarketDataProvider,
    UniversalOHLCVProvider,
    default_crypto_reference,
    keyless_venue_provider,
)
from cosmu.data.reference import (
    UNIFY_MIN_OVERLAP,
    CanonicalPair,
    cross_venue_alignment,
    decide,
    pair_for,
    persist_decision,
)
from cosmu.data.reference import AlignmentDecision as _AlignmentDecision
from cosmu.data.universe import PERP_UNIVERSE, UniverseRow, load_universe
from cosmu.data.universe_calendar import Listing, UniverseCalendar

# The reference venue: the deepest keyless crypto book = the natural canonical price. A cell on THIS venue is the
# reference itself (always "UNIFY", trivially — it IS the reference), so its bars come straight from the universal
# provider and no alignment check is needed.
REFERENCE_VENUE = "binance"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _calendar_from_rows(rows: list[UniverseRow]) -> UniverseCalendar | None:
    """A survivorship-honest UniverseCalendar from the selected universe rows, ONE window per venue symbol.

    The universe_pairs table lists a symbol under several rows (binance spot + binanceperp + venue spellings); each
    may carry its own listed_at/delisted_at, and some are NULL. Collapse them per symbol so eligibility is honest:
      - listed_at  = the EARLIEST known listing across the symbol's rows (NULLs ignored). A bar before this is
        look-ahead onto a pair that did not exist yet → excluded.
      - delisted_at = the LATEST delisting, but ONLY when EVERY row of the symbol is delisted (active=False). If any
        row is still active the symbol is treated as live (no delisting cap) — a coin still trading SOMEWHERE has
        not delisted. This is the inverse of UniverseCalendar.from_universe_pairs's OR-over-listings semantics,
        where a NULL-listed duplicate would make the symbol eligible at every ts and silently negate a real date.

    Returns None when NO row carries any window (nothing to trim) so the whole-history path stays byte-identical."""
    by_symbol: dict[str, list[UniverseRow]] = {}
    for r in rows:
        by_symbol.setdefault(r.symbol, []).append(r)
    listings: list[Listing] = []
    any_window = False
    for symbol, srows in by_symbol.items():
        listed_dts = [d for d in (_parse_dt(r.listed_at) for r in srows) if d is not None]
        delisted_dts = [d for d in (_parse_dt(r.delisted_at) for r in srows) if d is not None]
        listed = min(listed_dts) if listed_dts else None
        all_delisted = bool(srows) and all(not r.active for r in srows)
        delisted = max(delisted_dts) if (all_delisted and delisted_dts) else None
        if listed is not None or delisted is not None:
            any_window = True
        listings.append(Listing(symbol=symbol, listed_at=listed, delisted_at=delisted))
    return UniverseCalendar(listings) if any_window else None


def eligible_bars(bars: list[Bar], calendar: UniverseCalendar | None, row_symbol: str | None) -> list[Bar]:
    """Trim a cell's bars to the window the symbol was POINT-IN-TIME tradable (listed, not-yet-delisted) per the
    UniverseCalendar — the SURVIVORSHIP/LOOK-AHEAD fix. A bar at ts is kept only if the symbol is_eligible AS OF
    its close: bars before listed_at are dropped (no look-ahead onto a pair that did not exist yet) and bars
    at/after delisted_at are dropped (the position could not have been held past the delisting). The calendar keys
    by the venue's OWN row symbol (BTCUSDT / XBTUSD), the same key the cell is built from.

    BYTE-IDENTICAL when there is nothing to trim: `calendar is None` (no universe table / no PIT data), `row_symbol
    is None` (no reference-venue row to gate the shared series by), or the symbol has no listing window (listed_at
    and delisted_at both None → eligible for every ts) returns the bars unchanged — the whole-history behaviour. So
    this only ever REMOVES survivorship/look-ahead bars; it never adds, reorders, or fabricates one."""
    if calendar is None or not bars or row_symbol is None:
        return bars
    # Resolve the symbol's window ONCE (not per bar): is_eligible rebuilds + sorts the full eligible set on every
    # call, which over a 1500-bar series × the ~4000-symbol superset calendar would be a real perf regression. The
    # window is the same membership rule (>= listed_at, < delisted_at) evaluated O(1) per bar.
    window = calendar.window_for(row_symbol)
    if window is None:
        return bars  # unknown symbol → no trim (never trim a cell to empty on a calendar gap)
    listed, delisted = window
    if listed is None and delisted is None:
        return bars  # no window → whole-history, byte-identical
    kept = [
        b for b in bars
        if (listed is None or b.ts >= listed) and (delisted is None or b.ts < delisted)
    ]
    # Identity-preserving when nothing was trimmed: return the SAME list object so the UNIFY de-dup (a kraken cell
    # whose bars ARE the reference object) and the whole-history path are untouched. Only a real window that
    # actually clips a bar gets a new (shorter) list.
    return bars if len(kept) == len(bars) else kept


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


def alt_ingest_symbol(symbol: str) -> str:
    """The alt-data store key for a cell's canonical pair. The ingest pipeline (ingest/run.py over `perp_universe()`)
    keys funding_rate / open_interest / on-chain by the BARE full-pair Binance perp symbol (BTCUSDT), while the
    universal price layer (build_crypto_cells) stamps the CANONICAL slash pair (BTC/USDT) on each cell. Strip the
    '/' so a canonical-keyed cell resolves to the bare key the alt series actually live under — otherwise
    fetch_series('BTC/USDT', 'funding_rate') misses and funding/OI/on-chain silently read None on the populated-
    universe screen path. Idempotent on an already-bare symbol (the empty-universe fallback path keys cells by the
    bare symbol → no-op), so both screen paths fetch alt by the identical key."""
    return symbol.replace("/", "")


# ------------------------------------------------------------------------------------------------------------------
# PER-VENUE NATIVE BARS — flag-gated (COSMU_PER_VENUE_BARS). DEFAULT OFF → today's single-reference behaviour, so a
# Gate-input change can never SILENTLY move existing backtest results. The operator directive: "each bar per venue —
# don't take Kraken as source of truth for Hyperliquid"; i.e. a cell tagged venue=kraken should be SCORED on Kraken's
# OWN keyless bars, a venue=bybit cell on Bybit's, never one reference book proxying for all. When ON, each
# non-reference cell prefers its venue's NATIVE bars (reuses_reference False); only when those native bars are
# MISSING / too-sparse does it fall back to the reference via the existing corr-check/UNIFY path (so a real native
# series is never silently collapsed onto the reference, but a thin/absent venue still degrades safely).
# ------------------------------------------------------------------------------------------------------------------
def per_venue_bars_enabled() -> bool:
    """True iff COSMU_PER_VENUE_BARS is set truthy. DEFAULT OFF → the byte-identical single-reference path."""
    return os.environ.get("COSMU_PER_VENUE_BARS", "").strip().lower() in ("1", "true", "yes", "on")


# Keyless OHLCV providers per crypto venue, for FALLBACK bars (a venue whose prices diverge from the reference is
# screened on its OWN series). Only keyless venues are wired in Stage 1 (crypto, FREE). A venue absent here has no
# keyless data route → its non-reference cells can't FALLBACK to real bars, so they are SKIPPED (never fabricated).
#
# OFF (default): the byte-identical set — kraken + binance only (today's behaviour, unchanged).
# ON  (COSMU_PER_VENUE_BARS): the full keyless-NATIVE resolver (market.keyless_venue_provider) so bybit (+ any future
# keyless venue) reads ITS OWN bars too — never one reference book as the source of truth for every venue.
def _fallback_provider(venue_id: str) -> MarketDataProvider | None:
    if per_venue_bars_enabled():
        return keyless_venue_provider(venue_id)
    if venue_id == "kraken":
        return KrakenSpotOHLCVProvider()
    if venue_id == "binance":
        return default_crypto_reference()
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
    include_delisted: bool = False,
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

    SURVIVORSHIP / LOOK-AHEAD (the #1 backtest bias): selection reads the DELISTED SUPERSET (active_only=False) so
    a coin that pumped then died is a CANDIDATE — not silently dropped because it is not in TODAY's active set — and
    every cell's bars are trimmed to the symbol's POINT-IN-TIME window via the UniverseCalendar (listed, not-yet-
    delisted as of each bar's close). A delisted symbol is thus INCLUDED over the window it traded, and a not-yet-
    listed symbol is EXCLUDED before its listing. A delisted symbol whose runtime bar source returns nothing (the
    live venue no longer serves it) yields empty bars and is skipped honestly — never fabricated.

    `include_delisted` (opt-in, default False) widens the curated screen set to the delisted superset's pairs so the
    losers actually screen. KNOWN DATA GAP: the runtime crypto bar source (RemoteBarsProvider → live Binance
    /klines) returns NOTHING for a delisted symbol — the FREE Binance Vision archive bars exist only via the
    operator CLI (binance_vision_backfill.py), not in the runtime path. So today an included delisted cell fetches
    empty bars and is skipped; the per-symbol calendar trim + the superset selection are the realized fix, and full
    delisted backtesting waits on wiring Vision bars into the runtime source (FOLLOW-UP).

    BYTE-IDENTICAL FALLBACK PATH: when `store` is None OR universe_pairs has no crypto rows, returns one cell per
    `fallback_symbols` (the caller's legacy Binance screen set — the finder's PERP_UNIVERSE, the FarmLoop's
    CRYPTO_SCREEN_UNIVERSE) on the Binance reference (bare-symbol key, venue 'binance') — exactly the old screen
    set, with NO calendar (nothing to trim). A venue not in `enabled_venues` (the store's effective universe gate)
    is skipped; a row whose bars won't load is skipped (offline-safe, never fabricated)."""
    ref = reference or UniversalOHLCVProvider()

    # active_only=False: read the DELISTED SUPERSET so delisted rows (the losers) are candidates — the calendar then
    # gates each per bar. The CURATED-set cap below still bounds the screen to the caller's pairs (no compute blow-up).
    rows = load_universe(store, asset_class="crypto", active_only=False) if store is not None else []
    # No universe table (fresh store / offline) → the caller's legacy Binance-only set, byte-identical to before.
    if not rows:
        return [
            PriceCell(key=sym, symbol=sym, venue_id=REFERENCE_VENUE,
                      bars=ref.fetch_reference(pair_for(sym, REFERENCE_VENUE).id, timeframe, limit=limit),
                      reuses_reference=True)
            for sym in fallback_symbols
        ]

    # The POINT-IN-TIME membership calendar from the SAME superset rows. Built from the rows we just selected (one
    # fetch), collapsing the SEVERAL rows that share a symbol (binance spot + binanceperp + a venue spelling) into
    # ONE honest window per symbol: listed_at = the EARLIEST known listing, delisted_at = the latest delisting but
    # ONLY when EVERY row of that symbol is delisted (any still-active row → no delisting cap). Critically this
    # avoids the from_universe_pairs OR-NULL trap, where a NULL-listed duplicate row would make a symbol "eligible
    # always" and silently negate a sibling row's real listing date. None when there are no windows at all → nothing
    # to trim → whole-history behaviour preserved.
    calendar = _calendar_from_rows(rows)

    # BOUND THE SCREEN TO THE CALLER'S CURATED PAIR SET. The universal price layer WIDENS THE VENUE AXIS, not the
    # pair axis: it screens the SAME curated pairs the legacy Binance path did (the finder's PERP_UNIVERSE, the
    # FarmLoop's CRYPTO_SCREEN_UNIVERSE), now across EVERY enabled venue. Without this cap, load_universe returns the
    # FULL ~4000-row crypto table and the screen would run thousands of pairs × every spec — a compute blow-up that
    # silently busts the budget (and was never the intent; the de-collapse is about venues, not the long tail of
    # illiquid pairs). The curated set is the caller's existing screen universe, mapped to canonical pair ids so a
    # venue's own spelling (kraken XBTUSD ≙ binance BTCUSDT) still matches.
    curated = {pair_for(sym, REFERENCE_VENUE).id for sym in fallback_symbols}
    # DELISTED INCLUSION (opt-in): with include_delisted, widen the curated screen set to the canonical pairs of the
    # DELISTED rows in the superset, so a coin that pumped-then-died is screened over the window it traded — the
    # survivorship "losers" the active-only screen silently dropped. DEFAULT OFF: today the runtime crypto bar
    # source (RemoteBarsProvider → live Binance /klines) returns NOTHING for a delisted symbol (Vision archive bars
    # are operator-CLI-only, not in the runtime path), so an included delisted cell fetches empty bars and is
    # skipped honestly — no compute change, no fabricated bars. Flipping this on becomes meaningful once the Vision
    # delisted bars are wired into the runtime source (follow-up); the SELECTION + per-bar calendar are ready for it.
    if include_delisted:
        curated |= {
            pair_for(r.symbol, r.venue, base=r.base, quote=r.quote).id for r in rows if not r.active
        }

    # Group rows by canonical pair so the reference is fetched once per pair and shared across its venues. A venue can
    # list the SAME canonical pair under several quote spellings (kraken XBTUSD / XBTUSDC / XBTUSDT all bucket to
    # BTC/USDT) — keep only the FIRST (= most liquid, since load_universe orders by liquidity desc) per (pair, venue)
    # so each (pair, venue) yields exactly ONE cell, not a redundant fetch + key-collision across quote variants.
    by_pair: dict[str, list[tuple[str, str, CanonicalPair]]] = {}  # pair_id -> [(venue, row_symbol, pair)]
    seen_pair_venue: set[tuple[str, str]] = set()
    for r in rows:
        if enabled_venues is not None and r.venue not in enabled_venues:
            continue
        pair = pair_for(r.symbol, r.venue, base=r.base, quote=r.quote)
        if pair.id not in curated:
            continue  # outside the curated screen set → skip (widen venues, not the pair long-tail)
        if (pair.id, r.venue) in seen_pair_venue:
            continue  # already took the most-liquid quote variant for this (pair, venue)
        seen_pair_venue.add((pair.id, r.venue))
        by_pair.setdefault(pair.id, []).append((r.venue, r.symbol, pair))

    # The Binance reference symbol per canonical pair (the row whose venue IS the reference) — the key the calendar
    # gates the SHARED reference series by. None when no Binance row exists for this pair (a kraken-only pair): then
    # the shared reference series is NOT trimmed (we have no reference-venue window to trim it by) and each venue
    # cell still trims its OWN series by its OWN row symbol — never over-trimming on a symbol the calendar lacks.
    ref_symbol_by_pair: dict[str, str | None] = {
        p_id: next((rs for v, rs, _p in vr if v == REFERENCE_VENUE), None)
        for p_id, vr in by_pair.items()
    }

    # PER-VENUE NATIVE BARS flag, read ONCE per build (not per cell) so a build is internally consistent.
    per_venue = per_venue_bars_enabled()

    cells: list[PriceCell] = []
    for pair_id, venue_rows in by_pair.items():
        pair = venue_rows[0][2]
        # Trim the SHARED reference series ONCE per pair to the reference symbol's PIT window — every UNIFY cell of
        # this pair reuses this same trimmed object (the de-dup + the leakage guard's `is` identity both survive).
        reference_bars = eligible_bars(
            ref.fetch_reference(pair_id, timeframe, limit=limit), calendar, ref_symbol_by_pair[pair_id]
        )
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
            # Gate this venue's OWN series by ITS OWN row symbol's PIT window before the alignment check, so a venue
            # that delisted earlier than the reference is screened only over the bars it actually traded.
            venue_bars = eligible_bars(venue_bars, calendar, row_symbol)

            # PER-VENUE NATIVE BARS (flag ON): a SELF-CONTAINED per-venue decision — "each bar per venue, don't take
            # one book as source of truth for all". The cell is scored on its venue's OWN native series whenever that
            # series is adequate (>= the trustable-overlap floor); a MISSING or too-SPARSE native series FALLS BACK to
            # the reference. This branch never touches the OFF path below, which stays byte-identical.
            if per_venue:
                native_ok = len(venue_bars) >= UNIFY_MIN_OVERLAP
                if native_ok and reference_bars:
                    # Score on the venue's OWN bars (reuses_reference False, the leakage-safe per-venue path). The
                    # alignment verdict is still computed + persisted for inspectability (price_alignment).
                    stats = cross_venue_alignment(reference_bars, venue_bars)
                    dec = _AlignmentDecision(pair=pair.id, venue=venue, verdict=decide(stats), stats=stats)
                    if persist and store is not None:
                        persist_decision(store, dec)
                    cells.append(PriceCell(
                        key=cell_key(pair.id, venue), symbol=pair.id, venue_id=venue,
                        bars=venue_bars, reuses_reference=False, decision=dec,
                    ))
                elif reference_bars:
                    # Native bars missing / too-sparse → fall back to the reference series so the cell can still
                    # screen (explicit reference reuse; reuses_reference True). No native series with no reference
                    # series → nothing to score → skip honestly (handled by falling through without appending).
                    cells.append(PriceCell(
                        key=cell_key(pair.id, venue), symbol=pair.id, venue_id=venue,
                        bars=reference_bars, reuses_reference=True,
                    ))
                continue

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
