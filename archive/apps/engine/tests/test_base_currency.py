# The USDC liquidity-first base-currency decision module (spine/base_currency.py). Two SEPARATE legs:
#   (a) TRADE leg  — liquidity WINS: deeper book is the cheap fill; USDC only on a near-tie.
#   (b) STORAGE leg — settlement DEFAULTS to USDC (the stable end-state), with documented venue exceptions.
#   (c) needs_usdt — keep USDT only when load-bearing (actively trading a USDT pair, or a USDT-first venue).
# Pure + offline (no store, no network, no clock) — these tests pin the rule directly. PROPOSE-ONLY: no live
# behavior is touched; the module is exercised here only.

from __future__ import annotations

from cosmu.spine.base_currency import (
    COMPARABLE_BOOK_TOLERANCE,
    USDC,
    USDT,
    choose_trade_quote,
    needs_usdt,
    normalize_quote,
    settlement_quote,
)

# -----------------------------------------------------------------------------------------------------------------
# (a) TRADE leg — liquidity wins
# -----------------------------------------------------------------------------------------------------------------


def test_deep_usdt_thin_usdc_trades_usdt():
    # BTCUSDT trades ~1MM, BTCUSDC ~1k → route into the deep USDT book; the thin USDC book would pay spread/impact.
    d = choose_trade_quote("BTC", "binance", {"USDT": 1_000_000.0, "USDC": 1_000.0})
    assert d.quote == USDT
    assert "liquidity wins" in d.rationale
    assert d.usdt_liquidity == 1_000_000.0 and d.usdc_liquidity == 1_000.0


def test_deep_usdc_thin_usdt_trades_usdc():
    # The mirror: a venue/pair where the USDC book is the deep one → liquidity wins for USDC.
    d = choose_trade_quote("ETH", "kraken", {"USDC": 5_000_000.0, "USDT": 10_000.0})
    assert d.quote == USDC
    assert "liquidity wins" in d.rationale


def test_comparable_books_prefer_usdc():
    # Books within the tolerance band (USDC 90k vs USDT 100k → 0.9 ≥ 0.75) → the tie-break toward the stable
    # end-state picks USDC even though USDT is marginally deeper.
    d = choose_trade_quote("SOL", "kraken", {"USDT": 100_000.0, "USDC": 90_000.0})
    assert d.quote == USDC
    assert "comparable" in d.rationale


def test_just_outside_tolerance_liquidity_wins():
    # USDC at 70% of the USDT book is OUTSIDE the 25% band (0.70 < 0.75) → liquidity wins, route USDT.
    d = choose_trade_quote("SOL", "kraken", {"USDT": 100_000.0, "USDC": 70_000.0})
    assert d.quote == USDT
    assert "liquidity wins" in d.rationale


def test_usd_quote_folds_into_usdt_for_trade_leg():
    # A venue spelling its dollar book as 'USD' (Kraken/Coinbase) competes with USDT; a deep USD book beats a
    # thin USDC book on the trade leg.
    d = choose_trade_quote("BTC", "kraken", {"USD": 2_000_000.0, "USDC": 5_000.0})
    assert d.quote == USDT  # USD folded to USDT, the deep dollar book


def test_no_measured_book_defaults_to_usdc():
    # Zero/empty depth → we don't claim a liquidity win; default to the stable rest currency, honestly flagged.
    d = choose_trade_quote("XYZ", "binance", {})
    assert d.quote == USDC
    assert "default" in d.rationale.lower()


def test_polymarket_trade_is_usdc_native_regardless_of_figures():
    # Polymarket is USDC-native (CLOB settles USDC on Polygon) — no USDT book exists; trade USDC even if a bogus
    # USDT figure is passed.
    d = choose_trade_quote("PM-FED-CUT-2026", "polymarket", {"USDT": 9_999_999.0})
    assert d.quote == USDC
    assert "USDC-only" in d.rationale


def test_hyperliquid_trade_is_usdc_only():
    # Hyperliquid margins in USDC collateral → USDC-only on the trade leg.
    d = choose_trade_quote("BTC", "hyperliquid", {"USD": 50_000_000.0})
    assert d.quote == USDC


# -----------------------------------------------------------------------------------------------------------------
# (b) STORAGE / settlement leg — defaults to USDC
# -----------------------------------------------------------------------------------------------------------------


def test_settlement_defaults_to_usdc():
    # The general rule: kill a bot / realize a position → rest in USDC.
    assert settlement_quote("binance") == USDC
    assert settlement_quote("kraken") == USDC
    assert settlement_quote("coinbase") == USDC


def test_polymarket_settlement_is_usdc_native():
    assert settlement_quote("polymarket") == USDC


def test_hyperliquid_settlement_is_usdc():
    assert settlement_quote("hyperliquid") == USDC


# -----------------------------------------------------------------------------------------------------------------
# (c) needs_usdt — keep USDT only when load-bearing
# -----------------------------------------------------------------------------------------------------------------


def test_actively_trading_usdt_pair_needs_usdt():
    # A live USDT-quoted pair being traded → hold USDT (don't churn USDT↔USDC every step).
    assert needs_usdt("BTCUSDT", "binance", actively_trading=True) is True


def test_idle_usdt_pair_does_not_need_usdt():
    # Same pair but NOT actively trading → sweep back to USDC (no reason to hold USDT).
    assert needs_usdt("BTCUSDT", "binance", actively_trading=False) is False


def test_usdc_pair_never_needs_usdt():
    # Trading a USDC-quoted pair → no USDT needed even while active.
    assert needs_usdt("BTCUSDC", "binance", actively_trading=True) is False


def test_usdc_only_venue_never_needs_usdt():
    # Polymarket / Hyperliquid have no USDT leg → never hold USDT there, active or not.
    assert needs_usdt("PM-FED-CUT-2026", "polymarket", actively_trading=True) is False
    assert needs_usdt("BTC", "hyperliquid", actively_trading=True) is False


def test_bare_base_symbol_does_not_need_usdt():
    # A bare base ('BTC', no quote in the string) is not USDT-quoted → no USDT demanded.
    assert needs_usdt("BTC", "binance", actively_trading=True) is False


# -----------------------------------------------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------------------------------------------


def test_normalize_quote_folds_usd_to_usdt():
    assert normalize_quote("usd") == USDT
    assert normalize_quote("USDC") == USDC
    assert normalize_quote(" usdt ") == USDT
    assert normalize_quote("EUR") == "EUR"  # untouched — not a dollar book


def test_tolerance_constant_is_sane():
    # Guard the documented band so a future edit doesn't silently make every book "comparable".
    assert 0.0 < COMPARABLE_BOOK_TOLERANCE < 0.5
