# intent: the Deribit OPTIONS fee model the inefficiency scanner charges on every leg — because the scanner is
# maker-by-nature (it rests for an edge), the load-bearing honest facts are: (1) Deribit options charge the SAME
# fee maker and taker — there is NO maker rebate on options (unlike perps), so a "maker" fill saves the SPREAD,
# never a fee; (2) the per-contract fee is 0.03% of the underlying index, but CAPPED at 12.5% of the option's
# premium — and for cheap long-tail OTM options the CAP binds, which is exactly our sub-capacity lane. A model
# that ignored the cap would massively over-charge the long-tail and kill real edges; a model that ignored that
# maker==taker would invent a phantom rebate. Both are encoded here, dated, and reconfirmed manually (live OFF).
# Mirrors the project rule (memory: fees_always_today) — backtests/scans charge TODAY's published schedule.

from __future__ import annotations

from dataclasses import dataclass

# Deribit options fee schedule — VERIFIED 2026-06-29 against deribit.com/kb/fees. Reconfirm manually before any
# live arming (this is a research substrate; no money path). Figures are identical for BTC and ETH options.
FEES_VERIFIED_AT = "2026-06-29"

# Per-contract trade fee = 0.03% of the underlying index price, i.e. 0.0003 of the coin per contract.
OPTION_FEE_RATE = 0.0003
# ...but capped at 12.5% of the option's PREMIUM (price). For an option priced below 0.0024 coin the cap binds
# (0.125 * 0.0024 = 0.0003), so the long-tail OTM strikes — our sub-capacity lane — pay the (smaller) capped fee.
OPTION_FEE_CAP_FRACTION = 0.125
# Delivery (settlement/exercise) fee on an ITM option held to expiry = 0.015% of index, same 12.5% premium cap.
# Charged ONCE at settlement, never on an open/close trade; the scanner's maker arbs close before expiry, so this
# is reported for completeness and only added when a leg is modeled as held-to-delivery.
DELIVERY_FEE_RATE = 0.00015

# Deribit options have NO maker rebate — maker and taker pay the identical trade fee. This constant exists so the
# fact is asserted in code (and in tests), not buried in a comment.
OPTION_MAKER_EQUALS_TAKER = True


@dataclass(frozen=True)
class DeribitOptionFees:
    """The Deribit options fee schedule, defaulting to the verified live figures. Override the rates only for a
    what-if; the scanner uses the default. All fees are returned in USD."""

    fee_rate: float = OPTION_FEE_RATE
    cap_fraction: float = OPTION_FEE_CAP_FRACTION
    delivery_rate: float = DELIVERY_FEE_RATE

    def per_contract_fee_usd(self, index_price: float, option_price_coin: float | None) -> float:
        """The trade fee for ONE contract, in USD. = min(fee_rate, cap_fraction * premium_coin) * index_price.
        `option_price_coin` is the option's premium in coin (mark/mid); when None or 0 we conservatively charge the
        UNCAPPED flat fee (no premium to cap against). Maker and taker are identical (no options rebate)."""
        if index_price <= 0:
            return 0.0
        flat_coin = self.fee_rate
        if option_price_coin is not None and option_price_coin > 0:
            capped_coin = min(flat_coin, self.cap_fraction * option_price_coin)
        else:
            capped_coin = flat_coin
        return capped_coin * index_price

    def trade_fee_usd(
        self,
        index_price: float,
        option_price_coin: float | None,
        contracts: float,
        *,
        is_maker: bool = False,  # noqa: ARG002 — accepted for call-site clarity; options maker==taker (asserted)
    ) -> float:
        """Total trade fee in USD for `contracts` contracts. `is_maker` is accepted so call sites read honestly,
        but it does NOT change the fee — Deribit options charge maker == taker (OPTION_MAKER_EQUALS_TAKER)."""
        return self.per_contract_fee_usd(index_price, option_price_coin) * abs(contracts)

    def delivery_fee_usd(self, index_price: float, option_price_coin: float | None, contracts: float) -> float:
        """Settlement fee in USD if a contract is held to expiry ITM. Same 12.5% premium cap as the trade fee."""
        if index_price <= 0:
            return 0.0
        flat_coin = self.delivery_rate
        if option_price_coin is not None and option_price_coin > 0:
            capped_coin = min(flat_coin, self.cap_fraction * option_price_coin)
        else:
            capped_coin = flat_coin
        return capped_coin * index_price * abs(contracts)
