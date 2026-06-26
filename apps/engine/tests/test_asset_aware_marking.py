# ASSET-AWARE paper clock (orchestrator.mark_tracks): every held SIM position is re-marked against the
# REAL close from the pricing source for ITS asset class — crypto → Binance spot, equity/ETF → Yahoo total-return.
# Before this, the clock priced everything via Binance, so equity tracks (GEM dual-momentum, the TAA fleet) marked
# to 0 / sat flat. These tests prove the router sends each leg to the right provider, marks BOTH, and SKIPS (never
# synthetic/zero-fills) a genuinely unavailable equity close. Fully offline + deterministic: injected providers only.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio
from cosmu.orchestrator.loop import PricingRouter, mark_tracks
from cosmu.spine.venue import default_catalog


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/asset_aware.sqlite3"))


class _FakeProvider:
    """Returns one fixed close per symbol; an unknown symbol returns NO bars (offline/gap) so the router must
    skip it (no synthetic fill). Records which symbols it was asked for — the test asserts the router routed
    crypto vs equity to the right provider, not just that a price came back."""

    def __init__(self, closes: dict[str, float]) -> None:
        self._closes = closes
        self.asked: list[str] = []

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        self.asked.append(symbol)
        if symbol not in self._closes:
            return []
        c = Decimal(str(self._closes[symbol]))
        return [Bar(ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), open=c, high=c, low=c, close=c, volume=Decimal("0"))]


def _open(pf: Portfolio, *, vid: str, instrument_id: str, symbol: str, venue: str, qty: Decimal, price: Decimal) -> None:
    pf.apply_fill(
        instrument_id=instrument_id, symbol=symbol, venue=venue, side=1, qty=qty, price=price,
        fee=Decimal("0"), strategy_version_id=vid,
    )


def test_equity_position_marked_via_equity_provider_not_binance(tmp_path):
    """An ETF track (SPY@ibkr) is priced via the EQUITY provider — its return_pct moves off the entry, and the
    crypto provider is NEVER asked for an equity symbol (the old bug: SPY routed to Binance → 0 / flat)."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # GEM-style held equity leg: entered at 400, latest real close is 440 → +10% on the leg.
    _open(pf, vid="gem", instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", qty=Decimal("25"), price=Decimal("400"))

    crypto = _FakeProvider({"BTCUSDT": 30000.0})
    equity = _FakeProvider({"SPY": 440.0})
    router = PricingRouter(default_catalog(), crypto=crypto, equity=equity)
    snap = mark_tracks(store, router=router)

    assert "SPY" in equity.asked          # routed to the equity (Yahoo) source
    assert "SPY" not in crypto.asked      # the old bug would have priced SPY via Binance
    # equity = 25 * 440 = 11000 vs entry value 25 * 400 = 10000 → the equity leg accrued, not flat at 0.
    assert float(snap["equity"]) > float(store.settings.sim_bankroll)
    pv = pf.position("spy-ibkr", "ibkr", strategy_version_id="gem")
    assert pv is not None and pv.unrealized_pnl(Decimal("440")) == Decimal("1000")


def test_crypto_and_equity_tracks_both_marked_in_one_run(tmp_path):
    """A mixed book (crypto BTC@binance + equity SPY@ibkr) marks BOTH legs in a single clock run, each via its
    own asset-class source."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
    _open(pf, vid="btc", instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="binance", qty=Decimal("1"), price=Decimal("30000"))
    _open(pf, vid="gem", instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", qty=Decimal("25"), price=Decimal("400"))

    crypto = _FakeProvider({"BTCUSDT": 33000.0})
    equity = _FakeProvider({"SPY": 440.0})
    mark_tracks(store, router=PricingRouter(default_catalog(), crypto=crypto, equity=equity))

    assert crypto.asked == ["BTCUSDT"]    # crypto leg → Binance
    assert equity.asked == ["SPY"]        # equity leg → Yahoo
    # both legs are in the latest snapshot: +3000 (BTC) + +1000 (SPY) over a 100000 bankroll.
    snap = store.row("SELECT equity FROM portfolio_snapshots ORDER BY ts DESC LIMIT 1")
    assert Decimal(str(snap["equity"])) == store.settings.sim_bankroll + Decimal("4000")


def test_unavailable_equity_close_is_skipped_not_zero_filled(tmp_path):
    """A genuinely unavailable equity close (provider returns no bars) is SKIPPED — the position stays at its last
    basis, never marked to 0. No crash, no synthetic fill."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
    _open(pf, vid="gem", instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", qty=Decimal("25"), price=Decimal("400"))

    crypto = _FakeProvider({})
    equity = _FakeProvider({})  # offline: no close for SPY
    snap = mark_tracks(store, router=PricingRouter(default_catalog(), crypto=crypto, equity=equity))

    assert equity.asked == ["SPY"]  # it tried the equity source
    # No fresh mark → the position falls back to its avg_price basis (25 * 400 = 10000), NOT 0. Equity is flat at
    # bankroll (the held leg's basis exactly offsets the cash it consumed), proving no zero-fill wiped it out.
    assert float(snap["equity"]) == float(store.settings.sim_bankroll)


def test_equity_track_return_pct_updates_off_zero(tmp_path):
    """The clock drives tracks.return_pct off the LIVE marked equity (generalizing the per-arm GEM mark to every
    asset class). A flat equity track at return_pct=0 starts accruing the real close — the exact symptom this fix
    targets: equity tracks no longer sit flat."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # Register the track row the leaderboard/live_eligibility read, seeded flat at 0 like the prod equity tracks.
    sv = store.insert("strategies", {"name": "TAA fleet track", "thesis": "x", "origin": "documented", "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()})
    vid = store.insert(
        "strategy_versions",
        {"strategy_id": sv, "parent_id": None, "spec": {}, "generated_code": "", "code_hash": "taa-x",
         "params": {}, "mutation_operator": None, "mutation_rationale": "x", "origin": "documented",
         "status": "paper", "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat(),
         "killed_at": None, "kill_reason": None},
    )
    store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "10000",
                            "equity": "10000.00", "return_pct": "0.00", "updated_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()})
    _open(pf, vid=vid, instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", qty=Decimal("25"), price=Decimal("400"))  # 10000 deployed

    equity = _FakeProvider({"SPY": 440.0})  # +10% on the held leg
    mark_tracks(store, router=PricingRouter(default_catalog(), crypto=_FakeProvider({}), equity=equity))

    row = store.row("SELECT return_pct, equity FROM tracks WHERE strategy_version_id = ?", (vid,))
    # marked track value = 25 * 440 = 11000 vs starting_capital 10000 → +10.00%, no longer flat at 0.
    assert Decimal(str(row["return_pct"])) == Decimal("10.00")
    assert Decimal(str(row["equity"])) == Decimal("11000.00")


def test_versionwide_multileg_arm_track_marks_whole_book_not_one_leg(tmp_path):
    """REGRESSION (prod 2026-06-26): a LEGACY version-wide arm track (tracks.symbol/venue NULL — the documented
    multi-leg rotators DAA/PAA/TSMOM/GTAA/RiskParity/Sector) holds N legs across N symbols. The cell resolver
    re-keys each leg to its OWN cell snapshot, but with no per-cell tracks row to anchor it each cell snapshot was
    marked to that ONE leg's notional (~capital/N) instead of the whole book — so _update_track_returns read a
    single fragment as the track equity (DAA $1000 → ~$169 = $1000/6, a phantom -83% forward loss). The fix:
    a position only adopts the cell key when a real per-cell track owns it; a version-wide track aggregates ALL
    its legs on the version key. Here 3 equal legs flat at entry must mark the track to its full $1000, not ~$333."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
    sv = store.insert("strategies", {"name": "DAA-like multi-leg", "thesis": "x", "origin": "documented",
                                     "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()})
    vid = store.insert(
        "strategy_versions",
        {"strategy_id": sv, "parent_id": None, "spec": {}, "generated_code": "", "code_hash": "daa-x",
         "params": {}, "mutation_operator": None, "mutation_rationale": "x", "origin": "documented",
         "status": "paper", "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat(),
         "killed_at": None, "kill_reason": None},
    )
    # The legacy VERSION-WIDE track row: symbol/venue NULL (exactly the prod multi-leg arm rows). $1000 capital.
    store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "1000", "equity": "1000.00",
                            "return_pct": "0.00", "updated_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()})
    # Three equal equity legs, ~1/3 of capital each, opened at real basis (the DAA defensive book shape).
    _open(pf, vid=vid, instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", qty=Decimal("0.5"), price=Decimal("666.67"))
    _open(pf, vid=vid, instrument_id="agg-ibkr", symbol="AGG", venue="ibkr", qty=Decimal("3.4"), price=Decimal("98.04"))
    _open(pf, vid=vid, instrument_id="lqd-ibkr", symbol="LQD", venue="ibkr", qty=Decimal("3.08"), price=Decimal("108.23"))

    # Flat: latest close == entry for every leg → the honest track value is exactly its $1000 capital.
    equity = _FakeProvider({"SPY": 666.67, "AGG": 98.04, "LQD": 108.23})
    mark_tracks(store, router=PricingRouter(default_catalog(), crypto=_FakeProvider({}), equity=equity))

    row = store.row("SELECT return_pct, equity FROM tracks WHERE strategy_version_id = ?", (vid,))
    # The bug wrote ~$333 (one leg's notional) and ~-67%. The fix marks the WHOLE book: flat at $1000, 0.00%.
    assert Decimal(str(row["equity"])) == Decimal("1000.00"), f"version-wide multi-leg track equity={row['equity']} (want 1000.00 — a single-leg fragment is the bug)"
    assert Decimal(str(row["return_pct"])) == Decimal("0.00")


def test_router_resolves_asset_class_for_equity_and_crypto():
    """The router picks the equity provider for an ETF instrument and the crypto provider for a Binance symbol,
    looked up by (symbol, venue) in the catalog — no hardcoded per-symbol routing."""
    crypto = _FakeProvider({})
    equity = _FakeProvider({})
    router = PricingRouter(default_catalog(), crypto=crypto, equity=equity)
    assert router.provider_for("SPY", "ibkr") is equity
    assert router.provider_for("EFA", "ibkr") is equity
    assert router.provider_for("BTCUSDT", "binance") is crypto
    # unknown instrument falls back to the venue kind (ibkr is an equity venue) — never crashes.
    assert router.provider_for("NVDA", "ibkr") is equity


def test_order_path_equity_position_routes_by_instrument_not_ledger_venue(tmp_path):
    """REGRESSION: positions opened through the ONE order path persist venue='sim' (a fill-ledger label, not a
    catalog venue). The clock must route by the INSTRUMENT's real venue — an equity survivor funded by the
    funder (spy-ibkr @ venue='sim') previously fell through to the crypto leg and never marked."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # Exactly what fund_tracks_from_survivors leaves behind for an equity survivor: real instrument, venue='sim'.
    _open(pf, vid="eq", instrument_id="spy-ibkr", symbol="SPY", venue="sim", qty=Decimal("2.5"), price=Decimal("400"))

    crypto = _FakeProvider({})            # crypto leg knows nothing — routing there would skip the mark
    equity = _FakeProvider({"SPY": 440.0})
    snap = mark_tracks(store, router=PricingRouter(default_catalog(), crypto=crypto, equity=equity))

    assert "SPY" in equity.asked and "SPY" not in crypto.asked
    assert float(snap["equity"]) > float(store.settings.sim_bankroll)  # the leg accrued (+10%), not flat
