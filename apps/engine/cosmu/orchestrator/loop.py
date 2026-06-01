# intent: CLOSE THE AUTONOMOUS LOOP — read REAL persisted survivors (Finder/research gate-passers with sleeves),
# size them with the capped-Kelly correlation-aware allocator (portfolio/rotation), fund the single pooled paper
# Wallet by routing intended orders through the ONE order path (master/execution → master/portfolio), then
# mark-to-market so GET /portfolio reflects genuine positions/equity (no fabricated numbers). inputs: the store +
# a market provider for latest marks; outputs: allocations + opened paper positions + a marked snapshot.
# invariants: only gate-passed survivors are funded, sizing is capped-Kelly + memoryless, live stays OFF (paper
# fills only), every fill is audited, deterministic for a fixed store + marks, offline-safe (degrades to cache).

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from cosmu.data.market import BinanceSpotOHLCVProvider, MarketDataProvider
from cosmu.knowledge.store import Store
from cosmu.master.execution import IntendedOrder, execute_orders
from cosmu.master.portfolio import PaperPortfolio
from cosmu.portfolio.rotation import Allocation, Sleeve, rotate
from cosmu.spine.venue import VenueCatalog, default_catalog


def _crypto_symbols(catalog: VenueCatalog) -> list[str]:
    """Binance crypto symbols that actually exist as instruments in the catalog (so a paper fill can resolve an
    instrument). The Wallet only funds tradable instruments — no fabricated symbols."""
    return [i.symbol for i in catalog.instruments if i.venue_id == "binance" and i.asset_class == "crypto"]


@dataclass
class WalletFundingReport:
    survivors: int
    allocations: list[Allocation] = field(default_factory=list)
    funded: int = 0
    equity: float = 0.0
    pnl: float = 0.0


def _survivor_sleeves(store: Store, symbols: list[str]) -> list[tuple[str, Sleeve, str]]:
    """Read the real config-library / research survivors: paper/live versions that passed the gate and have a
    sleeve. Returns (version_id, Sleeve, symbol). `edge` = the sleeve's net-of-cost return per the backtest;
    `rolling_dsr` = the deflated Sharpe (decays as edge dies); `variance` from the backtest drawdown proxy."""
    rows = store.rows(
        """
        SELECT sv.id AS version_id, sl.return_pct AS return_pct, b.deflated_sharpe AS deflated_sharpe,
               b.max_dd AS max_dd, b.oos_return AS oos_return
        FROM strategy_versions sv
        JOIN sleeves sl ON sl.strategy_version_id = sv.id
        JOIN backtests b ON b.strategy_version_id = sv.id AND b.kind = 'screen'
        WHERE sv.status IN ('paper', 'live') AND b.passed_gates = 1
        ORDER BY CAST(b.deflated_sharpe AS REAL) DESC
        LIMIT 12
        """
    )
    out: list[tuple[str, Sleeve, str]] = []
    if not symbols:
        return out
    for i, r in enumerate(rows):
        edge = float(r["oos_return"] or 0.0)
        dd = float(r["max_dd"] or 0.0)
        sleeve = Sleeve(
            id=r["version_id"],
            edge=edge,
            variance=max(1e-4, dd * dd + 1e-3),       # drawdown-based variance proxy for capped-Kelly sizing
            rolling_dsr=float(r["deflated_sharpe"] or 0.0),
        )
        out.append((r["version_id"], sleeve, symbols[i % len(symbols)]))
    return out


def fund_wallet_from_survivors(
    store: Store,
    *,
    market_data: MarketDataProvider | None = None,
    catalog: VenueCatalog | None = None,
    bankroll: Decimal = Decimal("100000"),
) -> WalletFundingReport:
    """Close the loop for the single pooled paper Wallet: size gate-passed survivors with the capped-Kelly
    allocator, open paper positions through the one order path, and mark-to-market. Live stays OFF (paper fills)."""
    cat = catalog or default_catalog()
    provider = market_data or BinanceSpotOHLCVProvider()
    portfolio = PaperPortfolio(store, bankroll=bankroll)

    triples = _survivor_sleeves(store, _crypto_symbols(cat))
    report = WalletFundingReport(survivors=len(triples))
    if not triples:
        marks = portfolio.mark_to_market({})
        report.equity = float(marks["equity"])
        report.pnl = float(marks["pnl"])
        return report

    sleeve_by_id = {vid: (sleeve, symbol) for vid, sleeve, symbol in triples}
    allocations = rotate([s for _, s, _ in triples], max_positions=3)
    report.allocations = allocations

    # Build the latest marks + the intended paper orders for each funded sleeve.
    marks: dict[str, Decimal] = {}
    intents: list[IntendedOrder] = []
    equity = portfolio.equity()
    for alloc in allocations:
        if alloc.weight <= 0 or alloc.sleeve_id not in sleeve_by_id:
            continue
        _sleeve, symbol = sleeve_by_id[alloc.sleeve_id]
        price = _last_price(provider, symbol, cat)
        if price <= 0:
            continue
        instrument = cat.instrument(symbol, "binance")
        marks[instrument.id] = price
        # Allocator weight × equity, but never above the per-strategy notional cap (the risk gauntlet enforces it
        # too; we size within it so the paper fill is accepted rather than rejected).
        notional = min(equity * Decimal(str(alloc.weight)), store.settings.risk.per_strategy_cap)
        # Round qty DOWN so qty*price can never round a hair OVER the per-strategy cap (the gauntlet's
        # `notional > cap` is strict — sizing to exactly the cap then rounding up would trip it + reject the fill).
        qty = (notional / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= 0:
            continue
        intents.append(
            IntendedOrder(
                strategy_version_id=alloc.sleeve_id,
                symbol=symbol,
                venue_id="binance",
                side=1,
                qty=qty,
                price=price,
                # Bracket the paper entry with conservative protective levels (the risk gauntlet requires both;
                # the deterministic master owns final sizing — these are structure, not magic edge numbers).
                stop_loss=(price * Decimal("0.95")).quantize(Decimal("0.01")),
                take_profit=(price * Decimal("1.10")).quantize(Decimal("0.01")),
                conviction=Decimal("0.5"),
                gate_passed=True,        # only gate-passed survivors reach here; live still gated by the toggle
            )
        )

    execute_orders(
        intents,
        live_enabled=False,             # the loop funds the PAPER Wallet; live stays off until explicitly armed
        kill_switch=False,
        adapter=None,
        store=store,
        portfolio=portfolio,
        risk=store.settings.risk,
        catalog=cat,
    )
    report.funded = sum(1 for a in allocations if a.weight > 0)
    snapshot = portfolio.mark_to_market(marks)
    report.equity = float(snapshot["equity"])
    report.pnl = float(snapshot["pnl"])
    store.append_event(
        actor="master",
        kind="wallet_funded",
        ref_type="portfolio",
        ref_id="global",
        payload={"survivors": report.survivors, "funded": report.funded, "equity": report.equity, "pnl": report.pnl},
    )
    return report


def _last_price(provider: MarketDataProvider, symbol: str, catalog: VenueCatalog) -> Decimal:
    try:
        bars = provider.fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline/no-network: no fresh mark for this symbol, skip it
        return Decimal("0")
    if not bars:
        return Decimal("0")
    return bars[-1].close
