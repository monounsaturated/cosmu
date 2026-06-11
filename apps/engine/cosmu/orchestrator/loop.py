# intent: CLOSE THE AUTONOMOUS LOOP — read REAL persisted survivors (Finder/research gate-passers with tracks),
# open a STANDALONE forward-test track for each (its own simulated capital, no pooled wallet, no cross-track
# competition), routing intended orders through the ONE order path (master/execution → master/portfolio), then
# mark-to-market so GET /overview reflects genuine positions/equity (no fabricated numbers). inputs: the store +
# a market provider for latest marks; outputs: funded tracks + opened sim positions + a marked snapshot.
# invariants: only gate-passed survivors are funded, each track is standalone (fixed per-strategy capital, never a
# pooled share), live stays OFF (sim fills only), every fill is audited, deterministic for a fixed store + marks,
# offline-safe (degrades to cache).

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from decimal import ROUND_DOWN, Decimal

from cosmu.data.market import BinanceSpotOHLCVProvider, MarketDataProvider, YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.drift import monitor_drift
from cosmu.master.execution import IntendedOrder, execute_orders
from cosmu.master.neutral import accrue_funding, neutral_tracks
from cosmu.master.portfolio import Portfolio
from cosmu.portfolio.rotation import Track, select_tracks
from cosmu.spine.venue import VenueCatalog, default_catalog

# ASSET-CLASS → its funding venue (one tradable venue per class, mirroring PricingRouter's mark routing): crypto
# funds on Binance spot; equity/ETF funds on the IBKR instruments (the same equity universe the GEM arm uses, marked
# via Yahoo total-return). A class absent here has NO funding venue wired → its survivors are SKIPPED, never forced
# onto a crypto symbol (no mislabeled/mispriced position). Add a class here only once a real tradable venue exists.
_FUNDING_VENUE_BY_ASSET_CLASS: dict[str, str] = {"crypto": "binance", "equity": "ibkr"}


def _instrument_venue(catalog: VenueCatalog, instrument_id: str) -> str | None:
    """The catalog venue an instrument trades on, looked up by instrument id. Positions opened through the
    ONE order path persist venue='sim' — a fill-ledger label, NOT a catalog venue — so pricing/routing must
    recover the real venue from the instrument (an equity survivor funded via the order path would otherwise
    route to the crypto leg and never mark). None for an unknown instrument (the caller skips honestly)."""
    for inst in catalog.instruments:
        if inst.id == instrument_id:
            return inst.venue_id
    return None


def _venue_symbols(catalog: VenueCatalog, venue_id: str, asset_class: str) -> list[str]:
    """Symbols that actually exist as instruments at `venue_id` for `asset_class` (so a sim fill can resolve an
    instrument). A track only funds tradable instruments — no fabricated symbols."""
    return [i.symbol for i in catalog.instruments if i.venue_id == venue_id and i.asset_class == asset_class]


def _survivor_asset_class(raw_spec: object) -> str:
    """The asset class a survivor should be FUNDED against, read from its persisted StrategySpec
    (`universe.asset_classes`). Defaults to crypto when the spec is missing/unparsable or declares no asset class
    — the historical default for this loop (never crash on an unexpected row)."""
    if not raw_spec:
        return "crypto"
    try:
        spec = json.loads(raw_spec) if isinstance(raw_spec, str) else raw_spec
    except (ValueError, TypeError):
        return "crypto"
    if not isinstance(spec, dict):
        return "crypto"
    classes = (spec.get("universe") or {}).get("asset_classes") or []
    return str(classes[0]) if classes else "crypto"


@dataclass
class TrackFundingReport:
    survivors: int
    funded: int = 0
    funded_tracks: list[str] = field(default_factory=list)   # version_ids of the standalone tracks opened this cycle
    equity: float = 0.0
    pnl: float = 0.0
    drift_defunded: int = 0   # tracks the anticipatory drift monitor pulled this cycle (edge half-life / live drift)


def _survivor_tracks(store: Store, catalog: VenueCatalog) -> list[tuple[str, Track, str, str]]:
    """Read the real config-library / research survivors: forward-test/live versions that passed the gate and have
    a track. ASSET-AWARE: each survivor is routed to its OWN asset class's funding venue + symbol (read from the
    persisted spec's `universe.asset_classes`), mirroring PricingRouter's mark routing — crypto → Binance,
    equity → IBKR. A survivor whose asset class has NO funding venue wired (or no tradable symbol there) is
    SKIPPED rather than forced onto a crypto symbol (never mislabel/misprice a position). Returns
    (version_id, Track, symbol, venue_id). `rolling_dsr` = the deflated Sharpe (decays as edge dies)."""
    rows = store.rows(
        """
        SELECT sv.id AS version_id, sv.spec AS spec, tr.return_pct AS return_pct,
               b.deflated_sharpe AS deflated_sharpe, b.max_dd AS max_dd, b.oos_return AS oos_return
        FROM strategy_versions sv
        JOIN tracks tr ON tr.strategy_version_id = sv.id
        JOIN backtests b ON b.strategy_version_id = sv.id AND b.kind = 'screen'
        WHERE sv.status IN ('forward_test', 'live') AND b.passed_gates = 1 AND b.holdout_passed = 1
        ORDER BY CAST(b.deflated_sharpe AS REAL) DESC
        LIMIT 12
        """
    )
    # Round-robin within each asset class so multiple crypto (or multiple equity) survivors spread across that
    # class's tradable symbols instead of all colliding on one.
    symbols_by_class: dict[str, list[str]] = {}
    next_idx: dict[str, int] = {}
    out: list[tuple[str, Track, str, str]] = []
    for r in rows:
        asset_class = _survivor_asset_class(r.get("spec"))
        venue_id = _FUNDING_VENUE_BY_ASSET_CLASS.get(asset_class)
        if venue_id is None:
            continue  # no funding venue wired for this asset class → SKIP (never force onto a crypto symbol)
        symbols = symbols_by_class.setdefault(asset_class, _venue_symbols(catalog, venue_id, asset_class))
        if not symbols:
            continue  # the funding venue has no tradable instrument for this class → SKIP (no fabricated symbol)
        i = next_idx.get(asset_class, 0)
        next_idx[asset_class] = i + 1
        track = Track(id=r["version_id"], rolling_dsr=float(r["deflated_sharpe"] or 0.0))
        out.append((r["version_id"], track, symbols[i % len(symbols)], venue_id))
    return out


def fund_tracks_from_survivors(
    store: Store,
    *,
    market_data: MarketDataProvider | None = None,
    catalog: VenueCatalog | None = None,
    bankroll: Decimal = Decimal("100000"),
    router: PricingRouter | None = None,
) -> TrackFundingReport:
    """Close the loop in the standalone-track model: open a STANDALONE forward-test track for each gate-passed
    survivor (its own fixed per-strategy capital — never a pooled share), open sim positions through the one order
    path, and mark-to-market. There is no cross-track competition or capital weighting. Live stays OFF (sim fills).

    ASSET-AWARE: each survivor is FUNDED on the venue/symbol for its OWN asset class (read from the spec —
    crypto → Binance, equity → IBKR), and marked via the SAME router the forward-test clock uses, so an equity
    survivor opens a REAL equity position priced off Yahoo total-return instead of a mislabeled/mispriced Binance
    crypto symbol. A survivor whose asset class has no funding venue wired is SKIPPED (never forced onto crypto).
    `market_data` (kept for back-compat) overrides ONLY the crypto mark leg; pass `router` to control both legs."""
    cat = catalog or default_catalog()
    # ASSET-AWARE marks: the funder marks each new fill via the SAME router the forward-test clock uses, so a crypto
    # fill prices off Binance and an equity fill off Yahoo total-return — never marking an equity to 0 against a
    # Binance symbol. `market_data` (kept for back-compat) overrides only the crypto leg.
    pricer = router or PricingRouter(cat, crypto=market_data)
    portfolio = Portfolio(store, bankroll=bankroll)

    triples = _survivor_tracks(store, cat)
    report = TrackFundingReport(survivors=len(triples))
    if not triples:
        marks = portfolio.mark_to_market({})
        report.equity = float(marks["equity"])
        report.pnl = float(marks["pnl"])
        return report

    # ANTICIPATORY defund (master/drift): assess each funded track's realized trajectory (edge half-life + live
    # drift vs what it was funded on) and pull capital BEFORE P&L turns. Reads prior marks; on first funding there
    # is no history yet → no defund (insufficient history). select_tracks applies the verdict below.
    verdicts = {v.ref_id: v for v in monitor_drift(store, [vid for vid, _, _, _ in triples])}
    triples = [
        (
            vid,
            replace(
                track,
                drift_defund=verdicts[vid].defund if vid in verdicts else False,
                edge_half_life=verdicts[vid].decay.half_life if vid in verdicts else None,
            ),
            symbol,
            venue_id,
        )
        for vid, track, symbol, venue_id in triples
    ]
    report.drift_defunded = sum(1 for v in verdicts.values() if v.defund)

    track_by_id = {vid: (track, symbol, venue_id) for vid, track, symbol, venue_id in triples}
    fundable = {v.version_id for v in select_tracks([t for _, t, _, _ in triples]) if v.funded}

    # A track that has EVER held a sim position is NOT re-opened here: re-funding a held track every tick would
    # average a fresh same-bar entry into the basis and reset its forward-test clock, and re-funding a track the
    # forward-test EXECUTOR closed would overwrite its strategy's own verdict with a static long. The funder
    # funds each survivor ONCE; from then on the executor (orchestrator/forward_step.py) owns every entry/exit
    # by the track's own signals, and mark_tracks() accrues the honest P&L.
    already_funded = {
        r["strategy_version_id"]
        for r in store.rows(
            "SELECT DISTINCT strategy_version_id FROM positions WHERE strategy_version_id IS NOT NULL"
        )
    }

    # Build the latest marks + the intended sim orders for each NEW funded track. Each track is standalone: it is
    # sized to a fixed per-strategy capital (the standardized track size), not a competed pooled share.
    marks: dict[str, Decimal] = {}
    intents: list[IntendedOrder] = []
    # A standalone track is funded with one per-strategy slice (sim_track_capital), drawn from the SIM pool
    # (sim_bankroll) — so the pool fits many tracks and the gauntlet's per_strategy_cap/min_cash_reserve pass.
    per_track_capital = store.settings.sim_track_capital
    for vid in fundable:
        if vid in already_funded:
            continue
        _track, symbol, venue_id = track_by_id[vid]
        # Mark via the asset-aware router (crypto → Binance, equity → Yahoo) at the survivor's OWN venue — so an
        # equity survivor prices off a real equity close, not a Binance symbol that does not exist.
        price = pricer.last_price(symbol, venue_id)
        if price <= 0:
            continue
        instrument = cat.instrument(symbol, venue_id)
        marks[instrument.id] = price
        # Standalone track size = the standardized per-strategy capital (the risk gauntlet enforces the same cap,
        # so the sim fill is accepted rather than rejected).
        notional = per_track_capital
        # Round qty DOWN so qty*price can never round a hair OVER the per-strategy cap (the gauntlet's
        # `notional > cap` is strict — sizing to exactly the cap then rounding up would trip it + reject the fill).
        qty = (notional / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if qty <= 0:
            continue
        intents.append(
            IntendedOrder(
                strategy_version_id=vid,
                symbol=symbol,
                venue_id=venue_id,
                side=1,
                qty=qty,
                price=price,
                # Bracket the sim entry with conservative protective levels (the risk gauntlet requires both;
                # the deterministic master owns final sizing — these are structure, not magic edge numbers).
                stop_loss=(price * Decimal("0.95")).quantize(Decimal("0.01")),
                take_profit=(price * Decimal("1.10")).quantize(Decimal("0.01")),
                conviction=Decimal("0.5"),
                gate_passed=True,        # only gate-passed survivors reach here; live still gated by the toggle
            )
        )

    execute_orders(
        intents,
        live_enabled=False,             # the loop funds SIM tracks; live stays off until explicitly armed
        kill_switch=False,
        adapter=None,
        store=store,
        portfolio=portfolio,
        risk=store.settings.risk,
        catalog=cat,
    )
    report.funded = len(intents)
    report.funded_tracks = [i.strategy_version_id for i in intents if i.strategy_version_id]
    snapshot = portfolio.mark_to_market(marks)
    report.equity = float(snapshot["equity"])
    report.pnl = float(snapshot["pnl"])
    store.append_event(
        actor="master",
        kind="tracks_funded",
        ref_type="portfolio",
        ref_id="aggregate",
        payload={"survivors": report.survivors, "funded": report.funded, "equity": report.equity, "pnl": report.pnl},
    )
    return report


class PricingRouter:
    """ASSET-AWARE mark source for the forward-test clock. One router routes each held position to the REAL
    pricing source for its asset class — crypto → Binance spot, equity/ETF → Yahoo v8 total-return — so an
    equity (GEM, the TAA fleet) accrues honest P&L instead of marking to 0 against a Binance symbol that does
    not exist. The asset class is read from the instrument the position references in the catalog (looked up by
    (symbol, venue)); an unknown instrument falls back to the venue's declared kind. NO synthetic/zero-fill: a
    genuinely unavailable close (offline, gap day, unknown symbol) returns 0 and the caller SKIPS that position,
    leaving it at its last basis. Deterministic for a fixed catalog + provider responses; offline-safe.

    The crypto and equity providers are constructed lazily and reused across every position in one run (one cache
    each), and either can be injected for tests/alternate venues — there is no per-call-site provider, this is the
    single pricing-router for the clock."""

    def __init__(
        self,
        catalog: VenueCatalog,
        *,
        crypto: MarketDataProvider | None = None,
        equity: MarketDataProvider | None = None,
    ) -> None:
        self.catalog = catalog
        self._crypto = crypto or BinanceSpotOHLCVProvider()
        # Yahoo v8 prices on TOTAL-RETURN closes — the same source the working equity_dual_momentum_arm mark uses
        # (keyless, certifi SSL). Reused so a multi-leg equity track shares one cache per run.
        self._equity = equity or YahooDailyBarsProvider()

    def _asset_class(self, symbol: str, venue: str) -> str:
        """The asset class to price `symbol`@`venue` against. Prefer the instrument's own asset_class; if the
        instrument is not in the catalog, fall back to the venue's declared kind; if neither resolves, treat it
        as crypto (the historical default for this clock — never crash on an unknown row)."""
        try:
            return self.catalog.instrument(symbol, venue).asset_class
        except KeyError:
            pass
        try:
            return self.catalog.venue(venue).kind
        except KeyError:
            return "crypto"

    def provider_for(self, symbol: str, venue: str) -> MarketDataProvider:
        """The REAL pricing source for this position's asset class. equity/ETF → Yahoo total-return; everything
        else (crypto, the default) → Binance spot."""
        return self._equity if self._asset_class(symbol, venue) == "equity" else self._crypto

    def last_price(self, symbol: str, venue: str) -> Decimal:
        """Latest REAL daily close for a held position via its asset-class provider. 0 on any failure
        (offline / gap / unknown symbol) — never a synthetic fill; the caller skips the position."""
        return _last_price(self.provider_for(symbol, venue), symbol, self.catalog)


def mark_tracks(
    store: Store,
    *,
    market_data: MarketDataProvider | None = None,
    catalog: VenueCatalog | None = None,
    router: PricingRouter | None = None,
) -> dict[str, Decimal]:
    """THE FORWARD-TEST CLOCK. Re-mark every HELD sim position against the latest REAL close — without opening,
    re-funding, or averaging anything — and write a portfolio_snapshot. This is what makes a track a genuine
    forward test: a funded track lives across bars and reveals honest net-of-fee P&L over calendar time, instead
    of the same-bar entry==mark snapshot the funding step produces. Cron-able (run on a schedule independent of
    the 4h author/fund tick); offline-safe (a missing mark just leaves that position at its last basis); live
    stays OFF (no orders — marks only).

    ASSET-AWARE: each held position is priced via a PricingRouter that routes by asset class — crypto → Binance,
    equity/ETF → Yahoo total-return — so equity tracks (GEM, the TAA fleet) accrue P&L instead of sitting flat.
    `market_data` (kept for back-compat) overrides ONLY the crypto leg; pass `router` to control both legs."""
    cat = catalog or default_catalog()
    pricer = router or PricingRouter(cat, crypto=market_data)
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    positions = [p for p in portfolio.positions() if p.qty != 0]
    marks: dict[str, Decimal] = {}
    for p in positions:
        # Route by the instrument's REAL catalog venue: order-path fills persist venue='sim' (a ledger label),
        # which the router can't price — an equity survivor funded via the order path would silently route to
        # the crypto leg and never mark. Arm-opened positions carry the real venue already; both resolve here.
        venue = _instrument_venue(cat, p.instrument_id) or p.venue
        price = pricer.last_price(p.symbol, venue)
        if price > 0:
            marks[p.instrument_id] = price
    # TWO-LEG NEUTRAL tracks (DERIVATIVES_PLAN P0.3): pair a held long-spot leg with its short-perp leg, accrue one
    # funding period on the short perp against its latest mark, and carry the running funding into the mark. A
    # single-leg spot track has no short leg → it is not a neutral pair → it falls straight through to the
    # unchanged spot mark path below. Offline-safe: no funding data for a perp leg accrues nothing this tick.
    funding_by_track = _accrue_neutral_funding(store, positions, marks)
    snapshot = portfolio.mark_to_market(marks, funding_by_track=funding_by_track)
    # Drive each track's tracks.return_pct from the LIVE marked trajectory (the per-track snapshot
    # mark_to_market just wrote), so the forward-test net P&L — not a stale seed — is what the leaderboard +
    # master/live_eligibility read for live_ready. EVERY version with a position row updates, including
    # FLAT tracks the executor closed (their realized P&L must land in return_pct, not freeze pre-close).
    # A flat/negative forward test can therefore never reach live_ready on a stale seed.
    tracked = {
        r["strategy_version_id"]
        for r in store.rows("SELECT DISTINCT strategy_version_id FROM positions WHERE strategy_version_id IS NOT NULL")
    }
    updated = _update_track_returns(store, tracked)
    store.append_event(
        actor="master",
        kind="tracks_marked",
        ref_type="portfolio",
        ref_id="aggregate",
        payload={
            "positions": len(positions),
            "marked": len(marks),
            "neutral_tracks": len(funding_by_track),
            "tracks_updated": updated,
            "equity": float(snapshot["equity"]),
            "pnl": float(snapshot["pnl"]),
        },
    )
    return snapshot


def _update_track_returns(store: Store, version_ids: set[str]) -> int:
    """Refresh tracks.return_pct + tracks.equity for each held track from its latest per-track marked value
    (portfolio_snapshots scope='track'), vs the track's own starting_capital. Mirrors what the per-arm equity
    mark did for GEM, generalized to every track the clock just marked. Returns the count updated. A track with
    no marked snapshot or no starting_capital is left untouched (offline-safe — never zero/synthetic-fill)."""
    updated = 0
    for vid in version_ids:
        track = store.row(
            "SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (vid,)
        )
        snap = store.row(
            "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1",
            (vid,),
        )
        if track is None or track.get("starting_capital") is None or snap is None or snap.get("equity") is None:
            continue
        starting = Decimal(str(track["starting_capital"]))
        if starting <= 0:
            continue
        marked_value = Decimal(str(snap["equity"]))
        return_pct = (marked_value / starting - Decimal("1")) * Decimal("100")
        store.rows(
            "UPDATE tracks SET return_pct = ?, equity = ?, updated_at = ? WHERE strategy_version_id = ?",
            (str(return_pct.quantize(Decimal("0.01"))), str(marked_value.quantize(Decimal("0.01"))),
             utcnow(), vid),
        )
        updated += 1
    return updated


def _accrue_neutral_funding(
    store: Store, positions: list, marks: dict[str, Decimal]
) -> dict[str, Decimal]:
    """For each two-leg neutral track, accrue one funding period on the short-perp leg (point-in-time rate from
    the `alt_data` store) and return {strategy_version_id: cumulative funding}. Empty when there are no neutral
    pairs — so the spot-only path adds nothing. Funding accrues only when a fresh perp mark exists this tick (the
    venue charges funding on live notional); a missing rate or mark accrues nothing (offline-safe, deterministic
    for a fixed store + marks)."""
    tracks = neutral_tracks(store, positions)
    out: dict[str, Decimal] = {}
    for track in tracks:
        perp_mark = marks.get(track.perp.instrument_id)
        rate = _funding_rate_asof(store, track.perp.symbol)
        if perp_mark is not None and perp_mark > 0 and rate is not None:
            total = accrue_funding(store, track, funding_rate=rate, perp_mark=perp_mark)
        else:
            total = track.funding_accrued  # no fresh rate/mark → carry the prior cumulative forward unchanged
        out[track.strategy_version_id] = total
    return out


def _funding_rate_asof(store: Store, symbol: str) -> Decimal | None:
    """The latest point-in-time funding rate for a perp symbol from the central alt_data store (the same series
    the ingest pass fills: provider 'binance', metric 'funding_rate'). None when no rate is on file — accrue
    nothing this tick (offline-safe)."""
    row = store.row(
        "SELECT value FROM alt_data WHERE provider = 'binance' AND symbol = ? AND metric = 'funding_rate' "
        "ORDER BY available_at DESC, id DESC LIMIT 1",
        (symbol,),
    )
    return Decimal(str(row["value"])) if row else None


# The hourly intraday lane steps ONLY sub-daily horizons: crypto bars are closed-candle-guarded (data/market),
# while the Yahoo equity source serves an in-progress day bar — so daily tracks stay on the daily clocks.
_INTRADAY_BAR_SIZES = frozenset({"1h", "4h"})


def _main(argv: list[str] | None = None) -> int:
    """Railway cron entrypoint for the FORWARD-TEST CLOCK: first the EXECUTOR (forward_step.step_tracks — each
    gate-lane track's OWN spec/params decide exits and re-entries through the one order path, sim-only), then
    the MARK (re-mark every held sim position against the latest REAL close, routed by asset class — crypto →
    Binance, equity/ETF → Yahoo total-return). Step-then-mark so the snapshot reflects post-trade state.

    Three cadences, one entrypoint (re-running on the same closed bar is always a no-op — decision-bar coids):
      `python3 -m cosmu.orchestrator.loop`             full clock (daily crons, 00:10 + 22:10 UTC)
      `python3 -m cosmu.orchestrator.loop --intraday`  hourly lane: step sub-daily (1h/4h) tracks, then mark all
      `python3 -m cosmu.orchestrator.loop --mark-only` marks only (no executor step) — freshness without trades
    """
    import argparse

    from cosmu.config.settings import Settings
    from cosmu.orchestrator.forward_step import step_tracks

    parser = argparse.ArgumentParser(
        description="Run the forward-test executor (each track's own exits/entries, sim-only) then mark held positions to the latest real close, asset-aware."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--intraday", action="store_true",
                      help="step only sub-daily (1h/4h) tracks, then mark all held positions (the hourly lane)")
    mode.add_argument("--mark-only", action="store_true",
                      help="skip the executor step; just re-mark held positions to the latest real close")
    args = parser.parse_args(argv)
    store = Store(Settings())
    if not args.mark_only:
        step = step_tracks(store, bar_sizes=_INTRADAY_BAR_SIZES if args.intraday else None)
        lane = "intraday" if args.intraday else "full"
        print(f"FORWARD-TEST STEP ({lane}) — managed={step.managed} closed={step.closed} opened={step.opened} "
              f"skipped(deploy/unmanaged)={step.skipped_deploy}/{step.skipped_unmanaged}")
    snap = mark_tracks(store)
    print(f"SIM MARK-TO-MARKET — equity={float(snap['equity']):.2f} pnl={float(snap['pnl']):+.2f} drawdown={float(snap['drawdown']):.4f}")
    return 0


def _last_price(provider: MarketDataProvider, symbol: str, catalog: VenueCatalog) -> Decimal:
    try:
        bars = provider.fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline/no-network: no fresh mark for this symbol, skip it
        return Decimal("0")
    if not bars:
        return Decimal("0")
    return bars[-1].close


if __name__ == "__main__":
    raise SystemExit(_main())
