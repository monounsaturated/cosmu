# intent: lock the per-venue fee realism + jurisdiction model — the binding live-cost facts the gate trusts.
# Covers: catalog completeness, the real "US-legal crypto is worse than Binance" finding, volume tiering,
# the venue->cost-model bridge, and jurisdiction legality picking the live venue.

from __future__ import annotations

from decimal import Decimal

from cosmu.spine.venue import default_catalog


def test_catalog_has_multi_asset_venues() -> None:
    cat = default_catalog()
    ids = {v.id for v in cat.venues}
    assert {"binance", "kraken", "coinbase", "ibkr", "alpaca", "polymarket", "okx", "kraken_futures"} <= ids


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


def test_kraken_spot_is_a_live_venue_with_real_fees_and_depth() -> None:
    """Kraken SPOT now has a wired exec adapter (cosmu/adapters/exec/kraken.py) → live_enabled. Its real
    cost triple (taker fee + slippage + impact) resolves via cost_inputs() so the backtest prices it honestly,
    and SPOT is FR/EU-legal (MiCA) + US-legal — restricted_jurisdictions stays empty (the ESMA derivatives
    wall lives on kraken_futures, not spot)."""
    cat = default_catalog()
    kraken = cat.venue("kraken")
    assert kraken.kind == "crypto" and kraken.live_enabled is True
    # Kraken's REAL retail spot schedule is 25/40 bps (was a too-low 16/26 placeholder).
    assert kraken.maker_fee_bps == Decimal("25") and kraken.taker_fee_bps == Decimal("40")
    taker, slippage, impact = kraken.cost_inputs()
    assert taker == Decimal("40") and slippage > 0 and impact > 0  # full per-venue cost triple resolves
    # Spot is legal FR/EU + US — no jurisdiction restriction on the spot venue.
    assert kraken.live_legal_in("FR") is True
    assert kraken.live_legal_in("US") is True
    assert kraken.restricted_jurisdictions == []
    assert "kraken" in {v.id for v in cat.live_legal_venues("FR")}


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


def test_eu_venues_are_data_only_not_live() -> None:
    """OKX and Kraken Futures are wired as data/research venues — no money moves until live interlock passes."""
    cat = default_catalog()
    assert cat.venue("okx").live_enabled is False
    assert cat.venue("kraken_futures").live_enabled is False


def test_polymarket_is_a_live_venue_with_zero_fees_and_us_restricted() -> None:
    """Polymarket has a wired execution adapter → live_enabled. The CLOB has no per-trade fee (0 bps is real,
    not a stub — settlement is gasless via the relayer), and US persons are blocked, so jurisdiction picks it
    for FR/EU but never the US."""
    cat = default_catalog()
    poly = cat.venue("polymarket")
    assert poly.kind == "prediction" and poly.live_enabled is True
    assert poly.maker_fee_bps == Decimal("0") and poly.taker_fee_bps == Decimal("0")
    assert poly.live_legal_in("US") is False           # Polymarket blocks US persons
    assert poly.live_legal_in("FR") is True             # legal from FR/EU
    assert "polymarket" in {v.id for v in cat.live_legal_venues("FR")}
    assert "polymarket" not in {v.id for v in cat.live_legal_venues("US")}


def test_okx_real_fees_and_instruments() -> None:
    """OKX fees: retail 8/10 bps spot, tighten at volume (MiCA EU entity). Instruments: spot + swap."""
    cat = default_catalog()
    okx = cat.venue("okx")
    assert okx.maker_fee_bps == Decimal("8") and okx.taker_fee_bps == Decimal("10")
    # Volume tiers lower fees
    _, base_taker = okx.effective_fee(0)
    _, high_taker = okx.effective_fee(400_000_000)
    assert high_taker < base_taker
    # Both spot and perp symbols catalogued
    okx_symbols = {i.symbol for i in cat.instruments if i.venue_id == "okx"}
    assert {"BTC-USDT", "ETH-USDT", "BTC-USDT-SWAP", "ETH-USDT-SWAP"} <= okx_symbols


def test_kraken_futures_real_fees_and_instruments() -> None:
    """Kraken Futures: retail 2/5 bps perps, maker rebate at >$100M. Instruments: PF_ linear perps."""
    cat = default_catalog()
    kf = cat.venue("kraken_futures")
    assert kf.maker_fee_bps == Decimal("2") and kf.taker_fee_bps == Decimal("5")
    # Maker rebate at highest tier (negative maker = rebate)
    best_maker, _ = kf.effective_fee(200_000_000)
    assert best_maker < Decimal("0")
    # Linear perps catalogued
    kf_symbols = {i.symbol for i in cat.instruments if i.venue_id == "kraken_futures"}
    assert {"PF_XBTUSD", "PF_ETHUSD"} <= kf_symbols


def test_fr_eu_legality_is_correct() -> None:
    """FR/EU operator can use Binance spot, OKX, Kraken (spot), Kraken Futures, IBKR. US is restricted on crypto."""
    cat = default_catalog()
    # OKX and Kraken Futures are not live-enabled so live_legal_in always False regardless of jurisdiction
    assert cat.venue("okx").live_legal_in("FR") is False
    assert cat.venue("kraken_futures").live_legal_in("FR") is False
    # Once live_enabled=True (post interlock), jurisdiction must allow FR
    assert "FR" not in cat.venue("okx").restricted_jurisdictions
    assert "FR" not in cat.venue("kraken_futures").restricted_jurisdictions
    # US is restricted on all crypto derivatives and OKX
    assert "US" in cat.venue("okx").restricted_jurisdictions
    assert "US" in cat.venue("kraken_futures").restricted_jurisdictions
    # Binance spot and IBKR jurisdiction flags remain correct
    assert cat.venue("binance").live_legal_in("FR") is True
    assert cat.venue("ibkr").live_legal_in("FR") is True


def test_venue_for_resolves_new_venues() -> None:
    """venue_for() dispatches OKX and Kraken Futures specs to their own fee models."""
    cat = default_catalog()
    assert cat.venue_for(["okx"]).id == "okx"
    assert cat.venue_for(["kraken_futures"]).id == "kraken_futures"
    # Kraken Futures perp fees are cheaper than Binance spot at base volume
    _, kf_taker = cat.venue("kraken_futures").effective_fee(0)
    _, binance_taker = cat.venue("binance").effective_fee(0)
    assert kf_taker < binance_taker


def test_fee_schedule_bridge_reflects_venue_and_volume() -> None:
    """The venue→cost-model bridge is now Venue.cost_inputs()/effective_fee (the deleted costopt.FeeSchedule
    maker/taker optimizer was dead). The backtest's per-symbol fee axis reads this taker, tiered by volume."""
    binance = default_catalog().venue("binance")
    base_taker, base_slip, base_impact = binance.cost_inputs(volume_30d_usd=0)
    high_taker, _, _ = binance.cost_inputs(volume_30d_usd=50_000_000)
    assert high_taker < base_taker                 # volume → cheaper taker (the real profit lever)
    assert base_slip > 0 and base_impact > 0       # the full cost triple (fee + depth) resolves from one call


def test_venue_catalog_api_surfaces_depth_and_region() -> None:
    """The read-only venue catalog now lists per-venue market depth + jurisdiction provenance, not just fees —
    so the UI can show 'fees · depth · region · entity' per venue. A thin event book surfaces a wider spread."""
    from cosmu.api.routers.live import live_venue_catalog

    by = {v.id: v for v in live_venue_catalog().venues}
    assert by["binance"].slippage_bps > 0 and by["binance"].impact_bps > 0
    assert by["okx"].region and by["okx"].legal_entity and "Malta" in by["okx"].legal_entity
    # Polymarket's thin long-tail book surfaces a wider half-spread than Binance's deep spot book.
    assert by["polymarket"].slippage_bps > by["binance"].slippage_bps
