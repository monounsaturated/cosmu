"""fees.py — the Deribit options fee model: the 12.5%-of-premium cap, maker==taker, and the delivery fee."""

from __future__ import annotations

from cosmu.options.fees import OPTION_MAKER_EQUALS_TAKER, DeribitOptionFees


def test_flat_fee_when_cap_does_not_bind():
    f = DeribitOptionFees()
    # rich option (0.10 coin): 12.5% * 0.10 = 0.0125 >> 0.0003 → flat 0.0003 * index
    assert f.per_contract_fee_usd(1000.0, 0.10) == 0.0003 * 1000.0


def test_cap_binds_for_cheap_long_tail_option():
    f = DeribitOptionFees()
    # cheap option (0.001 coin): 12.5% * 0.001 = 0.000125 < 0.0003 → cap binds, fee = 0.000125 * index
    assert f.per_contract_fee_usd(1000.0, 0.001) == 0.000125 * 1000.0
    # exactly at the breakpoint price 0.0024: 0.125*0.0024 = 0.0003 → equal to flat
    assert abs(f.per_contract_fee_usd(1000.0, 0.0024) - 0.0003 * 1000.0) < 1e-9


def test_none_or_zero_price_charges_uncapped_flat():
    f = DeribitOptionFees()
    assert f.per_contract_fee_usd(1000.0, None) == 0.0003 * 1000.0
    assert f.per_contract_fee_usd(1000.0, 0.0) == 0.0003 * 1000.0


def test_zero_index_is_free():
    assert DeribitOptionFees().per_contract_fee_usd(0.0, 0.1) == 0.0


def test_maker_equals_taker_for_options():
    f = DeribitOptionFees()
    assert OPTION_MAKER_EQUALS_TAKER is True
    maker = f.trade_fee_usd(1000.0, 0.10, 3.0, is_maker=True)
    taker = f.trade_fee_usd(1000.0, 0.10, 3.0, is_maker=False)
    assert maker == taker == 0.0003 * 1000.0 * 3.0


def test_delivery_fee_capped_too():
    f = DeribitOptionFees()
    # rich option: flat 0.00015 * index
    assert f.delivery_fee_usd(1000.0, 0.10, 2.0) == 0.00015 * 1000.0 * 2.0
    # cheap option (0.0005): 12.5% * 0.0005 = 0.0000625 < 0.00015 → cap binds
    assert f.delivery_fee_usd(1000.0, 0.0005, 1.0) == 0.0000625 * 1000.0
