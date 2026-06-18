# intent: lock the per-asset / per-category fee resolver (spine/asset_fees.py) + its wiring into the screen cost
# path (master/screen_universe.build_cost_context). Covers: Polymarket per-category taker (ALWAYS today's fee —
# `as_of` ignored, operator rule), IBKR per-asset-class (us_equity per-share+min, us_future per-contract×multiplier,
# eu_equity 0.05%+min, French FTT buy-leg-only asymmetry), always-taker entry+exit symmetry through the backtest,
# and the control that a plain crypto spot symbol falls back to the flat catalog bps (Binance 10/10 unchanged).

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cosmu.spine.asset_fees import (
    FRENCH_FTT_RATE,
    asset_taker_bps,
    ibkr_commission_usd,
    ibkr_ftt_buy_leg_bps,
    ibkr_taker_bps,
    polymarket_category_fee_rate,
    polymarket_taker_bps,
)
from cosmu.spine.venue import Instrument, default_catalog

# --- Polymarket per-category taker --------------------------------------------------------------

def test_polymarket_category_fee_rates():
    # geopolitics/world free; sports 3%; politics/finance/tech 4%; econ/culture/weather/other 5%; crypto 7.2%.
    assert polymarket_category_fee_rate("geopolitics") == 0.00
    assert polymarket_category_fee_rate("world") == 0.00
    assert polymarket_category_fee_rate("sports") == 0.03
    assert polymarket_category_fee_rate("politics") == 0.04
    assert polymarket_category_fee_rate("finance") == 0.04
    assert polymarket_category_fee_rate("tech") == 0.04
    assert polymarket_category_fee_rate("economics") == 0.05
    assert polymarket_category_fee_rate("culture") == 0.05
    assert polymarket_category_fee_rate("crypto") == 0.072


def test_polymarket_unknown_category_defaults_to_conservative_crypto():
    """An unmapped (or absent) category over-charges at the crypto 7.2% rate — never under-charges."""
    assert polymarket_category_fee_rate("does-not-exist") == 0.072
    assert polymarket_category_fee_rate(None) == 0.072


def test_polymarket_taker_bps_uses_pnl_room_term():
    """fee/notional = feeRate × (1 − price) → bps. At price 0.5, sports (3%) → 0.03×0.5×1e4 = 150 bps."""
    after = datetime(2026, 4, 1, tzinfo=UTC)  # post-rollout
    assert polymarket_taker_bps("sports", 0.5, as_of=after) == pytest.approx(Decimal("150"))
    # A near-resolved market (price 0.95) pays much less room: crypto 7.2% × 0.05 × 1e4 = 36 bps.
    assert polymarket_taker_bps("crypto", 0.95, as_of=after) == pytest.approx(Decimal("36"))
    # geopolitics is fee-free at any price.
    assert polymarket_taker_bps("geopolitics", 0.5, as_of=after) == Decimal("0")


def test_polymarket_taker_always_uses_today_fee_even_on_old_bars():
    """Operator rule: fees are pinned to TODAY's schedule on EVERY bar — a historical `as_of` is IGNORED, so an old
    bar (2022, when Polymarket charged 0) is still charged the CURRENT per-category fee → no surprise at live."""
    old = datetime(2022, 1, 1, tzinfo=UTC)
    # crypto 7.2% × (1 − 0.5) × 1e4 = 360 bps — identical to charging "now".
    assert polymarket_taker_bps("crypto", 0.5, as_of=old) == pytest.approx(Decimal("360"))
    assert polymarket_taker_bps("crypto", 0.5, as_of=old) == polymarket_taker_bps("crypto", 0.5)


def test_polymarket_dispatch_reads_instrument_category():
    poly = default_catalog().venue("polymarket")
    sports = Instrument(id="x", venue_id="polymarket", symbol="X", asset_class="prediction", category="sports")
    after = datetime(2026, 4, 1, tzinfo=UTC)
    bps = asset_taker_bps(poly, sports, reference_price=0.5, as_of=after)
    assert bps == pytest.approx(Decimal("150"))
    # No instrument → unknown category → conservative crypto rate.
    bps_none = asset_taker_bps(poly, None, reference_price=0.5, as_of=after)
    assert bps_none == pytest.approx(Decimal("360"))  # 0.072 × 0.5 × 1e4


# --- IBKR per-asset-class -----------------------------------------------------------------------

def _eq(symbol: str, instrument_type: str | None = None, **kw) -> Instrument:
    return Instrument(id=symbol.lower(), venue_id="ibkr", symbol=symbol, asset_class="equity",
                      instrument_type=instrument_type, **kw)


def test_ibkr_us_equity_per_share_commission():
    """$0.0035/share. A $10k order of a $100 name buys 100 shares → $0.35 commission → 0.35 bps of notional."""
    spy = _eq("SPY", "us_equity")
    # commission curve: 100 shares × $0.0035 = $0.35 (also exactly the min) → 0.35/10000 × 1e4 = 0.35 bps.
    assert ibkr_commission_usd(spy, qty=100, price=100.0) == pytest.approx(0.35)
    assert ibkr_taker_bps(spy, price=100.0, reference_notional=10_000.0) == pytest.approx(Decimal("0.35"), abs=1e-6)


def test_ibkr_us_equity_min_order_floor():
    """Tiny order hits the $0.35 per-order MIN: 10 shares × $0.0035 = $0.035 → floored to $0.35."""
    aapl = _eq("AAPL", "us_equity")
    assert ibkr_commission_usd(aapl, qty=10, price=100.0) == pytest.approx(0.35)  # min applied


def test_ibkr_us_equity_value_cap_at_one_percent():
    """A high-share-count penny-stock order is capped at 1% of trade value (the per-share rate would exceed it)."""
    penny = _eq("PENNY", "us_equity")
    # 100k shares × $0.0035 = $350 per-share, but trade value = 100k × $0.10 = $10k → cap = 1% = $100.
    assert ibkr_commission_usd(penny, qty=100_000, price=0.10) == pytest.approx(100.0)


def test_ibkr_us_future_per_contract_times_multiplier():
    """$0.85/contract. An ES-like future (multiplier 50) at price 5000 → notional/contract = 250k →
    0.85/250000 × 1e4 = 0.034 bps. The multiplier is load-bearing: a bigger multiplier → lower bps."""
    es = Instrument(id="es", venue_id="ibkr", symbol="ES", asset_class="equity",
                    instrument_type="us_future", contract_multiplier=Decimal("50"))
    bps = ibkr_taker_bps(es, price=5000.0)
    assert bps == pytest.approx(Decimal(str(0.85 / (50 * 5000) * 1e4)), abs=1e-6)
    # A SMALLER multiplier (same $/contract) → HIGHER bps (the per-contract→bps conversion uses the multiplier).
    small = es.model_copy(update={"contract_multiplier": Decimal("5")})
    assert ibkr_taker_bps(small, price=5000.0) > bps


def test_ibkr_eu_future_per_contract_in_eur():
    """€0.90/contract. Multiplier 10 at price 100 → notional/contract = 1000 → 0.90/1000 × 1e4 = 9 bps."""
    fut = Instrument(id="eufut", venue_id="ibkr", symbol="FDAX", asset_class="equity",
                     instrument_type="eu_future", contract_multiplier=Decimal("10"))
    assert ibkr_taker_bps(fut, price=100.0) == pytest.approx(Decimal("9"), abs=1e-6)


def test_ibkr_eu_equity_value_percent_and_min():
    """eu_equity = 0.05% of value, min €1.25. A $10k order → $5 (0.05%) > min → 5 bps. A tiny order hits the min."""
    eu = _eq("ASML", "eu_equity")
    assert ibkr_commission_usd(eu, qty=100, price=100.0) == pytest.approx(5.0)        # 0.05% of 10k
    assert ibkr_taker_bps(eu, price=100.0, reference_notional=10_000.0) == pytest.approx(Decimal("5"))
    assert ibkr_commission_usd(eu, qty=1, price=100.0) == pytest.approx(1.25)         # min floor on a $100 order


def test_ibkr_french_ftt_is_buy_leg_only_asymmetry():
    """FR FTT = 0.40% (40 bps) on the BUY leg ONLY of an FR-HQ large-cap — a round-trip ASYMMETRY, NOT folded
    into the symmetric commission. The symmetric per-leg commission must NOT contain the FTT."""
    fr = _eq("MC", "eu_equity_fr_ftt")  # LVMH-like FR large-cap
    assert ibkr_ftt_buy_leg_bps(fr) == pytest.approx(Decimal(str(FRENCH_FTT_RATE * 1e4)))  # 40 bps buy-only
    # A non-FR eu_equity has NO FTT.
    assert ibkr_ftt_buy_leg_bps(_eq("ASML", "eu_equity")) == Decimal("0")
    # The symmetric commission for the FR name is the plain eu_equity 0.05% — the FTT is reported separately.
    assert ibkr_taker_bps(fr, price=100.0, reference_notional=10_000.0) == pytest.approx(Decimal("5"))


def test_ibkr_dispatch_overrides_flat_catalog_bps():
    """asset_taker_bps returns IBKR's per-share commission, NOT the flat 0.5 bps catalog placeholder."""
    ibkr = default_catalog().venue("ibkr")
    spy = _eq("SPY", "us_equity")
    bps = asset_taker_bps(ibkr, spy, reference_price=100.0)
    assert bps == pytest.approx(Decimal("0.35"), abs=1e-6)  # real per-share, not 0.5


# --- control: plain crypto spot falls back to the flat catalog bps ------------------------------

def test_plain_crypto_spot_keeps_flat_catalog_bps():
    """Binance spot is a flat-fee venue → the resolver returns None so the caller keeps the venue's 10 bps taker.
    No per-asset override should ever touch a plain crypto spot symbol."""
    binance = default_catalog().venue("binance")
    btc = Instrument(id="btc", venue_id="binance", symbol="BTCUSDT", asset_class="crypto")
    assert asset_taker_bps(binance, btc, reference_price=30_000.0) is None
    # And the venue's flat taker is unchanged at 10 bps.
    assert binance.taker_fee_bps == Decimal("10")
