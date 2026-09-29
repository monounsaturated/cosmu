# REAL LIVE-EXIT routing (api/routers/live.py): /live/liquidate (and /live/defund) must ROUTE a reduce_only
# liquidation through the exec adapter for every open leg BEFORE the SQL-zero bookkeeping — so a LIVE position
# is genuinely closed on the venue (a real reduce-only order on an ARMED venue), and a sim/unarmed leg sim-closes
# through the same managed path. Idempotent: a second call with nothing open routes nothing. Offline (fake
# adapter, no network); follows the test_live_ignition fake-adapter pattern.

from __future__ import annotations

from decimal import Decimal

import cosmu.api.routers.live as live_mod
import cosmu.orchestrator.paper_step as ps
from cosmu.api.models import DefundRequest, LiquidateRequest
from cosmu.config.settings import Settings
from cosmu.core.interfaces import AssetClass, OrderId
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio


class _FakeLiveAdapter:
    """An ACTIVE execution adapter (no keys, no network) capturing the venue orders it is asked to submit."""

    asset_class = AssetClass.CRYPTO

    def __init__(self, venue="binance", mode="live"):
        self.venue = venue
        self.mode = mode
        self.submitted: list = []

    @property
    def active(self) -> bool:
        return True

    def submit(self, order):
        self.submitted.append(order)
        return OrderId(venue=self.venue, client_order_id=order.client_order_id, venue_order_id="VEN-1")

    def cancel(self, order_id):  # pragma: no cover
        pass

    def positions(self):
        return []

    def fills(self, since):
        return []


def _store(tmp_path) -> Store:
    # _env_file=None → hermetic: the "unarmed" path must not inherit the dev box's real venue keys (else a live
    # adapter would resolve and the sim-close assertion would flip).
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/liq.sqlite3", openrouter_api_key=None, _env_file=None))


def _wire(monkeypatch, store: Store) -> None:
    """Point the live router's module-level store/settings + portfolio at our temp store."""
    monkeypatch.setattr(live_mod, "store", store)
    monkeypatch.setattr(live_mod, "settings", store.settings)
    monkeypatch.setattr(live_mod, "_portfolio", lambda: Portfolio(store, bankroll=store.settings.sim_bankroll))


def _open_position(store: Store, *, vid: str, book: str) -> None:
    """Seed ONE open long leg on the given book (sim / live / testnet) — BTCUSDT@binance, qty 0.1. Uses the REAL
    catalog instrument id so the order path's position lookup (keyed on instrument.id) matches the seeded row,
    exactly as a real funded position is keyed."""
    from cosmu.spine.venue import default_catalog

    instrument_id = default_catalog().instrument("BTCUSDT", "binance").id
    store.insert(
        "positions",
        {
            "strategy_version_id": vid, "instrument_id": instrument_id, "symbol": "BTCUSDT",
            "venue": book, "qty": "0.1", "avg_price": "30000", "realized_pnl": "0",
            "last_was_loss": 0, "updated_at": utcnow(),
        },
    )


def _qty(store: Store, vid: str) -> Decimal:
    row = store.row("SELECT qty FROM positions WHERE strategy_version_id = ?", (vid,))
    return Decimal(str(row["qty"])) if row else Decimal("0")


def test_liquidate_routes_reduce_only_to_armed_adapter(tmp_path, monkeypatch):
    """A LIVE leg on an ARMED venue routes a REAL reduce-only sell to the exec adapter, then the book is flat."""
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _open_position(store, vid="v-live", book="live")

    fake = _FakeLiveAdapter(venue="binance", mode="live")
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {"binance": fake})

    resp = live_mod.live_liquidate(LiquidateRequest(scope="all"))

    assert resp.ok and resp.routed == 1 and resp.closed == 1
    assert len(fake.submitted) == 1
    order = fake.submitted[0]
    assert order.reduce_only is True       # the venue order is genuinely reduce-only
    assert order.side == -1                 # opposite side of the long → a close
    assert float(order.qty) == 0.1          # the full held quantity
    assert _qty(store, "v-live") == 0       # book flat after liquidation + SQL-zero backstop
    # Audited as a real live submit on the ledger.
    assert store.row("SELECT id FROM events WHERE kind = 'order_submitted_live'") is not None
    assert store.row("SELECT id FROM events WHERE kind = 'live_liquidated'") is not None


def test_liquidate_sim_closes_when_unarmed(tmp_path, monkeypatch):
    """No armed adapter → a sim/paper leg sim-closes through the managed path (NO venue order), book flat.
    This is the degrade-to-today's-behaviour path the live-exit hole used to leave open."""
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _open_position(store, vid="v-sim", book="sim")
    # No monkeypatch of _resolve_live_adapters: the (off) live_toggle yields {} → nothing armed.

    resp = live_mod.live_liquidate(LiquidateRequest(scope="all"))

    assert resp.ok and resp.routed == 1 and resp.closed == 1
    assert _qty(store, "v-sim") == 0  # flattened
    # A sim-close is NOT a live submit — nothing routed to a venue.
    assert store.row("SELECT id FROM events WHERE kind = 'order_submitted_live'") is None
    # It went through the ONE order path as a paper fill (is_paper=1), a real reduce-only close booked in the ledger.
    sell = store.row("SELECT is_paper FROM executions WHERE side = 'sell' AND strategy_version_id = ?", ("v-sim",))
    assert sell is not None and int(sell["is_paper"]) == 1


def test_liquidate_is_idempotent(tmp_path, monkeypatch):
    """A second liquidate with nothing open routes nothing (idempotent) — no double exit, no phantom order."""
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _open_position(store, vid="v-sim", book="sim")

    first = live_mod.live_liquidate(LiquidateRequest(scope="all"))
    assert first.routed == 1 and _qty(store, "v-sim") == 0

    second = live_mod.live_liquidate(LiquidateRequest(scope="all"))
    assert second.routed == 0 and second.closed == 0  # nothing open → no-op


def test_liquidate_per_strategy_scope_only_targets_that_version(tmp_path, monkeypatch):
    """scope='strategy' liquidates ONLY the target version; a sibling open leg is untouched."""
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _open_position(store, vid="v-target", book="sim")
    _open_position(store, vid="v-other", book="sim")

    resp = live_mod.live_liquidate(LiquidateRequest(scope="strategy", version_id="v-target"))

    assert resp.routed == 1 and resp.version_ids == ["v-target"]
    assert _qty(store, "v-target") == 0       # closed
    assert _qty(store, "v-other") == Decimal("0.1")  # the sibling is left alone


def test_defund_now_liquidates_before_zeroing(tmp_path, monkeypatch):
    """/live/defund must ROUTE a reduce_only exit (real order on an armed venue) BEFORE the SQL-zero — the
    capital-safety fix: defund used to zero the row and sell nothing. The response reports legs liquidated."""
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _open_position(store, vid="v-live", book="live")

    fake = _FakeLiveAdapter(venue="binance", mode="live")
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {"binance": fake})

    resp = live_mod.live_defund(DefundRequest(scope="all"))

    assert resp.ok and resp.liquidated == 1
    assert resp.defunded == ["v-live"]
    assert len(fake.submitted) == 1 and fake.submitted[0].reduce_only is True and fake.submitted[0].side == -1
    assert _qty(store, "v-live") == 0


def test_defund_unarmed_still_degrades_to_sql_zero(tmp_path, monkeypatch):
    """No armed venue → defund sim-closes the leg through the managed path and zeroes the book (the old behaviour
    is preserved, now WITH a real managed close instead of a silent row-zero)."""
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _open_position(store, vid="v-sim", book="sim")

    resp = live_mod.live_defund(DefundRequest(scope="all"))

    assert resp.ok and resp.liquidated == 1 and resp.defunded == ["v-sim"]
    assert _qty(store, "v-sim") == 0
    assert store.row("SELECT id FROM events WHERE kind = 'order_submitted_live'") is None  # nothing routed live
