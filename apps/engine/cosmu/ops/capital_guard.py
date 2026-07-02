# intent: the CAPITAL-PROTECTION SUPERVISOR — a deterministic, read-then-reduce probe that protects a FUNDED
# combo's capital independently of (and in addition to) the strategy's own stop/take/time/signal exits. Two
# guards per funded track, judged on ITS OWN cell-keyed marked equity (scope='track' portfolio_snapshots):
#   • capital-preservation — LIQUIDATE the whole position when marked equity falls to/below a FLOOR fraction of
#     the track's starting_capital (a hard "don't ride it to zero" backstop), and
#   • profit-LOCK — TRIM the position when it has given back more than a configurable % from its OWN equity peak
#     (lock realized gains rather than round-trip a winner back to flat).
# Every protective order is REDUCE-ONLY, so master/risk.py routes it unconditionally — caps, the kill-switch, the
# daily-loss disarm, and the regime gate are all EXEMPT for a genuine close (blocking an exit traps the very loss
# this guard exists to stop). Orders route through the SAME exec resolver + execute_orders seam step_tracks uses:
# a live-book position closes via its armed venue adapter; a sim/paper position closes deterministically on the
# sim path. SAFE TO ADD WHILE LIVE IS OFF: with no armed venue this only ever reduce-fills the SIM/paper book
# (identical mechanics to the paper executor's own exits); it can move REAL money only once a venue is armed, and
# even then only ever to REDUCE exposure. inputs: the store (+ optional pricing router / config / now); outputs:
# audited reduce-only fills + capital_guard_action events; invariants: zero funded tracks → clean NO-OP; never
# OPENS or grows a position; deterministic for a fixed store + marks; offline-safe (no mark → skip that track).

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from cosmu.knowledge.store import Store, tracks_has_cell_columns
from cosmu.master.execution import IntendedOrder, OrderOutcome, execute_orders
from cosmu.master.portfolio import Portfolio, PositionView
from cosmu.orchestrator.loop import PricingRouter, _instrument_venue
from cosmu.orchestrator.paper_step import _resolve_live_adapters
from cosmu.spine.venue import VenueCatalog, default_catalog

# The books a real venue submit lands on (mirrors execution._LIVE_BOOKS): a position on one of these is closed via
# its armed adapter; anything else (the default "sim" paper book) closes deterministically on the sim path.
_LIVE_BOOKS = frozenset({"testnet", "live"})


@dataclass(frozen=True)
class GuardConfig:
    """Capital-protection thresholds — config-driven with sane, conservative defaults. All fractions; off-by-
    default where it would touch real money is handled structurally (a protective close only ROUTES live when the
    operator has armed the venue — see run_capital_guard). Setting a fraction to None disables that guard.

    floor_fraction: liquidate when marked equity <= starting_capital * floor_fraction (0.70 = down 30%).
    giveback_fraction: trim when equity has fallen this far BELOW its own peak (0.25 = gave back 25% from peak).
    trim_fraction: how much of the position to sell on a profit-lock trim (0.50 = sell half).
    min_peak_gain_fraction: only profit-LOCK a track whose peak rose at least this far above its starting capital
      (0.05 = peak must be +5%) — so the giveback guard never trims a track that never made money (that is the
      floor guard's job), it only locks REAL gains."""

    floor_fraction: Decimal | None = Decimal("0.70")
    giveback_fraction: Decimal | None = Decimal("0.25")
    trim_fraction: Decimal = Decimal("0.50")
    min_peak_gain_fraction: Decimal = Decimal("0.05")


DEFAULT_CONFIG = GuardConfig()


@dataclass
class GuardAction:
    """One protective decision the supervisor took (or would take). `kind` is 'liquidate' (floor breach, full
    close) or 'trim' (profit-lock, partial close). Carries the numbers the audit event records."""

    version_id: str
    symbol: str
    venue_id: str
    kind: str  # "liquidate" | "trim"
    reason: str  # "capital_floor" | "profit_lock"
    qty: Decimal
    equity: Decimal
    starting_capital: Decimal
    peak: Decimal


@dataclass
class GuardReport:
    """One supervisor pass, honestly counted. `evaluated` = funded tracks with a markable open position that were
    judged; `protected` = those an accepted reduce-only fill actually closed/trimmed this pass."""

    evaluated: int = 0
    protected: int = 0
    actions: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _FundedHolding:
    """A funded track resolved to everything the guard needs: its open position, real catalog venue, cell-keyed
    marked equity, peak equity, and starting capital."""

    version_id: str
    symbol: str
    venue_id: str  # the REAL catalog venue (positions persist venue='sim' as a ledger label)
    position: PositionView
    equity: Decimal
    peak: Decimal
    starting_capital: Decimal


def _latest_track_equity(store: Store, ref_id: str) -> Decimal | None:
    """The most recent marked equity for a cell's scope='track' snapshot series, or None if it has never marked.
    `ref_id` is the cell key (version:symbol:venue) or the legacy version-only key. Reads the RAW latest on purpose:
    a real mark that genuinely lands back on the seed (a break-even track) IS the current equity, so it must NOT be
    filtered here (that would hide a real giveback and fail to protect). The funder's phantom collapse-to-seed rows
    are removed at the ROOT — the writer no longer emits them (master/portfolio.mark_to_market) and the historical
    ones are backfilled out — so the raw latest is a real mark, and reads conservative (phantom-low) if any linger."""
    row = store.row(
        "SELECT equity FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ? ORDER BY ts DESC LIMIT 1",
        (ref_id,),
    )
    if row is None or row.get("equity") is None:
        return None
    try:
        return Decimal(str(row["equity"]))
    except Exception:  # noqa: BLE001 — a malformed snapshot must never break the money path
        return None


def _peak_track_equity(store: Store, ref_id: str, *, floor: Decimal) -> Decimal:
    """The high-water mark of a cell's marked-equity series (>= floor so a brand-new track with one snapshot has
    a sane peak). The profit-lock guard measures giveback from THIS. Raw MAX by design (see _latest_track_equity):
    a genuine break-even mark equal to the seed is real equity, and a phantom seed row is <= a real peak so it never
    inflates the high-water — the root writer fix + backfill remove the phantoms rather than filter them here."""
    row = store.row(
        "SELECT MAX(CAST(equity AS REAL)) AS hw FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ?",
        (ref_id,),
    )
    if row and row.get("hw") is not None:
        try:
            return max(Decimal(str(row["hw"])), floor)
        except Exception:  # noqa: BLE001
            pass
    return floor


def _funded_holdings(store: Store, portfolio: Portfolio, cat: VenueCatalog) -> list[_FundedHolding]:
    """Every FUNDED track (a `tracks` row) that currently HOLDS a markable open position, resolved to its
    cell-keyed marked equity + peak + starting capital. A flat track (no open qty) has no exposure to protect and
    is skipped; a track whose instrument/venue can't be resolved is skipped honestly (never guess)."""
    has_cells = tracks_has_cell_columns(store)
    # Index open positions by version so a track row can find its held leg. A funded track is one cell of one
    # version; the position carries the instrument the guard prices + closes.
    open_by_version: dict[str, PositionView] = {}
    for p in portfolio.positions():
        if p.strategy_version_id and p.qty != 0:
            open_by_version.setdefault(p.strategy_version_id, p)

    holdings: list[_FundedHolding] = []
    if has_cells:
        rows = store.rows(
            "SELECT strategy_version_id, symbol, venue_id, starting_capital FROM tracks "
            "WHERE starting_capital IS NOT NULL"
        )
    else:
        rows = store.rows(
            "SELECT strategy_version_id, starting_capital FROM tracks WHERE starting_capital IS NOT NULL"
        )
    for r in rows:
        vid = r.get("strategy_version_id")
        if not vid:
            continue
        pos = open_by_version.get(vid)
        if pos is None or pos.qty <= 0:
            continue  # flat (or short — funded paper tracks are long spot): nothing to protect
        venue_id = _instrument_venue(cat, pos.instrument_id) or pos.venue
        if not venue_id or venue_id == "sim":
            continue  # can't price/route it honestly
        try:
            starting_capital = Decimal(str(r["starting_capital"]))
        except Exception:  # noqa: BLE001
            continue
        # Cell-keyed ref_id (version:symbol:venue) when the schema carries the cell columns AND the track row
        # has them, else the legacy version-only key — exactly the keys portfolio.mark_to_market writes.
        if has_cells and r.get("symbol") and r.get("venue_id"):
            ref_id = f"{vid}:{r['symbol']}:{r['venue_id']}"
        else:
            ref_id = vid
        equity = _latest_track_equity(store, ref_id)
        if equity is None:
            continue  # never marked → no honest equity to judge (first-funding tick); skip
        floor_guard = min(equity, starting_capital)
        peak = _peak_track_equity(store, ref_id, floor=floor_guard)
        holdings.append(
            _FundedHolding(
                version_id=vid,
                symbol=pos.symbol,
                venue_id=venue_id,
                position=pos,
                equity=equity,
                peak=peak,
                starting_capital=starting_capital,
            )
        )
    return holdings


def _decide(h: _FundedHolding, cfg: GuardConfig) -> GuardAction | None:
    """The protection decision for one funded holding, or None to leave it alone. Capital-preservation
    (LIQUIDATE) is checked FIRST and outranks profit-lock — a floor breach closes the whole position; a
    profit-lock only TRIMS a winner that gave back from its peak."""
    qty = h.position.qty
    # 1) Capital preservation: equity at/below the floor fraction of starting capital → full liquidation.
    if cfg.floor_fraction is not None:
        floor = h.starting_capital * cfg.floor_fraction
        if h.equity <= floor:
            return GuardAction(
                version_id=h.version_id, symbol=h.symbol, venue_id=h.venue_id,
                kind="liquidate", reason="capital_floor", qty=qty,
                equity=h.equity, starting_capital=h.starting_capital, peak=h.peak,
            )
    # 2) Profit-lock: a track whose peak rose above starting capital by >= min_peak_gain and has since given back
    #    more than giveback_fraction from that peak → trim a fraction to lock gains.
    if cfg.giveback_fraction is not None:
        gained = h.peak >= h.starting_capital * (Decimal("1") + cfg.min_peak_gain_fraction)
        gave_back = h.peak > 0 and (h.peak - h.equity) / h.peak >= cfg.giveback_fraction
        if gained and gave_back:
            trim_qty = (qty * cfg.trim_fraction).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            if trim_qty > 0:
                return GuardAction(
                    version_id=h.version_id, symbol=h.symbol, venue_id=h.venue_id,
                    kind="trim", reason="profit_lock", qty=trim_qty,
                    equity=h.equity, starting_capital=h.starting_capital, peak=h.peak,
                )
    return None


def plan(
    store: Store,
    *,
    catalog: VenueCatalog | None = None,
    router=None,  # noqa: ANN001 — orchestrator.loop.PricingRouter
    config: GuardConfig | None = None,
) -> list[GuardAction]:
    """The protective actions the supervisor WOULD take this pass — pure read, no orders. Deterministic for a
    fixed store. Empty list when nothing is funded/held or no track breaches a threshold."""
    cat = catalog or default_catalog()
    cfg = config or DEFAULT_CONFIG
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    actions: list[GuardAction] = []
    for h in _funded_holdings(store, portfolio, cat):
        action = _decide(h, cfg)
        if action is not None:
            actions.append(action)
    return actions


def run_capital_guard(
    store: Store,
    *,
    catalog: VenueCatalog | None = None,
    router=None,  # noqa: ANN001 — orchestrator.loop.PricingRouter
    config: GuardConfig | None = None,
    now: datetime | None = None,
) -> GuardReport:
    """ONE supervisor pass: for every FUNDED track holding an open position, judge its OWN marked equity against
    the floor (liquidate) and profit-lock (trim) thresholds and, on a breach, emit a REDUCE-ONLY order that
    routes through the one order path — live-book positions via their armed venue adapter, sim/paper positions
    deterministically on the sim path. Reduce-only is exempt from caps/kill/regime, so a protection close always
    routes.

    STRICT NO-OP when nothing is live/funded: zero funded tracks (or none holding / none breaching) returns a
    clean empty report without touching the order path. SAFE WHILE LIVE IS OFF: with no armed venue every close
    reduce-fills the SIM/paper book (the same mechanics the paper executor's own exits use) — real money moves
    ONLY once the operator has armed the venue, and even then only ever to REDUCE exposure."""
    cat = catalog or default_catalog()
    cfg = config or DEFAULT_CONFIG
    now = now or datetime.now(tz=UTC)
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    pricer = router or PricingRouter(cat, settings=store.settings)
    report = GuardReport()

    holdings = _funded_holdings(store, portfolio, cat)
    if not holdings:
        return report  # nothing funded/held → clean no-op (never touches the order path)

    actions: list[tuple[_FundedHolding, GuardAction]] = []
    for h in holdings:
        action = _decide(h, cfg)
        if action is not None:
            actions.append((h, action))
    report.evaluated = len(actions)

    _route_and_audit(
        store, actions, portfolio=portfolio, pricer=pricer, catalog=cat, now=now, report=report, actor="master",
    )
    return report


def kill(
    store: Store,
    *,
    scope: str = "all",
    version_id: str | None = None,
    catalog: VenueCatalog | None = None,
    router=None,  # noqa: ANN001 — orchestrator.loop.PricingRouter
    now: datetime | None = None,
) -> GuardReport:
    """The MANUAL operator kill-switch — a FORCED, threshold-free capital-preservation close of every funded
    holding in scope, routed through the SAME reduce-only order path the automatic supervisor uses. This is the
    operator's "stop everything now" backstop: unlike run_capital_guard it does NOT wait for a floor/give-back
    breach — it liquidates the FULL held quantity of each in-scope funded track unconditionally.

      • scope='all' (the default, GLOBAL kill-all) closes every funded holding;
      • scope='combo' (with `version_id` = the combo/track id) closes ONLY that one cell — a sibling track is
        left alone.

    Same money-path guarantees as the automatic guard: every order is REDUCE-ONLY (caps/kill/regime EXEMPT — a
    close is the safety move), routes live ONLY on an armed venue (sim-closes otherwise, byte-identical to the
    paper executor's exits), and is audited as `capital_guard_action` with actor='human'. STRICT NO-OP when
    nothing in scope is funded/held → a clean empty report (never touches the order path). Offline (no mark) a
    holding is skipped rather than closed at a fabricated price."""
    cat = catalog or default_catalog()
    now = now or datetime.now(tz=UTC)
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    pricer = router or PricingRouter(cat, settings=store.settings)
    report = GuardReport()

    holdings = _funded_holdings(store, portfolio, cat)
    if scope == "combo":
        if not version_id:
            return report  # combo scope with no target → nothing to kill (clean no-op, never guess)
        holdings = [h for h in holdings if h.version_id == version_id]
    if not holdings:
        return report  # nothing funded/held in scope → clean no-op (never touches the order path)

    # A FORCED full liquidation per holding — the whole held qty, regardless of any threshold. Reuses the
    # liquidate GuardAction shape so the shared router/audit treats it identically to a floor-breach close.
    actions: list[tuple[_FundedHolding, GuardAction]] = [
        (
            h,
            GuardAction(
                version_id=h.version_id, symbol=h.symbol, venue_id=h.venue_id,
                kind="liquidate", reason="manual_kill", qty=h.position.qty,
                equity=h.equity, starting_capital=h.starting_capital, peak=h.peak,
            ),
        )
        for h in holdings
    ]
    report.evaluated = len(actions)

    _route_and_audit(
        store, actions, portfolio=portfolio, pricer=pricer, catalog=cat, now=now, report=report,
        actor="human", basis_fallback=True,
    )
    return report


def _route_and_audit(
    store: Store,
    actions: list[tuple[_FundedHolding, GuardAction]],
    *,
    portfolio: Portfolio,
    pricer,  # noqa: ANN001 — orchestrator.loop.PricingRouter (or a stub exposing last_price)
    catalog: VenueCatalog,
    now: datetime,
    report: GuardReport,
    actor: str,
    basis_fallback: bool = False,
) -> None:
    """Route a batch of REDUCE-ONLY protective closes through the ONE order path and audit what BOOKED — the
    shared spine of BOTH the automatic supervisor pass (run_capital_guard) and the manual operator kill-switch
    (kill). For each (holding, action): build a reduce-only sell at the latest REAL mark, group by the book/venue
    the close routes to (live-book on an armed venue → its adapter; everything else → the deterministic sim path),
    execute, then count + emit a `capital_guard_action` event for each accepted close. Mutates `report` in place.

    Reduce-only is gauntlet-EXEMPT from caps/kill/regime (closing IS the safety move), so a genuine protective
    close always routes. `actor` tags the audit event so the manual kill-switch is distinguishable from the
    automatic pass on the ledger.

    PRICING: a close fills at the latest REAL mark (never a synthetic price). When offline (no mark):
      • basis_fallback=False (the AUTOMATIC guard) → SKIP the close and defer to the next 4h pass — a threshold
        breach is not urgent enough to close at a stale basis;
      • basis_fallback=True (the MANUAL kill) → fall back to the position's own avg_price (a FLAT close, never a
        fabricated P&L — exactly /live/liquidate's behaviour) so the operator's "stop now" is never silently a
        no-op just because the box is offline; a live fill reconciles to the venue's true price out-of-band."""
    if not actions:
        return

    # LIVE IGNITION (shared with step_tracks): the active adapters per venue when the operator has armed live.
    # Empty unless armed → every close routes SIM (byte-identical to the paper executor's own exits).
    live_adapters = _resolve_live_adapters(store)

    # Build the reduce-only intents, grouped by the book/venue the close routes to.
    sim_intents: list[IntendedOrder] = []
    live_by_venue: dict[str, list[IntendedOrder]] = {}
    meta_by_coid: dict[str, GuardAction] = {}
    for h, action in actions:
        # The close fills at the latest REAL mark. Offline/no mark → the manual kill falls back to the position's
        # basis (a flat close); the automatic guard defers to the next pass rather than invent an exit price.
        mark = pricer.last_price(h.symbol, h.venue_id)
        if mark <= 0:
            if basis_fallback and h.position.avg_price > 0:
                mark = h.position.avg_price
            else:
                continue
        stamp = now.date().isoformat()
        coid = f"guard-{action.reason}-{h.version_id}-{stamp}"
        routes_live = h.position.venue in _LIVE_BOOKS and h.venue_id in live_adapters
        intent = IntendedOrder(
            strategy_version_id=h.version_id,
            symbol=h.symbol,
            venue_id=h.venue_id,
            side=-1,
            qty=action.qty,
            price=mark,
            stop_loss=None,
            take_profit=None,
            conviction=Decimal("0.5"),
            gate_passed=True,
            client_order_id=coid,
            reduce_only=True,
        )
        meta_by_coid[coid] = action
        if routes_live:
            live_by_venue.setdefault(h.venue_id, []).append(intent)
        else:
            sim_intents.append(intent)

    if not sim_intents and not live_by_venue:
        return

    outcome_by_coid: dict[str, OrderOutcome] = {}
    if sim_intents:
        for oc in execute_orders(
            sim_intents, live_enabled=False, kill_switch=False, adapter=None,
            store=store, portfolio=portfolio, risk=store.settings.risk, catalog=catalog,
        ):
            outcome_by_coid[oc.client_order_id] = oc
    if live_by_venue:
        from cosmu.master.scheduler import is_paused  # local: avoid an import cycle

        kill = is_paused(store)  # an operator pause freezes live routing (orders fail safe to sim)
        for venue_id, group in live_by_venue.items():
            adapter = live_adapters.get(venue_id)
            if adapter is None:  # defensive: routed live only for armed venues
                continue
            for oc in execute_orders(
                group, live_enabled=True, kill_switch=kill, adapter=adapter,
                store=store, portfolio=portfolio, risk=store.settings.risk, catalog=catalog,
            ):
                outcome_by_coid[oc.client_order_id] = oc

    # Audit + count only what actually BOOKED. A reduce-only that the gauntlet still rejected (e.g. it would not
    # genuinely reduce) was audited by the order path — it must not appear here as a protection that happened.
    for coid, action in meta_by_coid.items():
        oc = outcome_by_coid.get(coid)
        if oc is None or not oc.accepted:
            continue
        report.protected += 1
        record = {
            "version_id": action.version_id,
            "symbol": action.symbol,
            "venue_id": action.venue_id,
            "kind": action.kind,
            "reason": action.reason,
            "qty": str(action.qty),
            "equity": str(action.equity),
            "starting_capital": str(action.starting_capital),
            "peak": str(action.peak),
            "routed_live": oc.routed_live,
            "venue": oc.venue,
        }
        report.actions.append(record)
        store.append_event(
            actor=actor,
            kind="capital_guard_action",
            ref_type="strategy_version",
            ref_id=action.version_id,
            payload=record,
        )


def main() -> int:
    """The cron entry (`python -m cosmu.ops.capital_guard`, wired into the Modal `tick`): run ONE automatic
    supervisor pass over the live book. STRICT NO-OP until a venue is armed AND a funded track breaches a
    threshold — with nothing funded/held this returns 0 having touched no order path. Returns 0 always (a guard
    pass that protected 0 positions is the healthy steady state, not an error); prints a one-line summary so the
    Modal run log shows what it did."""
    from cosmu.config.settings import Settings

    store = Store(Settings())
    report = run_capital_guard(store)
    print(f"[capital_guard] evaluated={report.evaluated} protected={report.protected}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
