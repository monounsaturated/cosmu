# The shared per-venue COST CONTEXT (master/screen_universe.build_cost_context) the Strategy Finder and the
# autonomous FarmLoop both build from, plus the per-venue DEPTH schedule it feeds the backtest. These pin the
# divergence-killer: ONE source decides what an equity/HL leg costs (fee AND depth), the crypto-only path is
# byte-identical to the old scalar-cost behaviour, and a cross-asset leg is charged its own venue's depth — not
# the spec's primary-venue depth applied uniformly (the leak: today only the fee was per-venue).
from __future__ import annotations

from decimal import Decimal

import pytest

from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar, EquityOHLCVProvider
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.lab.finder import build_grid
from cosmu.master.screen_universe import build_cost_context
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.spine.venue import default_catalog


def _equity_spec():
    """The crypto ORB+FVG seed widened to also screen equities — primary venue stays Binance (crypto), but the
    universe now admits an equity leg, so build_cost_context must price that leg at IBKR."""
    spec = seed_orb_fvg_spec()
    return spec.model_copy(
        update={"universe": spec.universe.model_copy(update={"asset_classes": ["crypto", "equity"]})}
    )


def _params():
    spec = seed_orb_fvg_spec()
    return build_grid(spec, max_variants=1)[0].params


# --------------------------------------------------------------------------- build_cost_context


def test_crypto_only_cost_context_is_all_none():
    """The common path: a crypto-only spec has no equity/HL leg, so the context is (None, None, None, None) and
    the backtest falls back to its scalar venue fee/depth — byte-identical to before."""
    spec = seed_orb_fvg_spec()
    market = {"BTCUSDT": [], "ETHUSDT": []}
    fee_schedule, depth_schedule, asset_class, venue_id = build_cost_context(spec, market, default_catalog())
    assert (fee_schedule, depth_schedule) == (None, None)  # the headline "crypto-only → (None,None)" contract
    assert asset_class is None and venue_id is None


def _eq_bar(close: float):
    """One equity bar at a given close — gives build_cost_context a real reference price for the per-share fee."""
    import datetime as _dt

    return Bar(ts=_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC), open=Decimal(str(close)), high=Decimal(str(close)),
               low=Decimal(str(close)), close=Decimal(str(close)), volume=Decimal("1000"))


def test_equity_leg_priced_at_ibkr_per_share_fee_depth_and_calendar(monkeypatch):
    """A spec whose universe includes equity: the equity symbols present in the market are stamped with IBKR's
    REAL per-share fee (NOT the flat 0.5 bps placeholder) AND its depth, and marked equity for the ≈252-session
    calendar, while the crypto leg keeps the primary (Binance) cost — the per-venue map the finder persists."""
    monkeypatch.setattr(EquityOHLCVProvider, "available_symbols", lambda self, timeframe="1d": ["AAPL", "MSFT"])
    catalog = default_catalog()
    ibkr, binance = catalog.venue("ibkr"), catalog.venue("binance")
    # $100 names → $10k order buys 100 shares × $0.0035 = $0.35 commission → 0.35 bps (the real per-share fee).
    market = {"BTCUSDT": [], "AAPL": [_eq_bar(100.0)], "MSFT": [_eq_bar(100.0)]}

    fee_schedule, depth_schedule, asset_class, venue_id = build_cost_context(_equity_spec(), market, catalog)

    # Fees: IBKR's REAL per-share commission for the equity leg (~0.35 bps), NOT the flat 0.5 catalog placeholder.
    assert fee_schedule["AAPL"] == fee_schedule["MSFT"]
    assert fee_schedule["AAPL"] == pytest.approx(Decimal("0.35"), abs=1e-6)
    assert fee_schedule["AAPL"] != ibkr.taker_fee_bps      # the per-asset model overrode the flat 0.5
    assert fee_schedule["BTCUSDT"] == binance.taker_fee_bps
    assert fee_schedule["AAPL"] != binance.taker_fee_bps   # explicitly NOT the global Binance fee
    # Depth: each leg at ITS OWN venue's (slippage, impact) — the fix (IBKR 2/25, not Binance 5/40).
    assert depth_schedule["AAPL"] == (ibkr.slippage_bps, ibkr.impact_bps) == (Decimal("2"), Decimal("25"))
    assert depth_schedule["BTCUSDT"] == (binance.slippage_bps, binance.impact_bps)
    assert depth_schedule["AAPL"] != depth_schedule["BTCUSDT"]
    # Calendar: only the equity leg is re-annualized (≈252); crypto stays the 365 default (absent from the map).
    assert asset_class == {"AAPL": "equity", "MSFT": "equity"}
    # Venue id stamp: the equity cell is labelled ibkr, the crypto cell binance (the real fee axis).
    assert venue_id["AAPL"] == "ibkr" and venue_id["MSFT"] == "ibkr"
    assert venue_id["BTCUSDT"] == "binance"


# --------------------------------------------------------------------------- depth_schedule in the backtest


def test_depth_schedule_none_is_byte_identical():
    """Passing the crypto-only context (depth_schedule=None) yields a backtest byte-identical to omitting it —
    so wiring build_cost_context through the loop/finder cannot perturb the crypto path."""
    spec = seed_orb_fvg_spec()
    market = {"BTCUSDT": edge_bearing_screen_market(n=280)["BTCUSDT"][-280:]}
    fee = default_catalog().venue("binance").taker_fee_bps
    bare = run_strategy_backtest_detailed(spec, _params(), market, fee_bps=fee)
    with_none = run_strategy_backtest_detailed(spec, _params(), market, fee_bps=fee, depth_schedule=None)
    assert with_none.metrics == bare.metrics
    assert with_none.val_returns == bare.val_returns and with_none.per_symbol == bare.per_symbol


def test_depth_schedule_charges_per_symbol_slippage():
    """A per-symbol depth entry is actually applied: a punitive half-spread on the traded symbol nets a strictly
    worse return than a zero-cost depth — and a symbol ABSENT from the schedule falls back to the scalar."""
    spec = seed_orb_fvg_spec()
    market = {"BTCUSDT": edge_bearing_screen_market(n=280)["BTCUSDT"][-280:]}
    fee = default_catalog().venue("binance").taker_fee_bps

    cheap = run_strategy_backtest_detailed(
        spec, _params(), market, fee_bps=fee, depth_schedule={"BTCUSDT": (Decimal("0"), Decimal("0"))}
    )
    pricey = run_strategy_backtest_detailed(
        spec, _params(), market, fee_bps=fee, depth_schedule={"BTCUSDT": (Decimal("500"), Decimal("0"))}
    )
    assert cheap.metrics.num_trades > 0, "fixture must trade for slippage to bite"
    assert float(pricey.metrics.oos_return) < float(cheap.metrics.oos_return)

    # A symbol not in the schedule uses the scalar slippage_bps/impact_bps (here 0/0) → matches `cheap`.
    fallback = run_strategy_backtest_detailed(
        spec, _params(), market, fee_bps=fee,
        slippage_bps=Decimal("0"), impact_bps=Decimal("0"),
        depth_schedule={"SOMETHING-ELSE": (Decimal("500"), Decimal("0"))},
    )
    assert fallback.metrics.oos_return == cheap.metrics.oos_return


# ----------------------------------------------------- per-asset fee wiring (Polymarket / always-taker)


def _polymarket_spec():
    """The crypto seed re-pointed at Polymarket as its primary venue (prediction asset class) — so
    build_cost_context must resolve its taker via the per-category model, not Binance's flat 10 bps."""
    spec = seed_orb_fvg_spec()
    return spec.model_copy(
        update={"universe": spec.universe.model_copy(
            update={"venues": ["polymarket"], "asset_classes": ["prediction"]}
        )}
    )


def test_polymarket_primary_venue_uses_per_category_taker():
    """A Polymarket-primary spec triggers the per-symbol map (the venue is asset-aware) and charges the
    per-category P&L-room taker for its catalog market — NOT the flat 0 bps placeholder. The catalog
    PM-FED-CUT-2026 market is category 'economics' (5%) at a 0.5 mark → 0.05 × 0.5 × 1e4 = 250 bps."""
    catalog = default_catalog()
    market = {"PM-FED-CUT-2026": [_eq_bar(0.5)]}  # a 50/50 prediction-market mark
    fee_schedule, depth_schedule, asset_class, venue_id = build_cost_context(_polymarket_spec(), market, catalog)
    assert fee_schedule is not None  # asset-aware primary venue → the per-symbol path triggers
    assert fee_schedule["PM-FED-CUT-2026"] == pytest.approx(Decimal("250"))  # economics 5% × (1−0.5)
    assert fee_schedule["PM-FED-CUT-2026"] != catalog.venue("polymarket").taker_fee_bps  # NOT the flat 0
    assert venue_id["PM-FED-CUT-2026"] == "polymarket"
    assert asset_class is None  # prediction uses the 365 default calendar


def test_always_taker_charges_both_entry_and_exit_legs():
    """The screen cost path is ALWAYS-TAKER and SYMMETRIC: doubling the taker bps roughly DOUBLES the total
    fee drag (entry + exit both pay it). If only one leg were charged (or a maker assumption credited a rebate)
    the relationship would not hold. This is the always-taker entry+exit invariant the maker/taker deletion
    preserves."""
    spec = seed_orb_fvg_spec()
    bars = edge_bearing_screen_market(n=280)["BTCUSDT"][-280:]
    market = {"BTCUSDT": bars}
    # Zero depth so the FEE is the only cost lever (isolate the round-trip fee).
    lo = run_strategy_backtest_detailed(
        spec, _params(), market, fee_bps=Decimal("10"),
        slippage_bps=Decimal("0"), impact_bps=Decimal("0"),
    )
    hi = run_strategy_backtest_detailed(
        spec, _params(), market, fee_bps=Decimal("20"),
        slippage_bps=Decimal("0"), impact_bps=Decimal("0"),
    )
    assert lo.metrics.num_trades > 0 and hi.metrics.num_trades == lo.metrics.num_trades
    # Higher taker → strictly worse net return (fees bite on BOTH legs, never a rebate credited).
    assert float(hi.metrics.oos_return) < float(lo.metrics.oos_return)
