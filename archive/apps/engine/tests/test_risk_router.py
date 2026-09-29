from decimal import Decimal

from cosmu.config.settings import RiskSettings, SpendSettings
from cosmu.lab.router import RouteRequest, route_model
from cosmu.master.risk import OrderIntent, validate_order
from cosmu.spine.venue import default_catalog


def test_risk_gauntlet_rejects_revenge_sizing_and_missing_exits():
    catalog = default_catalog()
    order = OrderIntent(
        symbol="BTCUSDT",
        side="buy",
        qty=Decimal("0.01"),
        price=Decimal("65000"),
        stop_loss=None,
        take_profit=None,
        conviction=Decimal("0.9"),
        sizing_basis="equity_vol_conviction",
    )
    decision = validate_order(order, catalog.venue("binance"), catalog.instrument("BTCUSDT"), RiskSettings())
    assert decision.accepted is False
    assert "missing_sl_tp" in decision.issues


def test_model_router_respects_daily_cap():
    decision = route_model(
        RouteRequest(task="author", difficulty="mid", estimated_cost=Decimal("10")),
        SpendSettings(daily_cap_usd=Decimal("5")),
        spent_today=Decimal("0"),
    )
    assert decision.accepted is False
    assert decision.reason == "daily_cap_exhausted"

