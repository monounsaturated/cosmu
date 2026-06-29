# PER-CELL DATA PROVENANCE + SOURCE≠VENUE DIVERGENCE (anti-black-box). The operator's rule: "a backtest result
# must never be a black box." These tests prove the two additive surfacings:
#   (1) a backtest cell exposes EXACTLY what it ran on — symbol · venue · bar source · interval · date range ·
#       #bars · holdout split · the TODAY's-schedule fee/slippage/impact overlay (fees-always-today rule);
#   (2) the SOURCE≠VENUE price divergence is made VISIBLE (not write-only): a cell whose price came from a
#       FALLBACK reference source (≠ the live venue) surfaces the divergence metric (corr/spread) + the fallback
#       flag, and a same-source (native-venue) cell shows aligned / no-fallback.
# All display/audit only — NEVER a gate input, so the locked scorer/FDR/cohort math is byte-unchanged.
# Hermetic — no network, no store mutation, pure dataclass + builder assertions.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.data.price_cells import REFERENCE_VENUE, _bar_source
from cosmu.data.reference import (
    PROVENANCE_FLAG_MAX_SPREAD_BPS,
    PROVENANCE_FLAG_MIN_CORR,
    AlignmentDecision,
    AlignmentStats,
    CellProvenance,
    cell_provenance,
)

# --------------------------------------------------------------------------- helpers


def _bars(n: int, *, start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(ts=t0 + timedelta(hours=i), open=Decimal("100"), high=Decimal("101"),
            low=Decimal("99"), close=Decimal(str(100 + i)), volume=Decimal("1000"))
        for i in range(n)
    ]


def _decision(verdict: str, *, corr: float, spread_bps: float, overlap: int) -> AlignmentDecision:
    return AlignmentDecision(
        pair="BTC/USDT", venue="kraken", verdict=verdict,
        stats=AlignmentStats(corr=corr, median_spread_bps=spread_bps, n_overlap=overlap),
    )


# --------------------------------------------------------------------------- (1) provenance facts


def test_provenance_exposes_exactly_what_the_cell_ran_on():
    """A cell exposes its full provenance: source/interval/range/#bars/holdout/fee-schedule."""
    bars = _bars(200)
    prov = cell_provenance(
        symbol="BTC/USDT", venue="kraken", bar_source="kraken-keyless", bar_interval="1h",
        bars=bars, fee_bps=40.0, slippage_bps=7.0, impact_bps=55.0,
        reuses_reference=False, decision_=None, is_reference_venue=False,
    )
    assert prov.symbol == "BTC/USDT"
    assert prov.venue == "kraken"
    assert prov.bar_source == "kraken-keyless"
    assert prov.bar_interval == "1h"
    assert prov.n_bars == 200
    assert prov.first_bar_ts == bars[0].ts.isoformat()
    assert prov.last_bar_ts == bars[-1].ts.isoformat()
    # holdout split mirrors _purged_embargoed_split: max(40, int(0.8 * n)) = 160 for n=200.
    assert prov.holdout_split_index == 160
    # the TODAY's-schedule cost overlay the backtest charged — recorded, not re-typed.
    assert prov.fee_bps == 40.0
    assert prov.slippage_bps == 7.0
    assert prov.impact_bps == 55.0


def test_provenance_holdout_none_when_too_short():
    """A cell too short to leave a holdout (< 80 bars) records holdout_split_index=None (honest unknown)."""
    prov = cell_provenance(
        symbol="X/USDT", venue="binance", bar_source="binance-reference", bar_interval="1d",
        bars=_bars(50), fee_bps=10.0, slippage_bps=5.0, impact_bps=50.0,
        reuses_reference=True, decision_=None, is_reference_venue=True,
    )
    assert prov.holdout_split_index is None
    assert prov.n_bars == 50


def test_provenance_empty_bars_has_no_range():
    prov = cell_provenance(
        symbol="X/USDT", venue="binance", bar_source="binance-reference", bar_interval="1h",
        bars=[], fee_bps=10.0, slippage_bps=5.0, impact_bps=50.0,
        reuses_reference=True, decision_=None, is_reference_venue=True,
    )
    assert prov.n_bars == 0
    assert prov.first_bar_ts is None and prov.last_bar_ts is None
    assert prov.holdout_split_index is None


# --------------------------------------------------------------------------- (2) source ≠ venue divergence


def test_reference_venue_cell_is_native_not_fallback():
    """The reference venue's OWN cell reuses the reference book — but that IS its own book, so NOT a fallback and
    NEVER divergence-flagged: a same-source cell shows aligned / no-fallback."""
    prov = cell_provenance(
        symbol="BTC/USDT", venue=REFERENCE_VENUE, bar_source="binance-reference", bar_interval="1h",
        bars=_bars(200), fee_bps=10.0, slippage_bps=5.0, impact_bps=50.0,
        reuses_reference=True, decision_=None, is_reference_venue=True,
    )
    assert prov.source_is_fallback is False
    assert prov.divergence_flagged is False
    assert "aligned (native venue source)" in prov.log_line()


def test_native_venue_fallback_cell_is_not_fallback():
    """A FALLBACK cell in the price_cells sense (scored on its venue's OWN bars, reuses_reference=False) is NATIVE:
    the price source IS the venue, so it is not a source-≠-venue fallback and is never flagged."""
    prov = cell_provenance(
        symbol="BTC/USDT", venue="kraken", bar_source="kraken-keyless", bar_interval="1h",
        bars=_bars(200), fee_bps=40.0, slippage_bps=7.0, impact_bps=55.0,
        reuses_reference=False,
        decision_=_decision("FALLBACK", corr=0.5, spread_bps=300.0, overlap=200),
        is_reference_venue=False,
    )
    assert prov.source_is_fallback is False
    assert prov.divergence_flagged is False
    assert "native venue source" in prov.log_line()


def test_unify_cell_surfaces_source_neq_venue_with_alignment():
    """A UNIFY cell is scored on the SHARED reference book while its live venue is kraken — the headline
    source-≠-venue case. It surfaces source_is_fallback=True + the divergence metric (corr/spread). With corr above
    / spread below the LOOSE display thresholds it is a clean (non-flagged) fallback."""
    prov = cell_provenance(
        symbol="BTC/USDT", venue="kraken", bar_source="binance-reference", bar_interval="1h",
        bars=_bars(200), fee_bps=40.0, slippage_bps=7.0, impact_bps=55.0,
        reuses_reference=True,
        decision_=_decision("UNIFY", corr=0.999, spread_bps=3.0, overlap=180),
        is_reference_venue=False,
    )
    assert prov.source_is_fallback is True
    assert prov.align_corr == 0.999
    assert prov.align_spread_bps == 3.0
    assert prov.align_overlap == 180
    assert prov.divergence_flagged is False  # tracks the venue tightly → trustworthy
    line = prov.log_line()
    assert "backtested on binance-reference price → live venue kraken" in line
    assert "FALLBACK source" in line
    assert "DIVERGENT" not in line


def test_divergent_fallback_is_flagged_on_low_corr():
    """A fallback whose source tracks the live venue too LOOSELY (corr below the display threshold) is FLAGGED."""
    prov = cell_provenance(
        symbol="BTC/USDT", venue="bybit", bar_source="binance-reference", bar_interval="1h",
        bars=_bars(200), fee_bps=10.0, slippage_bps=5.0, impact_bps=50.0,
        reuses_reference=True,
        decision_=_decision("FALLBACK", corr=PROVENANCE_FLAG_MIN_CORR - 0.05, spread_bps=10.0, overlap=120),
        is_reference_venue=False,
    )
    assert prov.source_is_fallback is True
    assert prov.divergence_flagged is True
    assert "⚠ DIVERGENT" in prov.log_line()


def test_divergent_fallback_is_flagged_on_wide_spread():
    """A fallback whose source sits at a persistent PREMIUM/discount (spread above the display threshold) is
    FLAGGED even when correlation is high — a level offset mis-marks every entry/exit."""
    prov = cell_provenance(
        symbol="BTC/USDT", venue="bybit", bar_source="binance-reference", bar_interval="1h",
        bars=_bars(200), fee_bps=10.0, slippage_bps=5.0, impact_bps=50.0,
        reuses_reference=True,
        decision_=_decision("UNIFY", corr=0.999, spread_bps=PROVENANCE_FLAG_MAX_SPREAD_BPS + 10.0, overlap=120),
        is_reference_venue=False,
    )
    assert prov.source_is_fallback is True
    assert prov.divergence_flagged is True


def test_fallback_with_no_alignment_is_flagged_most_suspect():
    """The per-venue-mode 'native bars missing → fall back to reference' path reuses the reference with NO measured
    alignment (decision None). A source-≠-venue fallback with no measurable alignment is the MOST suspect case →
    flagged for the operator to inspect."""
    prov = cell_provenance(
        symbol="BTC/USDT", venue="bybit", bar_source="binance-reference", bar_interval="1h",
        bars=_bars(200), fee_bps=10.0, slippage_bps=5.0, impact_bps=50.0,
        reuses_reference=True, decision_=None, is_reference_venue=False,
    )
    assert prov.source_is_fallback is True
    assert prov.align_corr is None
    assert prov.divergence_flagged is True
    assert "alignment unmeasured" in prov.log_line()


# --------------------------------------------------------------------------- serialization + log line


def test_to_dict_is_json_serializable_and_complete():
    prov = cell_provenance(
        symbol="BTC/USDT", venue="kraken", bar_source="binance-reference", bar_interval="1h",
        bars=_bars(200), fee_bps=40.0, slippage_bps=7.0, impact_bps=55.0,
        reuses_reference=True,
        decision_=_decision("UNIFY", corr=0.999, spread_bps=3.0, overlap=180),
        is_reference_venue=False,
    )
    d = prov.to_dict()
    import json

    json.dumps(d)  # must not raise
    for key in (
        "symbol", "venue", "bar_source", "bar_interval", "n_bars", "first_bar_ts", "last_bar_ts",
        "holdout_split_index", "fee_bps", "slippage_bps", "impact_bps", "reuses_reference",
        "source_is_fallback", "align_corr", "align_spread_bps", "align_overlap", "divergence_flagged",
    ):
        assert key in d
    assert d["divergence_flagged"] is False
    assert d["source_is_fallback"] is True


def test_log_line_states_source_interval_range_holdout_fees():
    prov = cell_provenance(
        symbol="ETH/USDT", venue="kraken", bar_source="kraken-keyless", bar_interval="1d",
        bars=_bars(200), fee_bps=40.0, slippage_bps=7.0, impact_bps=55.0,
        reuses_reference=False, decision_=None, is_reference_venue=False,
    )
    line = prov.log_line()
    assert line.startswith("PROVENANCE ETH/USDT@kraken:")
    assert "kraken-keyless price → live venue kraken" in line
    assert "1d" in line
    assert "200 bars" in line
    assert "holdout@160" in line
    assert "fees 40.0bps slip 7.0/55.0bps" in line


# --------------------------------------------------------------------------- _bar_source naming


def test_bar_source_names_reference_vs_native():
    assert _bar_source(venue_id="kraken", reuses_reference=True) == f"{REFERENCE_VENUE}-reference"
    assert _bar_source(venue_id="kraken", reuses_reference=False) == "kraken-keyless"
    assert _bar_source(venue_id=REFERENCE_VENUE, reuses_reference=True) == f"{REFERENCE_VENUE}-reference"


# --------------------------------------------------------------------------- finder end-to-end provenance


def test_finder_build_provenance_populates_per_cell_record():
    """The finder's _build_provenance assembles one CellProvenance per cell from the assembled bars + the cost
    overlay + the cell sources — the seam that attaches provenance to the result. A reference cell shows native /
    no-fallback; a UNIFY-on-another-venue cell shows the source-≠-venue divergence + the alignment metric."""
    from cosmu.lab.finder import CellSource, StrategyFinder

    finder = StrategyFinder.__new__(StrategyFinder)  # no store/network needed for this pure helper

    class _Venue:
        id = "binance"
        taker_fee_bps = Decimal("10")
        slippage_bps = Decimal("5")
        impact_bps = Decimal("50")

    class _Spec:
        class horizon:
            bar_size = "1h"

    market = {"BTC/USDT": _bars(200), "BTC/USDT@kraken": _bars(200)}
    cell_meta = {"BTC/USDT": ("BTC/USDT", "binance"), "BTC/USDT@kraken": ("BTC/USDT", "kraken")}
    cell_sources = {
        "BTC/USDT": CellSource(
            bar_source="binance-reference", reuses_reference=True, is_reference_venue=True, decision=None,
        ),
        "BTC/USDT@kraken": CellSource(
            bar_source="binance-reference", reuses_reference=True, is_reference_venue=False,
            decision=_decision("UNIFY", corr=0.999, spread_bps=3.0, overlap=180),
        ),
    }
    # cross-venue cost overlay: the kraken cell pays kraken's 40bps / 7-55 depth, the binance cell the scalar.
    fee_schedule = {"BTC/USDT": Decimal("10"), "BTC/USDT@kraken": Decimal("40")}
    depth_schedule = {"BTC/USDT": (Decimal("5"), Decimal("50")), "BTC/USDT@kraken": (Decimal("7"), Decimal("55"))}

    prov = finder._build_provenance(
        _Spec(), market, cell_meta, cell_sources, _Venue(), fee_schedule, depth_schedule
    )
    assert set(prov) == {"BTC/USDT", "BTC/USDT@kraken"}

    ref = prov["BTC/USDT"]
    assert ref.venue == "binance"
    assert ref.source_is_fallback is False
    assert ref.divergence_flagged is False
    assert ref.fee_bps == 10.0

    kraken = prov["BTC/USDT@kraken"]
    assert kraken.venue == "kraken"
    assert kraken.bar_source == "binance-reference"
    assert kraken.source_is_fallback is True  # scored on the binance reference, live venue kraken
    assert kraken.align_corr == 0.999
    assert kraken.divergence_flagged is False  # tracks tightly
    assert kraken.fee_bps == 40.0  # the kraken overlay, not the scalar
    assert kraken.slippage_bps == 7.0 and kraken.impact_bps == 55.0


def test_finder_build_provenance_scalar_fallback_when_no_schedule():
    """The crypto-only single-venue path passes fee_schedule=None — the provenance records the spec's primary-venue
    SCALAR fee/depth (the byte-identical path), so a provenance line is still emitted with the real cost used."""
    from cosmu.lab.finder import CellSource, StrategyFinder

    finder = StrategyFinder.__new__(StrategyFinder)

    class _Venue:
        id = "binance"
        taker_fee_bps = Decimal("10")
        slippage_bps = Decimal("5")
        impact_bps = Decimal("50")

    class _Spec:
        class horizon:
            bar_size = "1h"

    market = {"BTCUSDT": _bars(200)}
    cell_meta = {"BTCUSDT": ("BTCUSDT", "binance")}
    cell_sources = {
        "BTCUSDT": CellSource(
            bar_source="binance-reference", reuses_reference=True, is_reference_venue=True, decision=None,
        )
    }
    prov = finder._build_provenance(_Spec(), market, cell_meta, cell_sources, _Venue(), None, None)
    cell = prov["BTCUSDT"]
    assert cell.fee_bps == 10.0 and cell.slippage_bps == 5.0 and cell.impact_bps == 50.0
    assert cell.source_is_fallback is False
    assert isinstance(cell, CellProvenance)
