# intent: lock the PAPER-lane fee parity with the backtest/screen cost path (the money-honesty fix). Paper is the
# gate that funds live, so a Polymarket / IBKR paper order MUST charge the SAME per-venue, asset-aware,
# pinned-to-today fee the backtest charged — not the flat 0-bps (Polymarket) / 0.5-bps (IBKR) placeholder the order
# path used before. Covers: (1) the shared effective_taker_bps resolver returns the asset-aware override for
# Polymarket/IBKR and None for crypto (byte-identical crypto); (2) _pit_fee_for_order charges the override for
# Polymarket (per-category×(1−price)) and IBKR (per-share), the catalog/PIT bps for crypto; (3) an end-to-end paper
# execute_orders books the parity fee on the executions row. INVARIANT under test: the change only EQUAL-or-RAISES a
# non-crypto fee, never lowers crypto, never the Gate.

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cosmu.config.settings import RiskSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.execution import IntendedOrder, _pit_fee_for_order, execute_orders
from cosmu.master.portfolio import Portfolio
from cosmu.spine.asset_fees import (
    asset_taker_bps,
    effective_taker_bps,
    ibkr_taker_bps,
    polymarket_taker_bps,
)
from cosmu.spine.venue import Instrument, default_catalog


def _store() -> Store:
    tmp = tempfile.mkdtemp()
    return Store(Settings(database_url=f"sqlite:///{tmp}/parity.sqlite3"))


# ---------------------------------------------------------------------------
# 1. The shared resolver — effective_taker_bps
# ---------------------------------------------------------------------------

class TestEffectiveTakerBpsResolver:
    def test_crypto_returns_none_byte_identical(self):
        """Plain spot/perp venue → None: the caller keeps its flat/PIT bps (crypto fee never changes)."""
        catalog = default_catalog()
        binance = catalog.venue("binance")
        instr = catalog.instrument("BTCUSDT", "binance")
        assert effective_taker_bps(binance, instr, reference_price=65000.0) is None
        # Even with no instrument, crypto stays None.
        assert effective_taker_bps(binance, None, reference_price=65000.0) is None

    def test_polymarket_override_matches_asset_taker_bps(self):
        """Polymarket → the per-category×(1−price) override (NOT None, NOT the flat ~0 placeholder)."""
        catalog = default_catalog()
        poly = catalog.venue("polymarket")
        instr = catalog.instrument("PM-FED-CUT-2026", "polymarket")  # category="economics" → 5%
        price = 0.40
        got = effective_taker_bps(poly, instr, reference_price=price)
        assert got is not None
        # 5% × (1 − 0.40) × 1e4 = 300 bps.
        assert got == asset_taker_bps(poly, instr, reference_price=price)
        assert got == polymarket_taker_bps("economics", price)
        assert got == pytest.approx(Decimal("300"))
        assert got > Decimal("0")  # the gap this fix closes: was ≈0 in paper

    def test_ibkr_override_matches_asset_taker_bps(self):
        """IBKR equity → the REAL per-share commission override (the bps the backtest charged), NOT the flat 0.5
        placeholder. The override is evaluated at the same $10k reference notional the screen uses, so paper ==
        backtest by construction. At a low share price the per-share + min-order floor pushes it ABOVE 0.5 bps."""
        catalog = default_catalog()
        ibkr = catalog.venue("ibkr")
        instr = catalog.instrument("SPY", "ibkr")  # us_equity
        price = 50.0  # low price → 200 shares per $10k leg → $0.70 commission → 0.7 bps (> the 0.5 placeholder)
        got = effective_taker_bps(ibkr, instr, reference_price=price)
        assert got is not None
        # PARITY: identical to the resolver the backtest cost path uses (build_cost_context → asset_taker_bps).
        assert got == asset_taker_bps(ibkr, instr, reference_price=price)
        assert got == ibkr_taker_bps(instr, price)
        assert got == pytest.approx(Decimal("0.7"))
        assert got > ibkr.taker_fee_bps  # 0.7 > 0.5 flat → tightened (honest)


# ---------------------------------------------------------------------------
# 2. _pit_fee_for_order — the paper-lane fee chokepoint
# ---------------------------------------------------------------------------

class TestPitFeeForOrderParity:
    def test_polymarket_paper_fee_matches_backtest_not_zero(self):
        """A Polymarket paper order pays the per-category×(1−price) fee, matching the backtest (not ≈0)."""
        store = _store()
        catalog = default_catalog()
        poly = catalog.venue("polymarket")
        instr = catalog.instrument("PM-FED-CUT-2026", "polymarket")
        qty = Decimal("1000")
        price = Decimal("0.40")
        fee = _pit_fee_for_order(store, poly, "PM-FED-CUT-2026", qty, price, instrument=instr)
        # Backtest charge: notional × (feeRate × (1−price)). notional = 1000 × 0.40 = 400.
        # bps = 5% × 0.60 × 1e4 = 300 → fraction 0.03 → fee = 400 × 0.03 = 12.0.
        expected = qty * price * (polymarket_taker_bps("economics", float(price)) / Decimal("10000"))
        assert fee == expected
        assert fee == pytest.approx(Decimal("12.0"))
        # The OLD flat-catalog behaviour would have charged poly.taker_fee_bps (≈0) → assert we beat it.
        flat = qty * price * (poly.taker_fee_bps / Decimal("10000"))
        assert fee > flat  # tightened, never loosened

    def test_ibkr_paper_fee_matches_backtest_not_flat(self):
        """An IBKR equity paper order pays the REAL per-share fee the backtest charged (not the flat 0.5 bps). At a
        low price the per-share + min-order floor makes it strictly ABOVE the 0.5 placeholder (tightened)."""
        store = _store()
        catalog = default_catalog()
        ibkr = catalog.venue("ibkr")
        instr = catalog.instrument("SPY", "ibkr")
        price = Decimal("50")
        qty = Decimal("200")  # $10k notional
        fee = _pit_fee_for_order(store, ibkr, "SPY", qty, price, instrument=instr)
        # PARITY: the backtest charges notional × ibkr_taker_bps (evaluated at the $10k reference notional).
        expected = qty * price * (ibkr_taker_bps(instr, float(price)) / Decimal("10000"))
        assert fee == expected
        # 200 shares × $0.0035 = $0.70 commission on $10k → 0.7 bps.
        assert fee == pytest.approx(Decimal("0.70"))
        flat = qty * price * (ibkr.taker_fee_bps / Decimal("10000"))  # 0.5 bps → $0.50
        assert fee > flat  # tightened, never loosened

    def test_crypto_paper_fee_unchanged_catalog_fallback(self):
        """A crypto spot paper order is UNCHANGED: flat catalog taker (no PIT snapshot) — byte-identical."""
        store = _store()
        catalog = default_catalog()
        binance = catalog.venue("binance")
        instr = catalog.instrument("BTCUSDT", "binance")
        qty = Decimal("0.1")
        price = Decimal("65000")
        fee = _pit_fee_for_order(store, binance, "BTCUSDT", qty, price, instrument=instr)
        # No PIT snapshot in this fresh store → catalog flat (Binance 10 bps).
        expected = qty * price * (binance.taker_fee_bps / Decimal("10000"))
        assert fee == expected
        # And identical whether or not we pass the instrument (crypto path ignores the override).
        assert fee == _pit_fee_for_order(store, binance, "BTCUSDT", qty, price, instrument=None)

    def test_crypto_paper_fee_uses_pit_snapshot_unchanged(self):
        """Crypto with a PIT fee snapshot still reads the snapshot (override is None for crypto)."""
        from cosmu.data.altdata import AltDataPoint, PgAltDataStore

        store = _store()
        catalog = default_catalog()
        binance = catalog.venue("binance")
        instr = catalog.instrument("BTCUSDT", "binance")
        # Seed a PIT taker snapshot of 6 bps (a VIP-tier discount), available now.
        alt = PgAltDataStore(store)
        now = datetime.now(tz=UTC)
        alt.append("venue_fees", "binance:BTCUSDT", "venue_fees_taker", [AltDataPoint(ts=now, available_at=now, value=6.0)])
        qty = Decimal("0.1")
        price = Decimal("65000")
        fee = _pit_fee_for_order(store, binance, "BTCUSDT", qty, price, instrument=instr)
        expected = qty * price * (Decimal("6.0") / Decimal("10000"))
        assert fee == expected  # snapshot, not catalog 10 bps — crypto behaviour preserved


# ---------------------------------------------------------------------------
# 3. End-to-end paper execute_orders books the parity fee
# ---------------------------------------------------------------------------

class TestPaperExecutionBooksParityFee:
    def _run_paper(self, store, catalog, intent) -> Decimal:
        pf = Portfolio(store)
        execute_orders(
            [intent],
            live_enabled=False,  # PAPER lane — the gate that funds
            kill_switch=False,
            adapter=None,
            store=store,
            portfolio=pf,
            risk=RiskSettings(),
            catalog=catalog,
        )
        row = store.row("SELECT fee, is_paper FROM executions ORDER BY id DESC LIMIT 1")
        assert row is not None
        assert int(row["is_paper"]) == 1
        return Decimal(str(row["fee"]))

    def test_polymarket_paper_execution_charges_category_fee(self):
        store = _store()
        catalog = default_catalog()
        intent = IntendedOrder(
            strategy_version_id="sv-poly",
            symbol="PM-FED-CUT-2026",
            venue_id="polymarket",
            side=1,
            qty=Decimal("1000"),
            price=Decimal("0.40"),
            stop_loss=Decimal("0.30"),   # entries require brackets (the gauntlet); a close fires the bracket
            take_profit=Decimal("0.60"),
            conviction=Decimal("0.6"),
            gate_passed=True,
            order_type="limit",
            client_order_id="parity-poly",
        )
        fee = self._run_paper(store, catalog, intent)
        # The paper fill crosses the half-spread, so the fee is on the FILLED notional. Assert it is materially
        # above the OLD flat-0-bps placeholder (the gap) and on the per-category order of magnitude.
        poly = catalog.venue("polymarket")
        flat = Decimal("1000") * Decimal("0.40") * (poly.taker_fee_bps / Decimal("10000"))
        assert fee > flat
        assert fee > Decimal("5")  # ~12 on a $400 notional at 300 bps — far from ≈0

    def test_ibkr_paper_execution_charges_per_share_fee(self):
        store = _store()
        catalog = default_catalog()
        intent = IntendedOrder(
            strategy_version_id="sv-ibkr",
            symbol="SPY",
            venue_id="ibkr",
            side=1,
            qty=Decimal("200"),
            price=Decimal("50"),
            stop_loss=Decimal("45"),
            take_profit=Decimal("60"),
            conviction=Decimal("0.6"),
            gate_passed=True,
            order_type="market",
            client_order_id="parity-ibkr",
        )
        fee = self._run_paper(store, catalog, intent)
        ibkr = catalog.venue("ibkr")
        flat = Decimal("200") * Decimal("50") * (ibkr.taker_fee_bps / Decimal("10000"))  # 0.5 bps placeholder
        assert fee > flat  # tightened: per-share (0.7 bps) > flat 0.5 bps

    def test_crypto_paper_execution_fee_unchanged(self):
        store = _store()
        catalog = default_catalog()
        intent = IntendedOrder(
            strategy_version_id="sv-crypto",
            symbol="BTCUSDT",
            venue_id="binance",
            side=1,
            qty=Decimal("0.1"),
            price=Decimal("65000"),
            stop_loss=Decimal("60000"),
            take_profit=Decimal("72000"),
            conviction=Decimal("0.6"),
            gate_passed=True,
            order_type="market",
            client_order_id="parity-crypto",
        )
        fee = self._run_paper(store, catalog, intent)
        # Fill crosses the 5 bps half-spread; the fee is the flat catalog 10 bps on the FILLED notional — exactly
        # what _pit_fee_for_order returns for the filled price with no instrument override.
        binance = catalog.venue("binance")
        fill_price = Decimal("65000") * (Decimal("1") + Decimal("0.0005"))  # buy crosses up
        expected = Decimal("0.1") * fill_price * (binance.taker_fee_bps / Decimal("10000"))
        assert fee == expected  # byte-identical to the pre-change crypto behaviour


# ---------------------------------------------------------------------------
# 4. The REAL prod path — kickstart_paper_fills backfill (orchestrator/loop.py)
# ---------------------------------------------------------------------------

class TestKickstartBackfillChargesParityFee:
    """Reproduce the EXACT 2026-07-03 prod condition and lock the fix. A *screened* version HOLDS an IBKR-equity
    position (opened the documented-TAA-arm way via apply_fill → `positions`, NEVER `executions`) with ZERO paper
    fills; `kickstart_paper_fills` then back-fills the missing ledger rows. The pre-fix code hardcoded ``fee=0``
    HERE — a THIRD fee path, distinct from the `execute_orders`/`_pit_fee_for_order` path the tests above cover.
    That divergence is exactly why `test_ibkr_paper_execution_charges_per_share_fee` PASSED (execute_orders resolves
    the instrument) while all 33 prod IBKR-equity fills — every one written by this backfill — read fee=0. This
    test exercises the SAME instrument-resolution the orchestrator uses and asserts the parity fee, not 0."""

    _TS = "2026-01-01T00:00:00+00:00"

    def _screened_ibkr_holding(self, store, *, symbol, qty, price) -> str:
        """A screened version holding one IBKR-equity leg with NO executions — the precise held-but-unledgered
        state the boot-time backfill exists to repair (apply_fill writes `positions`, record_execution defaults
        False so it writes NO `executions`)."""
        sid = store.insert("strategies", {"name": f"TAA {symbol}", "thesis": "documented", "origin": "documented", "created_at": self._TS})
        vid = store.insert(
            "strategy_versions",
            {"strategy_id": sid, "parent_id": None, "spec": {}, "generated_code": "", "code_hash": f"h-{symbol}",
             "params": {}, "mutation_operator": None, "mutation_rationale": "documented", "origin": "documented",
             "status": "screened", "created_at": self._TS, "killed_at": None, "kill_reason": None},
        )
        Portfolio(store).apply_fill(
            instrument_id=f"{symbol.lower()}-ibkr", symbol=symbol, venue="ibkr", side=1,
            qty=qty, price=price, fee=Decimal("0"), strategy_version_id=vid,
        )
        return vid

    def test_kickstart_ibkr_backfill_charges_per_share_fee_not_zero(self):
        from cosmu.orchestrator.loop import kickstart_paper_fills

        store = _store()
        catalog = default_catalog()
        qty, price = Decimal("1.3558"), Decimal("737.55")  # a real DAA/GEM SPY leg from the prod incident
        vid = self._screened_ibkr_holding(store, symbol="SPY", qty=qty, price=price)

        assert kickstart_paper_fills(store) == 1
        row = store.row(
            "SELECT fee, is_paper, venue_id, fill_log FROM executions WHERE strategy_version_id = ? ORDER BY id DESC LIMIT 1",
            (vid,),
        )
        assert row is not None
        assert int(row["is_paper"]) == 1
        assert row["venue_id"] == "ibkr"
        assert "kickstart_backfill" in str(row["fill_log"])
        fee = Decimal(str(row["fee"]))
        assert fee > 0  # THE REGRESSION: pre-fix this leg was written with a hardcoded fee=0
        # PARITY: byte-identical to the money-path chokepoint for the SAME leg (IBKR per-share, min+cap aware) —
        # which shares the resolver build_cost_context uses, so paper == backtest fee by construction.
        expected = _pit_fee_for_order(
            store, catalog.venue("ibkr"), "SPY", qty, price, instrument=catalog.instrument("SPY", "ibkr")
        )
        assert expected > 0
        assert fee == expected

    def test_kickstart_never_crashes_on_unknown_symbol(self):
        """An IBKR symbol absent from the catalog must NOT crash the boot-time backfill: the resolver degrades to
        the venue's flat taker bps (0.5 for IBKR) — still > 0, still honest, never a hard failure."""
        from cosmu.orchestrator.loop import kickstart_paper_fills

        store = _store()
        catalog = default_catalog()
        qty, price = Decimal("10"), Decimal("100")
        vid = self._screened_ibkr_holding(store, symbol="ZZZZ", qty=qty, price=price)  # not in default_catalog

        assert kickstart_paper_fills(store) == 1
        fee = Decimal(str(store.row(
            "SELECT fee FROM executions WHERE strategy_version_id = ? ORDER BY id DESC LIMIT 1", (vid,)
        )["fee"]))
        ibkr = catalog.venue("ibkr")
        assert fee == qty * price * (ibkr.taker_fee_bps / Decimal("10000"))  # flat 0.5 bps fallback
        assert fee > 0  # never the 0 the bug wrote
