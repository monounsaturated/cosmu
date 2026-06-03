# intent: lock the per-venue fee realism + jurisdiction model — the binding live-cost facts the gate trusts.
# Covers: catalog completeness, the real "US-legal crypto is worse than Binance" finding, volume tiering,
# the venue->cost-model bridge, and jurisdiction legality picking the live venue.

from __future__ import annotations

from decimal import Decimal

from cosmu.execution.costopt import FeeSchedule, choose_order
from cosmu.spine.venue import default_catalog


def test_catalog_has_multi_asset_venues() -> None:
    cat = default_catalog()
    ids = {v.id for v in cat.venues}
    assert {"binance", "kraken", "coinbase", "ibkr", "alpaca", "polymarket"} <= ids


def test_venue_for_prices_a_spec_against_its_own_venue() -> None:
    """The single source of fee truth: a spec is screened at its OWN declared venue's fees, not a hardcoded
    Binance. An equity spec on IBKR (~0.5 bps) must NOT inherit Binance's 10 bps taker."""
    cat = default_catalog()
    assert cat.venue_for(["ibkr"]).id == "ibkr"
    assert cat.venue_for(["ibkr"]).taker_fee_bps < cat.venue("binance").taker_fee_bps
    assert cat.venue_for([]).id == "binance"            # empty universe → the default crypto-spot venue
    assert cat.venue_for(["does-not-exist"]).id == "binance"   # unknown venue degrades to the default


def test_us_legal_crypto_is_more_expensive_than_binance() -> None:
    """The real finding: forced off Binance for US live crypto, the taker fee wall gets HIGHER."""
    cat = default_catalog()
    _, binance_taker = cat.venue("binance").effective_fee()
    _, kraken_taker = cat.venue("kraken").effective_fee()
    _, coinbase_taker = cat.venue("coinbase").effective_fee()
    assert kraken_taker > binance_taker
    assert coinbase_taker > kraken_taker


def test_equities_are_the_cheapest_live_venue() -> None:
    cat = default_catalog()
    _, ibkr_taker = cat.venue("ibkr").effective_fee()
    _, binance_taker = cat.venue("binance").effective_fee()
    assert ibkr_taker < Decimal("1")
    assert ibkr_taker < binance_taker


def test_ibkr_real_fees_and_instrument_catalog() -> None:
    """IBKR's REAL fee is ~0.5 bps (the correct conversion of $0.005/share on a ~$100 name), and it lists the
    liquid equity research universe (SPY/QQQ + AAPL/MSFT/TSLA) — priced at IBKR fees, not Binance's."""
    cat = default_catalog()
    ibkr = cat.venue("ibkr")
    assert ibkr.kind == "equity"
    assert ibkr.maker_fee_bps == Decimal("0.5") and ibkr.taker_fee_bps == Decimal("0.5")
    symbols = {i.symbol for i in cat.instruments if i.venue_id == "ibkr"}
    assert {"SPY", "QQQ", "AAPL", "MSFT", "TSLA"} <= symbols
    assert all(i.asset_class == "equity" for i in cat.instruments if i.venue_id == "ibkr")


def test_volume_tiers_lower_fees() -> None:
    binance = default_catalog().venue("binance")
    _, base = binance.effective_fee(0)
    _, high = binance.effective_fee(50_000_000)
    assert high < base


def test_jurisdiction_picks_the_live_venue() -> None:
    cat = default_catalog()
    # Binance live is unavailable in the US; Kraken/Coinbase/IBKR are available.
    assert cat.venue("binance").live_legal_in("US") is False
    assert cat.venue("binance").live_legal_in("PT") is True
    assert cat.venue("kraken").live_legal_in("US") is True
    # Data/paper venues never move money, regardless of jurisdiction.
    assert cat.venue("alpaca").live_legal_in("US") is False

    us_live = {v.id for v in cat.live_legal_venues("US")}
    assert "binance" not in us_live
    assert {"kraken", "coinbase", "ibkr"} <= us_live


def test_fee_schedule_bridge_reflects_venue_and_volume() -> None:
    binance = default_catalog().venue("binance")
    base = FeeSchedule.from_venue(binance, volume_30d_usd=0)
    high = FeeSchedule.from_venue(binance, volume_30d_usd=50_000_000)
    assert high.taker_bps < base.taker_bps
    # And it feeds the existing cost optimizer unchanged.
    plan = choose_order(gross_edge_bps=30.0, fee=base, spread_bps=4.0)
    assert plan.order_type in {"maker", "market"}
    assert plan.expected_net_bps < 30.0  # fees + spread eat into gross edge
