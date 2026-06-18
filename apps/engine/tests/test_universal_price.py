# The UNIVERSAL PRICE LAYER (Stage 0 + Stage 1): compute a pair's price ONCE and overlay per-venue fees, instead
# of fetching a separate (often identical) series per venue — de-collapsing the venue axis (backtest_symbols was
# 100% Binance). The #1 risk these tests guard is FALSE-UNIFY: silently reusing the reference for a venue whose
# prices diverge is a LEAKAGE bug upstream of the Gate. So the suite proves: (1) two venues of the same pair with
# corr~1 + a tiny spread UNIFY → ONE reference series scored under TWO fee overlays, and the cheaper-fee venue's
# net return is strictly higher; (2) a decoupled (low-corr) OR a big-spread (illiquid) venue FALLS BACK to its OWN
# bars; (3) the alignment verdict + its two stats are PERSISTED + inspectable; (4) quote normalization (USDT vs
# USD vs USDC) is explicit; (5) the LEAKAGE-SANITY guard: a FALLBACK cell NEVER carries the reference series.
# Hermetic — every provider is an injected in-memory stub; no network.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.data.price_cells import REFERENCE_VENUE, build_crypto_cells
from cosmu.data.reference import (
    UNIFY_MAX_SPREAD_BPS,
    UNIFY_MIN_CORR,
    UNIFY_MIN_OVERLAP,
    canonical_quote,
    cross_venue_alignment,
    decide,
    decision,
    load_decision,
    pair_for,
    persist_decision,
)
from cosmu.knowledge.store import Store

# --------------------------------------------------------------------------- helpers


def _bars(closes: list[float], *, start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(ts=t0 + timedelta(days=i), open=Decimal(str(c)), high=Decimal(str(c)),
            low=Decimal(str(c)), close=Decimal(str(c)), volume=Decimal("1000"))
        for i, c in enumerate(closes)
    ]


def _walk(n: int, *, seed: int, start: float = 100.0, vol: float = 0.02) -> list[float]:
    """A deterministic geometric random walk (no numpy) — a realistic-ish price series for the alignment math."""
    import random

    rng = random.Random(seed)
    out = [start]
    for _ in range(n):
        out.append(out[-1] * (1 + rng.uniform(-vol, vol)))
    return out


class _StubProvider:
    """A MarketDataProvider whose bars are pre-seeded per symbol. Stands in for any venue's keyless OHLCV."""

    def __init__(self, by_symbol: dict[str, list[Bar]]) -> None:
        self._by = by_symbol

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:  # noqa: ARG002
        return self._by.get(symbol, [])[-limit:]


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/up.sqlite3", openrouter_api_key=None))


def _seed_universe(store: Store, rows: list[tuple[str, str, str, str]]) -> None:
    """Insert (venue, symbol, base, quote) crypto-spot rows into universe_pairs (the venue-tagged discovery set)."""
    with store.batch() as b:
        for venue, symbol, base, quote in rows:
            b.insert("universe_pairs", {
                "id": f"{venue}:{symbol}", "venue": venue, "symbol": symbol, "base": base, "quote": quote,
                "asset_class": "crypto", "instrument_type": "spot", "liquidity_usd_24h": 1.0e9,
                "tier": 0, "rank": 0, "active": 1, "source": "live", "fetched_at": "2024-01-01T00:00:00+00:00",
            })


# --------------------------------------------------------------------------- pair / quote normalization


def test_pair_for_normalizes_base_and_quote_across_venues():
    """kraken XBTUSD + binance BTCUSDT resolve to the SAME canonical pair (XBT->BTC base alias, USD->USDT quote
    bucket) — the prerequisite for the alignment check to even compare them."""
    kraken = pair_for("XBTUSD", "kraken", base="XBT", quote="ZUSD")
    binance = pair_for("BTCUSDT", "binance", base="BTC", quote="USDT")
    assert kraken.id == binance.id == "BTC/USDT"


def test_alt_ingest_symbol_strips_slash_and_is_idempotent():
    """The canonical→bare alt key: the canonical slash pair (BTC/USDT, stamped on populated-universe cells) maps to
    the BARE ingest key (BTCUSDT) the alt store actually uses; an already-bare key (the empty-universe fallback
    path) is a no-op, so both screen paths fetch alt by the identical key."""
    from cosmu.data.price_cells import alt_ingest_symbol

    assert alt_ingest_symbol("BTC/USDT") == "BTCUSDT"
    assert alt_ingest_symbol("BTCUSDT") == "BTCUSDT"  # idempotent on the bare fallback-path key
    assert alt_ingest_symbol("1000PEPE/USDT") == "1000PEPEUSDT"


def test_quote_normalization_is_explicit():
    """USDT/USD/USDC all collapse to the canonical USDT bucket (deliberate + visible); an unbucketed quote (EUR)
    keeps its own spelling (no silent collapse)."""
    assert canonical_quote("USDT") == canonical_quote("USD") == canonical_quote("USDC") == "USDT"
    assert canonical_quote("ZUSD") == "USDT"  # Kraken's USD spelling
    assert canonical_quote("EUR") == "EUR"


# --------------------------------------------------------------------------- alignment + decision thresholds


def test_alignment_corr_and_spread_on_common_bars():
    """cross_venue_alignment computes return-corr ~1 + a small median spread for a venue series that is the
    reference scaled by a constant premium (identical returns, fixed level offset)."""
    ref = _bars(_walk(120, seed=1))  # _walk(n) returns n+1 closes
    ven = _bars([float(b.close) * 1.001 for b in ref])  # 10bps premium, identical returns
    stats = cross_venue_alignment(ref, ven)
    assert stats.n_overlap == len(ref)
    assert stats.corr == pytest.approx(1.0, abs=1e-6)
    assert stats.median_spread_bps == pytest.approx(10.0, abs=0.5)


def test_decide_unify_requires_all_three_thresholds():
    """UNIFY iff corr>=0.99 AND spread<=25bps AND overlap>=60. Each threshold miss → FALLBACK (bias to FALLBACK)."""
    from cosmu.data.reference import AlignmentStats

    assert decide(AlignmentStats(corr=0.999, median_spread_bps=10.0, n_overlap=100)) == "UNIFY"
    assert decide(AlignmentStats(corr=0.90, median_spread_bps=10.0, n_overlap=100)) == "FALLBACK"   # low corr
    assert decide(AlignmentStats(corr=0.999, median_spread_bps=80.0, n_overlap=100)) == "FALLBACK"  # big spread
    assert decide(AlignmentStats(corr=0.999, median_spread_bps=10.0, n_overlap=30)) == "FALLBACK"   # thin overlap
    # thresholds are the documented constants (guard against accidental loosening)
    assert (UNIFY_MIN_CORR, UNIFY_MAX_SPREAD_BPS, UNIFY_MIN_OVERLAP) == (0.99, 25.0, 60)


def test_decision_decoupled_series_falls_back():
    """A venue whose returns are an INDEPENDENT walk (low corr) FALLS BACK — never unified onto the reference."""
    ref = _bars(_walk(120, seed=1))
    decoupled = _bars(_walk(120, seed=999))
    d = decision(pair_for("BTCUSDT", "binance"), "weird", ref, decoupled)
    assert d.verdict == "FALLBACK"
    assert not d.unify


def test_decision_big_spread_illiquid_falls_back():
    """A venue at a large persistent premium (illiquid/depegged) FALLS BACK even with corr~1 — the level offset
    would mis-mark every fill."""
    ref = _bars(_walk(120, seed=2))
    premium = _bars([float(b.close) * 1.05 for b in ref])  # 500bps premium
    d = decision(pair_for("BTCUSDT", "binance"), "prem", ref, premium)
    assert d.verdict == "FALLBACK"
    assert d.stats.corr == pytest.approx(1.0, abs=1e-6)  # corr alone would have passed — the spread is the killer


# --------------------------------------------------------------------------- persistence (inspectable)


def test_alignment_decision_is_persisted_and_inspectable(tmp_path):
    """The verdict + BOTH stats + overlap are written to price_alignment, keyed per (pair, venue), and read back —
    so the decision is inspectable and NOT recomputed per run."""
    store = _store(tmp_path)
    store.migrate()
    ref = _bars(_walk(120, seed=3))
    ven = _bars([float(b.close) * 1.0005 for b in ref])
    d = decision(pair_for("BTCUSDT", "binance"), "kraken", ref, ven)
    persist_decision(store, d)

    row = store.row("SELECT * FROM price_alignment WHERE id = ?", ("BTC/USDT:kraken",))
    assert row is not None
    assert row["pair"] == "BTC/USDT" and row["venue"] == "kraken" and row["verdict"] == d.verdict
    assert float(row["corr"]) == pytest.approx(d.stats.corr, abs=1e-6)
    assert float(row["median_spread_bps"]) == pytest.approx(d.stats.median_spread_bps, abs=1e-3)
    assert int(row["n_overlap"]) == d.stats.n_overlap

    loaded = load_decision(store, pair_for("BTCUSDT", "binance"), "kraken")
    assert loaded is not None and loaded.verdict == d.verdict and loaded.stats.n_overlap == d.stats.n_overlap


def test_persist_decision_is_idempotent_upsert(tmp_path):
    """Re-deciding the same (pair, venue) REFRESHES the row (one row, latest stats) — no duplicate, no crash."""
    store = _store(tmp_path)
    store.migrate()
    ref = _bars(_walk(120, seed=4))
    ven = _bars([float(b.close) * 1.0005 for b in ref])
    pair = pair_for("BTCUSDT", "binance")
    persist_decision(store, decision(pair, "kraken", ref, ven))
    persist_decision(store, decision(pair, "kraken", ref, ven))  # re-decide
    n = store.row("SELECT COUNT(*) AS n FROM price_alignment WHERE id = ?", ("BTC/USDT:kraken",))["n"]
    assert n == 1


# --------------------------------------------------------------------------- Stage 1: cells (UNIFY / FALLBACK)


def test_unify_reuses_one_reference_series_for_both_venues(tmp_path):
    """A same-pair pair across 2 venues with corr~1 + tiny spread → BOTH cells UNIFY → the kraken cell's bars ARE
    the SAME reference object (one backtest reused), not the venue's own fetched series."""
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [
        ("binance", "BTCUSDT", "BTC", "USDT"),
        ("kraken", "XBTUSD", "XBT", "ZUSD"),
    ])
    ref_closes = _walk(150, seed=10)
    reference = _StubProvider({"BTCUSDT": _bars(ref_closes)})
    # Kraken's own bars: the reference with a 5bps premium (corr 1, tiny spread → UNIFY).
    kraken_bars = _bars([c * 1.0005 for c in ref_closes])
    # Patch the kraken FALLBACK provider so the cell builder fetches these when it checks alignment.
    import cosmu.data.price_cells as pc
    orig = pc._fallback_provider
    pc._fallback_provider = lambda v: _StubProvider({"XBTUSD": kraken_bars}) if v == "kraken" else orig(v)
    try:
        from cosmu.data.market import UniversalOHLCVProvider
        cells = build_crypto_cells(store, timeframe="1d", limit=200, enabled_venues={"binance", "kraken"},
                                   reference=UniversalOHLCVProvider(reference))
    finally:
        pc._fallback_provider = orig

    by_venue = {c.venue_id: c for c in cells}
    assert set(by_venue) == {"binance", "kraken"}
    assert by_venue["binance"].symbol == by_venue["kraken"].symbol == "BTC/USDT"
    assert by_venue["kraken"].reuses_reference is True
    # THE de-dup: the UNIFY kraken cell's bars ARE the reference cell's bars (one fetch reused), NOT kraken's own.
    assert by_venue["kraken"].bars is by_venue["binance"].bars
    assert by_venue["kraken"].decision.verdict == "UNIFY"
    # Distinct cell keys (so two per-symbol runs), same canonical symbol.
    assert by_venue["binance"].key == "BTC/USDT"
    assert by_venue["kraken"].key == "BTC/USDT@kraken"


def test_fallback_decoupled_venue_uses_its_own_bars_never_the_reference(tmp_path):
    """LEAKAGE-SANITY GUARD: a decoupled (low-corr) venue FALLS BACK → its cell's bars are the venue's OWN series,
    NOT the reference, and reuses_reference is False. A FALLBACK can NEVER silently reuse the reference."""
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [
        ("binance", "BTCUSDT", "BTC", "USDT"),
        ("kraken", "XBTUSD", "XBT", "ZUSD"),
    ])
    ref_closes = _walk(150, seed=11)
    reference = _StubProvider({"BTCUSDT": _bars(ref_closes)})
    decoupled_bars = _bars(_walk(150, seed=777))  # an INDEPENDENT walk → low corr → FALLBACK
    import cosmu.data.price_cells as pc
    orig = pc._fallback_provider
    pc._fallback_provider = lambda v: _StubProvider({"XBTUSD": decoupled_bars}) if v == "kraken" else orig(v)
    try:
        from cosmu.data.market import UniversalOHLCVProvider
        cells = build_crypto_cells(store, timeframe="1d", limit=200, enabled_venues={"binance", "kraken"},
                                   reference=UniversalOHLCVProvider(reference))
    finally:
        pc._fallback_provider = orig

    by_venue = {c.venue_id: c for c in cells}
    kraken = by_venue["kraken"]
    assert kraken.reuses_reference is False
    assert kraken.decision.verdict == "FALLBACK"
    # THE guard: the FALLBACK cell's bars are kraken's OWN series, and are NOT the reference object.
    assert kraken.bars is not by_venue["binance"].bars
    assert [float(b.close) for b in kraken.bars] == [float(b.close) for b in decoupled_bars]


def test_empty_universe_table_is_byte_identical_binance_only(tmp_path):
    """No universe_pairs rows → the legacy Binance-only set on bare-symbol keys (venue 'binance'), so the existing
    crypto screen path is unchanged."""
    store = _store(tmp_path)
    store.migrate()
    from cosmu.data.market import UniversalOHLCVProvider
    closes = _walk(150, seed=12)
    reference = UniversalOHLCVProvider(_StubProvider({"BTCUSDT": _bars(closes), "ETHUSDT": _bars(closes)}))
    cells = build_crypto_cells(store, timeframe="1d", limit=200, enabled_venues={"binance"},
                               reference=reference, fallback_symbols=("BTCUSDT", "ETHUSDT"))
    assert {c.key for c in cells} == {"BTCUSDT", "ETHUSDT"}
    assert all(c.venue_id == REFERENCE_VENUE and c.reuses_reference and c.key == c.symbol for c in cells)


def test_curated_cap_widens_venues_not_the_pair_long_tail(tmp_path):
    """COMPUTE-EXPLOSION GUARD: load_universe returns the FULL ~4000-row crypto table, but the universal layer must
    widen the VENUE axis, NOT the pair axis — it screens only the caller's CURATED set (fallback_symbols) across
    venues, never the illiquid long tail. Here universe_pairs carries a curated pair (BTC) AND an off-list pair
    (DOGE), both on 2 venues; only BTC may screen, and it DOES fan across both venues."""
    store = _store(tmp_path)
    store.migrate()
    _seed_universe(store, [
        ("binance", "BTCUSDT", "BTC", "USDT"),
        ("kraken", "XBTUSD", "XBT", "ZUSD"),
        ("binance", "DOGEUSDT", "DOGE", "USDT"),  # in universe_pairs but OFF the curated screen list
        ("kraken", "DOGEUSD", "DOGE", "ZUSD"),
    ])
    closes = _walk(150, seed=20)
    reference = _StubProvider({"BTCUSDT": _bars(closes), "DOGEUSDT": _bars(closes)})
    venue_bars = {"XBTUSD": _bars([c * 1.0005 for c in closes]), "DOGEUSD": _bars([c * 1.0005 for c in closes])}
    import cosmu.data.price_cells as pc
    orig = pc._fallback_provider
    pc._fallback_provider = lambda v: _StubProvider(venue_bars) if v == "kraken" else orig(v)
    try:
        from cosmu.data.market import UniversalOHLCVProvider
        # Curated set = ONLY BTC. DOGE is in universe_pairs on both venues but off the caller's screen list.
        cells = build_crypto_cells(store, timeframe="1d", limit=200, enabled_venues={"binance", "kraken"},
                                   reference=UniversalOHLCVProvider(reference), fallback_symbols=("BTCUSDT",))
    finally:
        pc._fallback_provider = orig

    assert {c.symbol for c in cells} == {"BTC/USDT"}          # the off-list DOGE pair never screens
    assert {c.venue_id for c in cells} == {"binance", "kraken"}  # the curated pair DOES fan across venues


# --------------------------------------------------------------------------- the fee overlay (cheaper venue wins)


def test_unify_two_fee_overlays_cheaper_venue_has_higher_net_return(tmp_path):
    """The whole point of UNIFY: ONE reference price scored under TWO fee overlays. Run the SAME bars through the
    backtest at Binance's 10bps vs Kraken's 40bps taker — the cheaper-fee (Binance) net return is strictly higher.
    This is the per-venue fee axis the cost context overlays on a unified price."""
    from cosmu.data.backtest import run_strategy_backtest_detailed
    from cosmu.evolution.seeder import seed_orb_fvg_spec
    from cosmu.lab.finder import build_grid
    from cosmu.master.screen_universe import build_cost_context
    from cosmu.research.fixtures import edge_bearing_screen_market
    from cosmu.spine.venue import default_catalog

    spec = seed_orb_fvg_spec()
    params = build_grid(spec, max_variants=1)[0].params
    bars = edge_bearing_screen_market(n=300)["BTCUSDT"][-300:]
    catalog = default_catalog()

    # Two cells of the SAME pair pointing at the SAME bars, one per venue.
    market = {"BTC/USDT": bars, "BTC/USDT@kraken": bars}
    crypto_cell_venues = {"BTC/USDT": "binance", "BTC/USDT@kraken": "kraken"}
    fee_schedule, depth_schedule, _ac, venue_id = build_cost_context(
        spec, market, catalog, crypto_cell_venues=crypto_cell_venues
    )
    assert fee_schedule is not None, "a multi-venue crypto screen must trigger the per-cell cost map"
    binance, kraken = catalog.venue("binance"), catalog.venue("kraken")
    assert fee_schedule["BTC/USDT"] == binance.taker_fee_bps          # 10 bps
    assert fee_schedule["BTC/USDT@kraken"] == kraken.taker_fee_bps    # 40 bps
    assert venue_id["BTC/USDT"] == "binance" and venue_id["BTC/USDT@kraken"] == "kraken"
    # Depth is also per-venue (Kraken's wider book), not a single scalar.
    assert depth_schedule["BTC/USDT@kraken"] == (kraken.slippage_bps, kraken.impact_bps)
    assert depth_schedule["BTC/USDT"] != depth_schedule["BTC/USDT@kraken"]

    detailed = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=binance.taker_fee_bps,
        fee_schedule=fee_schedule, depth_schedule=depth_schedule,
    )
    binance_run = detailed.per_symbol["BTC/USDT"]
    kraken_run = detailed.per_symbol["BTC/USDT@kraken"]
    assert binance_run["trades"] > 0 and kraken_run["trades"] == binance_run["trades"], "same price → same trades"
    # The ONLY difference is the fee/depth overlay → the cheaper-fee venue nets strictly more.
    assert binance_run["return"] > kraken_run["return"]


def test_single_venue_crypto_cost_context_is_none(tmp_path):
    """A crypto-only SINGLE-venue screen (no cross-venue cell) keeps the (None, …) cost context → byte-identical
    scalar fee/depth path. The universal-price extension must NOT perturb the common single-venue case."""
    from cosmu.evolution.seeder import seed_orb_fvg_spec
    from cosmu.master.screen_universe import build_cost_context
    from cosmu.spine.venue import default_catalog

    spec = seed_orb_fvg_spec()
    market = {"BTCUSDT": [], "ETHUSDT": []}
    # All cells on the primary (binance) venue → no cross-venue crypto → (None, None, None, None).
    out = build_cost_context(spec, market, default_catalog(),
                             crypto_cell_venues={"BTCUSDT": "binance", "ETHUSDT": "binance"})
    assert out == (None, None, None, None)


# --------------------------------------------------------------------------- alt fetch resolves the bare ingest key


def _seed_funding(alt_store, symbol: str, bars: list[Bar], *, value: float = 0.0005) -> None:
    """Append one immutable funding_rate point per bar (available_at == ts, PIT-honest) under `symbol` — exactly
    how ingest/run.py keys funding: provider 'binance', the BARE full-pair symbol (BTCUSDT), metric 'funding_rate'."""
    from cosmu.data.providers._types import AltDataPoint

    pts = [AltDataPoint(ts=b.ts, available_at=b.ts, value=value) for b in bars]
    alt_store.append("binance", symbol, "funding_rate", pts)


def test_alt_by_cell_maps_canonical_pair_to_bare_ingest_key(tmp_path):
    """REGRESSION (universal-price layer): a crypto cell on the POPULATED-universe screen path carries the CANONICAL
    slash pair (BTC/USDT), but ingest keys funding/OI/on-chain by the BARE full-pair symbol (BTCUSDT). _alt_by_cell
    must map canonical→bare (alt_ingest_symbol) BEFORE the alt fetch — otherwise fetch_series('BTC/USDT',
    'funding_rate') misses and funding silently reads None for every crypto cell, making funding/alt edges
    untestable on the universe path. Uses an EXACT-MATCH store (PgAltDataStore over SQLite, like prod Postgres):
    the JSONL store would MASK the bug by stripping '/' in its file path."""
    from cosmu.data.altdata import PgAltDataStore, StoreBackedAltProvider
    from cosmu.evolution.seeder import seed_funding_squeeze_spec
    from cosmu.lab.finder import _alt_by_cell

    store = _store(tmp_path)
    store.migrate()
    alt = PgAltDataStore(store)
    spec = seed_funding_squeeze_spec()  # entry feature funding_rate → spec_alt_feature_names includes it

    bars = _bars(_walk(120, seed=42))
    _seed_funding(alt, "BTCUSDT", bars)  # ingest banks funding under the BARE symbol

    # Sanity: the store is EXACT-MATCH (prod Postgres semantics) — the slash key alone finds nothing, the bare key
    # does. This mismatch is what made the regression bite: the cell carried 'BTC/USDT' but the series lives under
    # 'BTCUSDT'. (The JSONL store strips '/' in its file path and would hide this — hence the PG-backed store here.)
    provider = StoreBackedAltProvider(alt)
    assert provider.fetch_series("BTC/USDT", "funding_rate", limit=10_000) == []
    assert provider.fetch_series("BTCUSDT", "funding_rate", limit=10_000)

    # The POPULATED-universe path: the cell key + canonical symbol are the slash pair, the venue is binance.
    market = {"BTC/USDT": bars}
    cell_meta = {"BTC/USDT": ("BTC/USDT", "binance")}
    joined = _alt_by_cell(alt, spec, market, cell_meta)
    assert joined is not None, "the funding spec must produce an alt join (the regression returned None)"
    funding = joined.get("BTC/USDT", {}).get("funding_rate")
    assert funding, "the canonical cell must see REAL funding (bare-key ingest resolved), not an empty series"
    assert len(funding) == len(bars)  # one PIT value per bar

    # Parity: the empty-universe FALLBACK path (bare-symbol cells, always unaffected) sees the IDENTICAL funding.
    bare = _alt_by_cell(alt, spec, {"BTCUSDT": bars}, {"BTCUSDT": ("BTCUSDT", "binance")})
    assert bare["BTCUSDT"]["funding_rate"] == funding


def test_alt_by_cell_shares_one_funding_fetch_across_a_pairs_venue_cells(tmp_path):
    """A pair's funding is a property of the ASSET, not the venue cell: a 'BTC/USDT@kraken' cell must read the SAME
    bare-key funding as its 'BTC/USDT' binance sibling (one dedup'd fetch, replicated under each cell key) — the
    venue axis must NOT split the alt series."""
    from cosmu.data.altdata import PgAltDataStore
    from cosmu.evolution.seeder import seed_funding_squeeze_spec
    from cosmu.lab.finder import _alt_by_cell

    store = _store(tmp_path)
    store.migrate()
    alt = PgAltDataStore(store)
    spec = seed_funding_squeeze_spec()
    bars = _bars(_walk(120, seed=43))
    _seed_funding(alt, "BTCUSDT", bars)

    market = {"BTC/USDT": bars, "BTC/USDT@kraken": bars}
    cell_meta = {"BTC/USDT": ("BTC/USDT", "binance"), "BTC/USDT@kraken": ("BTC/USDT", "kraken")}
    joined = _alt_by_cell(alt, spec, market, cell_meta)
    assert joined is not None
    assert joined["BTC/USDT"]["funding_rate"], "binance cell sees funding"
    assert joined["BTC/USDT@kraken"]["funding_rate"] == joined["BTC/USDT"]["funding_rate"], "kraken cell shares it"


# ----------------------------------------------------------- the MONEY path: neutral funding-accrual bare-key fix


def test_funding_rate_asof_resolves_canonical_perp_cell_to_bare_ingest_key(tmp_path):
    """REGRESSION (LIVE/PAPER money path, parallel to the #341 screen-path fix): after the universal price layer
    (#338) a neutral short-perp track on the POPULATED-universe path stamps the CANONICAL slash pair (BTC/USDT) on
    its perp position, but ingest keys funding by the BARE full-pair Binance perp symbol (BTCUSDT). _funding_rate_asof
    does an EXACT `WHERE symbol = ?` match, so without the canonical→bare map (alt_ingest_symbol) the lookup misses on
    the prod Postgres store and the short-perp leg silently UNDER-ACCRUES funding P&L — distorting the forward record.
    Uses an EXACT-MATCH store (PgAltDataStore over SQLite, like prod Postgres): the JSONL store would MASK the bug by
    stripping '/' in its file path. (Mirrors test_alt_by_cell_maps_canonical_pair_to_bare_ingest_key on the screen path.)"""
    from cosmu.data.altdata import PgAltDataStore
    from cosmu.data.providers._types import AltDataPoint
    from cosmu.orchestrator.loop import _funding_rate_asof

    store = _store(tmp_path)
    store.migrate()
    alt = PgAltDataStore(store)

    bars = _bars(_walk(8, seed=51))  # _walk(n) -> n+1 closes/bars
    # Ingest banks funding under the BARE symbol. Two appends — an OLD then a NEWER rate (later available_at) — so
    # the asof pick (ORDER BY available_at DESC) must return the latest, exactly as on the prod money path.
    alt.append("binance", "BTCUSDT", "funding_rate",
               [AltDataPoint(ts=bars[0].ts, available_at=bars[0].ts, value=0.0001)])
    alt.append("binance", "BTCUSDT", "funding_rate",
               [AltDataPoint(ts=bars[-1].ts, available_at=bars[-1].ts, value=0.0005)])

    # Sanity: the store is EXACT-MATCH (prod Postgres semantics) — the canonical slash key alone finds NOTHING, the
    # bare key does. This mismatch is what made the regression bite: the perp cell carried 'BTC/USDT' but the series
    # lives under 'BTCUSDT'. (The JSONL store strips '/' in its file path and would hide this — hence PG-backed here.)
    _sql = "SELECT value FROM alt_data WHERE provider = 'binance' AND symbol = ? AND metric = 'funding_rate'"
    assert store.row(_sql, ("BTC/USDT",)) is None
    assert store.row(_sql, ("BTCUSDT",)) is not None

    # THE fix: the canonical-keyed perp cell resolves to the bare ingest key and reads the LATEST real rate.
    # Pre-fix this returned None (the exact match on 'BTC/USDT' missed) → funding silently under-accrued every tick.
    assert _funding_rate_asof(store, "BTC/USDT") == Decimal("0.0005")
    # Parity: the empty-universe FALLBACK path (a bare-symbol perp leg) is a no-op map → reads the IDENTICAL rate.
    assert _funding_rate_asof(store, "BTCUSDT") == Decimal("0.0005")


# --------------------------------------------------------------------------- funding preserves the cell venue


def test_funding_venue_preserves_the_cells_own_venue():
    """THE venue-axis fix: a cell the gate passed on KRAKEN funds on KRAKEN (its own screen venue, which has a real
    exec adapter), NOT collapsed back onto Binance — that collapse would defeat the whole universal-price layer. A
    data/research-only venue (ibkr, no exec adapter) falls back to the asset-class default; a None venue too."""
    from cosmu.orchestrator.loop import _funding_venue_for_cell

    # Kraken HAS an exec adapter → its crypto cell funds on Kraken (the axis stays de-collapsed).
    assert _funding_venue_for_cell("kraken", "crypto") == "kraken"
    # Binance cell → binance (unchanged legacy path).
    assert _funding_venue_for_cell("binance", "crypto") == "binance"
    # IBKR has DATA but no exec adapter → an equity cell falls back to the class default (alpaca).
    assert _funding_venue_for_cell("ibkr", "equity") == "alpaca"
    # A missing/legacy venue_id falls back to the asset-class default, never crashes.
    assert _funding_venue_for_cell(None, "crypto") == "binance"
    # An asset class with no default funding venue AND a non-executable cell venue → None (the cell is SKIPPED).
    assert _funding_venue_for_cell("ibkr", "prediction") is None
