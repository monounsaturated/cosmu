# intent: P0.4 dynamic-fee engine — VenueFeesProvider, PIT read seam, cost_ratio metric,
# reconcile_fills fee-drift logging.  All tests offline (mock ccxt, no network).

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataStore, VenueFeesProvider, read_pit_fee
from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics
from cosmu.spine.venue import default_catalog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_days: int = 0) -> datetime:
    from datetime import timedelta
    return datetime(2024, 6, 1, tzinfo=UTC) + timedelta(days=offset_days)


def _store(tmp_path) -> AltDataStore:
    return AltDataStore(root=str(tmp_path / "altdata"))


# ---------------------------------------------------------------------------
# VenueFeesProvider — fallback ladder
# ---------------------------------------------------------------------------

class TestVenueFeesProvider:
    def test_offline_static_fallback_no_ccxt(self, tmp_path):
        """No ccxt client → returns static catalog fallback bps."""
        provider = VenueFeesProvider("binance")
        pts = provider.fetch_series("BTCUSDT", "venue_fees_taker", limit=1)
        assert len(pts) == 1
        assert pts[0].value == 10.0  # Binance default taker = 10 bps

    def test_offline_static_fallback_maker(self, tmp_path):
        provider = VenueFeesProvider("binance")
        pts = provider.fetch_series("BTCUSDT", "venue_fees_maker", limit=1)
        assert len(pts) == 1
        assert pts[0].value == 10.0  # Binance default maker = 10 bps

    def test_unknown_metric_returns_empty(self):
        provider = VenueFeesProvider("binance")
        pts = provider.fetch_series("BTCUSDT", "funding_rate", limit=1)
        assert pts == []

    def test_injected_fetcher_used_when_symbol_present(self):
        """The injected fetcher path (rung 1) is used and returns account-specific bps."""
        def mock_fetcher(exchange):
            return {"BTCUSDT": {"maker": 0.0006, "taker": 0.0010}}  # 6 / 10 bps

        provider = VenueFeesProvider("binance", ccxt_exchange=object(), _fetcher=mock_fetcher)
        pts_taker = provider.fetch_series("BTCUSDT", "venue_fees_taker", limit=1)
        pts_maker = provider.fetch_series("BTCUSDT", "venue_fees_maker", limit=1)
        assert pts_taker[0].value == pytest.approx(10.0)  # 0.0010 * 10000
        assert pts_maker[0].value == pytest.approx(6.0)   # 0.0006 * 10000

    def test_injected_fetcher_symbol_missing_falls_to_describe(self):
        """Symbol absent from fetchTradingFees → try describe()['fees']."""
        class MockExchange:
            def describe(self):
                return {"fees": {"trading": {"takerFee": 0.0009, "makerFee": 0.0007}}}

        def mock_fetcher(exchange):
            return {}  # symbol not present

        provider = VenueFeesProvider("binance", ccxt_exchange=MockExchange(), _fetcher=mock_fetcher)
        pts = provider.fetch_series("ETHUSDT", "venue_fees_taker", limit=1)
        assert pts[0].value == pytest.approx(9.0)  # 0.0009 * 10000

    def test_ccxt_fetchTradingFees_raises_falls_to_static(self):
        """ccxt error → graceful fallback to static catalog, never crashes."""
        class BrokenExchange:
            def fetchTradingFees(self):
                raise RuntimeError("rate limit")
            def describe(self):
                raise RuntimeError("also broken")

        provider = VenueFeesProvider("binance", ccxt_exchange=BrokenExchange())
        pts = provider.fetch_series("BTCUSDT", "venue_fees_taker", limit=1)
        # Falls through to static catalog: 10 bps for binance
        assert pts[0].value == 10.0

    def test_unknown_venue_returns_none_bps(self):
        """Venue not in static catalog and no ccxt → returns []."""
        provider = VenueFeesProvider("some_unknown_venue_xyz")
        pts = provider.fetch_series("BTCUSDT", "venue_fees_taker", limit=1)
        # No fallback entry → empty
        assert pts == []

    def test_available_at_equals_ts(self):
        """Fees are a live read — available_at == ts (no publication lag)."""
        provider = VenueFeesProvider("binance")
        pts = provider.fetch_series("BTCUSDT", "venue_fees_taker", limit=1)
        assert pts[0].available_at == pts[0].ts


# ---------------------------------------------------------------------------
# read_pit_fee — PIT seam
# ---------------------------------------------------------------------------

class TestReadPitFee:
    def test_reads_latest_point_before_as_of(self, tmp_path):
        store = _store(tmp_path)
        t0 = _ts(0)
        t1 = _ts(1)
        store.append("venue_fees", "binance:BTCUSDT", "venue_fees_taker", [
            AltDataPoint(ts=t0, available_at=t0, value=10.0),
        ])
        store.append("venue_fees", "binance:BTCUSDT", "venue_fees_taker", [
            AltDataPoint(ts=t1, available_at=t1, value=9.0),
        ])
        # Reading as-of t0 should see only 10.0 (t1 not yet available)
        val = read_pit_fee(store, "binance", "BTCUSDT", "venue_fees_taker", t0)
        assert val == pytest.approx(10.0)

    def test_reads_newer_point_when_available(self, tmp_path):
        store = _store(tmp_path)
        t0 = _ts(0)
        t1 = _ts(1)
        t2 = _ts(2)
        store.append("venue_fees", "binance:BTCUSDT", "venue_fees_taker", [
            AltDataPoint(ts=t0, available_at=t0, value=10.0),
            AltDataPoint(ts=t1, available_at=t1, value=9.5),
        ])
        # Reading as-of t2 should see 9.5 (most recent available)
        val = read_pit_fee(store, "binance", "BTCUSDT", "venue_fees_taker", t2)
        assert val == pytest.approx(9.5)

    def test_no_data_returns_fallback(self, tmp_path):
        store = _store(tmp_path)
        val = read_pit_fee(store, "binance", "BTCUSDT", "venue_fees_taker", _ts(0), fallback_bps=10.0)
        assert val == 10.0

    def test_no_data_no_fallback_returns_none(self, tmp_path):
        store = _store(tmp_path)
        val = read_pit_fee(store, "binance", "BTCUSDT", "venue_fees_taker", _ts(0))
        assert val is None

    def test_future_point_not_visible(self, tmp_path):
        """A fee snapshot stamped AFTER as_of must not be read (PIT guarantee)."""
        store = _store(tmp_path)
        future = _ts(5)
        store.append("venue_fees", "binance:BTCUSDT", "venue_fees_taker", [
            AltDataPoint(ts=future, available_at=future, value=7.0),
        ])
        val = read_pit_fee(store, "binance", "BTCUSDT", "venue_fees_taker", _ts(0), fallback_bps=10.0)
        assert val == 10.0  # future snapshot invisible, fallback used


# NOTE: the FeeSchedule.from_pit "costopt seam" was DELETED with cosmu/execution/costopt.py (dead maker/taker
# path, no live caller). The PIT read it wrapped is `read_pit_fee`, covered directly by TestReadPitFee above; the
# production order path (master/execution._pit_fee_for_order) calls read_pit_fee directly, not FeeSchedule.


# ---------------------------------------------------------------------------
# BacktestMetrics.cost_ratio field
# ---------------------------------------------------------------------------

class TestCostRatioField:
    def test_cost_ratio_present_and_zero_by_default(self):
        m = BacktestMetrics(
            oos_return=Decimal("0.05"),
            sharpe=Decimal("1.2"),
            sortino=Decimal("0"),
            max_drawdown=Decimal("0.10"),
            win_rate=Decimal("0.55"),
            num_trades=30,
        )
        assert m.cost_ratio == Decimal("0")

    def test_cost_ratio_set_correctly(self):
        m = BacktestMetrics(
            oos_return=Decimal("0.05"),
            sharpe=Decimal("1.2"),
            sortino=Decimal("0"),
            max_drawdown=Decimal("0.10"),
            win_rate=Decimal("0.55"),
            num_trades=30,
            cost_ratio=Decimal("0.75"),
        )
        assert m.cost_ratio == Decimal("0.75")


# ---------------------------------------------------------------------------
# reconcile_fills — fee-drift logging
# ---------------------------------------------------------------------------

class TestReconcileFillsFeeeDrift:
    def _setup_store(self, tmp_path) -> Store:
        return Store(Settings(database_url=f"sqlite:///{tmp_path}/recon.sqlite3"))

    def test_fee_drift_event_emitted_when_drift_exceeds_threshold(self, tmp_path):
        from datetime import timedelta
        from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
        from cosmu.config.settings import RiskSettings
        from cosmu.core.interfaces import Fill, OrderId
        from cosmu.master.execution import IntendedOrder, execute_orders, reconcile_fills
        from cosmu.master.portfolio import Portfolio

        store = self._setup_store(tmp_path)
        pf = Portfolio(store)
        catalog = default_catalog()

        # A mock ccxt that returns fills with a higher actual fee than predicted
        class MockCcxtDrift:
            def __init__(self):
                self._orders: dict[str, dict] = {}
                self.created: list = []

            def create_order(self, symbol, type, side, amount, price, params):  # noqa: A002
                coid = params.get("clientOrderId", "unknown")
                raw = {"id": f"v-{len(self.created)+1}", "clientOrderId": coid}
                self.created.append(raw)
                self._orders[coid] = raw
                return raw

            def fetch_order(self, id, symbol=None, params=None):  # noqa: A002
                # Return None so submit() proceeds to create_order (not idempotency short-circuit)
                raise ValueError("not found")

            def cancel_order(self, id, symbol=None, params=None):  # noqa: A002
                return {}

            def fetch_balance(self, params=None):
                return {"total": {"BTC": "0.1", "USDT": "10000"}}

            def fetch_my_trades(self, symbol=None, since=None, limit=None, params=None):
                # Actual fee is much higher than predicted (large drift).
                # Use the FIRST created order's coid (the main order; OCO is second).
                coid = list(self._orders.keys())[0] if self._orders else "unknown"
                return [{
                    "order": coid,
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "amount": "0.05",
                    "price": "65000",
                    "fee": {"cost": "10.00", "currency": "USDT"},  # ~30 bps on 0.05 * 65000 = 3250
                    "takerOrMaker": "taker",
                    "timestamp": 1_700_000_000_000,
                }]

        mock = MockCcxtDrift()
        adapter = BinanceSpotExecutionAdapter(client=mock, mode="live")

        intent = IntendedOrder(
            strategy_version_id="sv-drift",
            symbol="BTCUSDT",
            venue_id="binance",
            side=1,
            qty=Decimal("0.05"),
            price=Decimal("65000"),
            stop_loss=Decimal("60000"),
            take_profit=Decimal("72000"),
            conviction=Decimal("0.6"),
            gate_passed=True,
            order_type="market",
            client_order_id="cosmu-drift-test",
        )

        execute_orders(
            [intent],
            live_enabled=True,
            kill_switch=False,
            adapter=adapter,
            store=store,
            portfolio=pf,
            risk=RiskSettings(),
            catalog=catalog,
        )

        events = reconcile_fills(
            adapter, store, pf,
            since=datetime(2024, 1, 1, tzinfo=UTC),
            fee_drift_alert_bps=2.0,
        )
        assert len(events) >= 1
        assert "fee_drift_bps" in events[0]
        assert "predicted_fee" in events[0]

        # fee_model_drift event should be emitted (drift is large: ~30 bps >> 2 bps threshold)
        drift_events = store.rows("SELECT * FROM events WHERE kind = 'fee_model_drift'")
        assert len(drift_events) >= 1

    def test_no_fee_model_drift_event_when_within_threshold(self, tmp_path):
        """When fee drift is tiny, no fee_model_drift alert event should be emitted."""
        from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
        from cosmu.config.settings import RiskSettings
        from cosmu.master.execution import IntendedOrder, execute_orders, reconcile_fills
        from cosmu.master.portfolio import Portfolio

        store = self._setup_store(tmp_path)
        pf = Portfolio(store)
        catalog = default_catalog()

        class MockCcxtNoDrift:
            def __init__(self):
                self._orders: dict[str, dict] = {}
                self.created: list = []

            def create_order(self, symbol, type, side, amount, price, params):  # noqa: A002
                coid = params.get("clientOrderId", "nodrift")
                raw = {"id": f"v-{len(self.created)+1}", "clientOrderId": coid}
                self.created.append(raw)
                self._orders[coid] = raw
                return raw

            def fetch_order(self, id, symbol=None, params=None):  # noqa: A002
                raise ValueError("not found")

            def cancel_order(self, id, symbol=None, params=None):  # noqa: A002
                return {}

            def fetch_balance(self, params=None):
                return {"total": {"BTC": "0.1", "USDT": "10000"}}

            def fetch_my_trades(self, symbol=None, since=None, limit=None, params=None):
                # Fee matches predicted exactly (10 bps on 0.05*65000=3250 notional → 3.25 USDT)
                # → zero drift, no alert
                coid = list(self._orders.keys())[0] if self._orders else "unknown"
                return [{
                    "order": coid,
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "amount": "0.05",
                    "price": "65000",
                    "fee": {"cost": "3.25", "currency": "USDT"},  # exactly 10 bps → 0 drift
                    "takerOrMaker": "taker",
                    "timestamp": 1_700_000_000_000,
                }]

        mock = MockCcxtNoDrift()
        adapter = BinanceSpotExecutionAdapter(client=mock, mode="live")

        intent = IntendedOrder(
            strategy_version_id="sv-nodrift",
            symbol="BTCUSDT",
            venue_id="binance",
            side=1,
            qty=Decimal("0.05"),
            price=Decimal("65000"),
            stop_loss=Decimal("60000"),
            take_profit=Decimal("72000"),
            conviction=Decimal("0.6"),
            gate_passed=True,
            order_type="market",
            client_order_id="cosmu-nodrift-test",
        )

        execute_orders(
            [intent],
            live_enabled=True,
            kill_switch=False,
            adapter=adapter,
            store=store,
            portfolio=pf,
            risk=RiskSettings(),
            catalog=catalog,
        )

        events = reconcile_fills(
            adapter, store, pf,
            since=datetime(2024, 1, 1, tzinfo=UTC),
            fee_drift_alert_bps=2.0,
        )
        assert len(events) >= 1
        drift_events = store.rows("SELECT * FROM events WHERE kind = 'fee_model_drift'")
        assert len(drift_events) == 0


# ---------------------------------------------------------------------------
# ingest/run.py — _ingest_venue_fees helper
# ---------------------------------------------------------------------------

class TestIngestVenueFees:
    def test_venue_fees_ingested_into_store(self, tmp_path):
        """_ingest_venue_fees appends maker + taker rows per symbol into the alt_data store."""
        from datetime import timedelta
        from cosmu.ingest.run import _ingest_venue_fees

        store = _store(tmp_path)
        provider = VenueFeesProvider("binance")  # uses static fallback

        count = _ingest_venue_fees(store, provider, ["BTCUSDT", "ETHUSDT"])
        # 2 symbols × 2 metrics = 4 rows
        assert count == 4

        # Verify the stored rows are PIT-readable.
        # Use a far-future as_of so the snapshot (stamped now) is visible.
        t_future = datetime.now(tz=UTC) + timedelta(days=1)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            taker = read_pit_fee(store, "binance", symbol, "venue_fees_taker", t_future)
            maker = read_pit_fee(store, "binance", symbol, "venue_fees_maker", t_future)
            assert taker == pytest.approx(10.0)
            assert maker == pytest.approx(10.0)

    def test_venue_fees_provider_in_providers_dataclass(self):
        """Providers dataclass has a venue_fees field wired to VenueFeesProvider by default."""
        from cosmu.ingest.run import Providers

        p = Providers()
        assert hasattr(p, "venue_fees")
        assert isinstance(p.venue_fees, VenueFeesProvider)
