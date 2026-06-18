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
