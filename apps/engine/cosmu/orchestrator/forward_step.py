# intent: THE FORWARD-TEST EXECUTOR — make a funded track a GENUINE forward test by running each survivor's OWN
# strategy logic forward on the latest real bars, every clock tick. Before this module existed the funder opened
# one static long and the clock only re-marked it, so `live_ready` measured buy-and-hold of the first signal —
# not the strategy. Now each gate-lane track's persisted spec + FITTED params are re-evaluated with the SAME
# machinery the Gate screened them with (_feature_matrix/_entry_signal/_exit_signal + the PIT alt join): a held
# position exits on its own stop / take / time-stop / signal-exit, and a flat track re-enters when its entry
# signal fires — all through the ONE order path (fees + sim slippage + gauntlet + audit). inputs: the store + the
# asset-aware PricingRouter; outputs: real closes/opens (executions, positions) + audited events. invariants:
# SIM only (live stays OFF here); deploy-lane tracks (documented rotation arms) are SKIPPED — their arm modules
# own rotation; a spec/params/bars failure is an HONEST skip (mark-only), never a fabricated trade; exits are
# decided on the latest CLOSED bar and filled at the latest close via the order path (no intrabar hindsight
# fills); deterministic for a fixed store + bars; offline-safe (no bars → no action this tick).

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from cosmu.data.alt_join import build_alt_by_symbol, resolve_alt_store
from cosmu.data.backtest import (
    _entry_signal,
    _exit_signal,
    _feature_matrix,
    _setup_entry_gate,
    _warmup_bars,
)
from cosmu.knowledge.store import Store
from cosmu.master.drift import monitor_drift
from cosmu.master.execution import IntendedOrder, execute_orders
from cosmu.master.portfolio import Portfolio, PositionView
from cosmu.orchestrator.loop import PricingRouter, _instrument_venue
from cosmu.spine.venue import VenueCatalog, default_catalog
from cosmu.strategy.spec import StrategySpec

# Fallback brackets used ONLY when a track re-enters and its fitted stop/take params are missing from the
# persisted row (historical rows) — the same conservative protective structure the funder uses, NOT edge numbers.
_FALLBACK_STOP = Decimal("0.95")
_FALLBACK_TAKE = Decimal("1.10")


@dataclass
class StepReport:
    """One executor tick, honestly counted. `managed` = gate-lane tracks whose own logic was evaluated;
    deploy-lane (documented rotation arms) and unmanageable rows are SKIPPED and say so."""

    managed: int = 0
    closed: int = 0
    opened: int = 0
    skipped_deploy: int = 0
    skipped_unmanaged: int = 0
    exits: list[dict] = field(default_factory=list)   # {version_id, symbol, reason, price}
    entries: list[dict] = field(default_factory=list)  # {version_id, symbol, price}


@dataclass(frozen=True)
class _Managed:
    """One executor-managed track resolved to everything its evaluation needs. `venue_id` is the REAL catalog
    venue (binance/ibkr/…) recovered from the position's instrument — positions persist venue='sim' for paper
    fills, which is a fill-ledger label, not a pricing/catalog venue. `liquidate_reason` set ⇒ the position
    closes unconditionally at the next mark (killed version) — no spec evaluation, just the exit."""

    version_id: str
    spec: StrategySpec | None
    params: dict[str, float]
    symbol: str
    venue_id: str
    position: PositionView | None  # None ⇒ flat (re-entry candidate)
    liquidate_reason: str | None = None


def _load_spec_params(store: Store, version_id: str) -> tuple[StrategySpec, dict[str, float]] | None:
    """The persisted spec + FITTED params for a version — the exact hypothesis the Gate passed. Params drop
    non-numeric carriers (config_tag); missing fitted params fall back to fit_params(spec) (mid-of-space, the
    same fallback the finder persists with). None when the row/spec is missing or unparsable — the caller
    skips honestly (mark-only) rather than inventing logic for a position it can't explain."""
    row = store.row("SELECT spec, params, status FROM strategy_versions WHERE id = ?", (version_id,))
    if row is None or row.get("status") not in ("forward_test", "live"):
        return None
    raw_spec, raw_params = row.get("spec"), row.get("params")
    try:
        spec_dict = json.loads(raw_spec) if isinstance(raw_spec, str) else raw_spec
        spec = StrategySpec.model_validate(spec_dict)
    except Exception:  # noqa: BLE001 — a historical/minimal spec that can't parse is an honest skip
        return None
    params: dict[str, float] = {}
    try:
        params_dict = json.loads(raw_params) if isinstance(raw_params, str) else (raw_params or {})
        for k, v in dict(params_dict).items():
            try:
                params[k] = float(v)
            except (TypeError, ValueError):
                continue  # config_tag and friends — carriers, not knobs
    except (ValueError, TypeError):
        params = {}
    if not params:
        from cosmu.evolution.loop import fit_params

        params = fit_params(spec)
    return spec, params


def _bracket_fractions(spec: StrategySpec, params: dict[str, float]) -> tuple[float | None, float | None]:
    """The track's OWN fitted stop/take distances (fractions), or None per leg when the param is missing —
    that leg is then honestly unenforced rather than guessed."""
    stop = params.get(spec.exit.stop_loss.param)
    take = params.get(spec.exit.take_profit.param)
    stop_f = float(stop) if stop is not None and float(stop) > 0 else None
    take_f = float(take) if take is not None and float(take) > 0 else None
    return stop_f, take_f


def _entry_ts(store: Store, version_id: str, instrument_id: str) -> datetime | None:
    """When the CURRENT leg was opened: the latest BUY execution for this (version, instrument). Used for the
    spec's time-stop. None (no execution on file — e.g. an arm-opened fill predating the executor) ⇒ no
    time-stop this tick (honest: never guess an entry time)."""
    row = store.row(
        "SELECT MAX(ts) AS ts FROM executions WHERE strategy_version_id = ? AND instrument_id = ? AND side = 'buy'",
        (version_id, instrument_id),
    )
    if not row or not row.get("ts"):
        return None
    try:
        ts = datetime.fromisoformat(str(row["ts"]))
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    except ValueError:
        return None


def _exit_reason(
    m: _Managed,
    store: Store,
    bars: list,  # noqa: ANN001 — list[Bar]
    features: dict[str, list[float | None]],
    now: datetime,
) -> str | None:
    """Why the held position should close NOW, judged by the strategy's OWN rules on the latest closed bar —
    or None to keep holding. Worst-case priority mirrors the backtest: stop first, then take, time, signal."""
    pos = m.position
    assert pos is not None
    mark = bars[-1].close
    basis = pos.avg_price
    stop_f, take_f = _bracket_fractions(m.spec, m.params)
    if stop_f is not None and mark <= basis * (Decimal("1") - Decimal(str(stop_f))):
        return "stop_loss"
    if take_f is not None and mark >= basis * (Decimal("1") + Decimal(str(take_f))):
        return "take_profit"
    entry_ts = _entry_ts(store, m.version_id, pos.instrument_id)
    if entry_ts is not None and (now - entry_ts).days >= m.spec.horizon.max_hold_days:
        return "time_stop"
    if _exit_signal(m.spec, m.params, features, len(bars) - 1):
        return "signal_exit"
    return None


def _managed_tracks(store: Store, portfolio: Portfolio, cat: VenueCatalog) -> tuple[list[_Managed], StepReport]:
    """Resolve every executor-managed track: held sim positions (exit candidates) plus flat-but-funded gate-lane
    tracks (re-entry candidates). Deploy-lane specs are counted + skipped — their arm modules own rotation."""
    report = StepReport()
    held = {p.strategy_version_id: p for p in portfolio.positions() if p.strategy_version_id and p.venue == "sim"}
    flat_rows = store.rows(
        "SELECT DISTINCT strategy_version_id, symbol, instrument_id FROM positions "
        "WHERE CAST(qty AS REAL) = 0 AND strategy_version_id IS NOT NULL AND venue = 'sim'"
    )
    out: list[_Managed] = []
    seen: set[str] = set()
    for vid, pos, symbol, instrument_id in (
        [(vid, p, p.symbol, p.instrument_id) for vid, p in held.items()]
        + [(r["strategy_version_id"], None, r["symbol"], r["instrument_id"]) for r in flat_rows]
    ):
        if vid in seen:
            continue
        seen.add(vid)
        loaded = _load_spec_params(store, vid)
        if loaded is None:
            # Distinguish DEAD (version killed/graveyarded/vanished) from ALIVE-but-unparsable (historical
            # minimal spec): a dead strategy's HELD position must not march on accruing P&L forever — it
            # LIQUIDATES at the next mark. An alive track whose spec can't parse stays mark-only (honest
            # skip — never invent logic for it), and flat dead rows just stay skipped.
            status_row = store.row("SELECT status FROM strategy_versions WHERE id = ?", (vid,))
            dead = status_row is None or status_row.get("status") not in ("forward_test", "live")
            if pos is not None and dead:
                venue_id = _instrument_venue(cat, instrument_id)
                if venue_id is not None:
                    out.append(_Managed(vid, None, {}, symbol, venue_id, pos, liquidate_reason="version_killed"))
                    continue
            report.skipped_unmanaged += 1
            continue
        spec, params = loaded
        if spec.lane == "deploy":
            report.skipped_deploy += 1
            continue
        if getattr(spec, "direction", 1) == -1:
            report.skipped_unmanaged += 1  # funded tracks are long spot; a short spec can't be managed here
            continue
        venue_id = _instrument_venue(cat, instrument_id)
        if venue_id is None:
            report.skipped_unmanaged += 1  # unknown instrument → can't price/order it honestly
            continue
        out.append(_Managed(vid, spec, params, symbol, venue_id, pos))
    return out, report


def step_tracks(
    store: Store,
    *,
    catalog: VenueCatalog | None = None,
    router=None,  # noqa: ANN001 — orchestrator.loop.PricingRouter (import-cycle-free at runtime)
    now: datetime | None = None,
) -> StepReport:
    """ONE executor tick: for every gate-lane funded track, re-evaluate ITS OWN spec + fitted params on the
    latest real bars and act — close a held position on its stop/take/time/signal exit, open a flat track when
    its entry signal fires (drift-defunded tracks excepted). Every fill goes through the one order path (fees,
    sim slippage, gauntlet, audit). Run BEFORE mark_tracks so the marked snapshot reflects post-trade state."""
    cat = catalog or default_catalog()
    pricer = router or PricingRouter(cat)
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    now = now or datetime.now(tz=UTC)

    tracks, report = _managed_tracks(store, portfolio, cat)
    if not tracks:
        return report

    # Drift verdicts now have TEETH: a defunded HELD track is closed this tick (master/drift's documented
    # intent — "capital is pulled BEFORE realized P&L turns" — was only ever a recommendation while nothing
    # could close a position), and a defunded FLAT track is not re-entered by its next signal. Exits are
    # never blocked. Insufficient history ⇒ no defund, same as the funder.
    all_ids = [m.version_id for m in tracks if m.liquidate_reason is None]
    defunded = {v.ref_id for v in monitor_drift(store, all_ids) if v.defund} if all_ids else set()

    alt_store = resolve_alt_store(store.settings, store)
    per_track_capital = store.settings.sim_track_capital
    intents: list[IntendedOrder] = []

    def _close(m: _Managed, mark: Decimal, reason: str) -> None:
        intents.append(
            IntendedOrder(
                strategy_version_id=m.version_id,
                symbol=m.symbol,
                venue_id=m.venue_id,
                side=-1,
                qty=m.position.qty,
                price=mark,
                stop_loss=None,
                take_profit=None,
                conviction=Decimal(str(m.spec.risk.conviction)) if m.spec is not None else Decimal("0.5"),
                gate_passed=True,
                reduce_only=True,
            )
        )
        report.closed += 1
        report.exits.append({"version_id": m.version_id, "symbol": m.symbol, "reason": reason, "price": str(mark)})
        store.append_event(
            actor="master",
            kind="forward_exit",
            ref_type="strategy_version",
            ref_id=m.version_id,
            payload={"symbol": m.symbol, "reason": reason, "qty": str(m.position.qty), "price": str(mark)},
        )

    for m in tracks:
        report.managed += 1
        if m.liquidate_reason is not None:
            # Dead version, held position: liquidate at the latest real mark — no spec to evaluate. A missing
            # mark (offline) defers to the next tick rather than inventing an exit price.
            mark = pricer.last_price(m.symbol, m.venue_id)
            if mark > 0:
                _close(m, mark, m.liquidate_reason)
            continue
        provider = pricer.provider_for(m.symbol, m.venue_id)
        limit = min(max(_warmup_bars(m.spec, m.params) + 10, 60), 500)
        try:
            bars = provider.fetch_bars(m.symbol, m.spec.horizon.bar_size, limit=limit)
        except Exception:  # noqa: BLE001 — offline/no data this tick → hold/stay flat (mark-only), never guess
            bars = []
        if len(bars) < 3 or bars[-1].close <= 0:
            continue
        alt_by_symbol = build_alt_by_symbol(alt_store, m.spec, {m.symbol: bars})
        alt = (alt_by_symbol or {}).get(m.symbol)
        features = _feature_matrix(m.spec, m.params, bars, alt)
        i = len(bars) - 1
        mark = bars[-1].close

        if m.position is not None:
            # An anticipatory drift defund outranks the spec's own exits — the edge the track was funded on
            # is measurably gone, so capital is pulled NOW rather than waiting for a bracket to trip.
            reason = "drift_defund" if m.version_id in defunded else _exit_reason(m, store, bars, features, now)
            if reason is None:
                continue
            _close(m, mark, reason)
        else:
            if m.version_id in defunded:
                continue
            highs = [float(b.high) for b in bars]
            lows = [float(b.low) for b in bars]
            closes = [float(b.close) for b in bars]
            setup_ok = _setup_entry_gate(m.spec, m.params, highs, lows, closes)
            if not (setup_ok[i] and _entry_signal(m.spec, m.params, features, i)):
                continue
            qty = (per_track_capital / mark).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            if qty <= 0:
                continue
            stop_f, take_f = _bracket_fractions(m.spec, m.params)
            stop = mark * (Decimal("1") - Decimal(str(stop_f))) if stop_f is not None else mark * _FALLBACK_STOP
            take = mark * (Decimal("1") + Decimal(str(take_f))) if take_f is not None else mark * _FALLBACK_TAKE
            intents.append(
                IntendedOrder(
                    strategy_version_id=m.version_id,
                    symbol=m.symbol,
                    venue_id=m.venue_id,
                    side=1,
                    qty=qty,
                    price=mark,
                    stop_loss=stop.quantize(Decimal("0.01")),
                    take_profit=take.quantize(Decimal("0.01")),
                    conviction=Decimal(str(m.spec.risk.conviction)),
                    gate_passed=True,
                )
            )
            report.opened += 1
            report.entries.append({"version_id": m.version_id, "symbol": m.symbol, "price": str(mark)})
            store.append_event(
                actor="master",
                kind="forward_entry",
                ref_type="strategy_version",
                ref_id=m.version_id,
                payload={"symbol": m.symbol, "qty": str(qty), "price": str(mark)},
            )

    if intents:
        execute_orders(
            intents,
            live_enabled=False,  # the executor is SIM-only; live exits stay with the live lane
            kill_switch=False,
            adapter=None,
            store=store,
            portfolio=portfolio,
            risk=store.settings.risk,
            catalog=cat,
        )
    store.append_event(
        actor="master",
        kind="forward_stepped",
        ref_type="portfolio",
        ref_id="aggregate",
        payload={
            "managed": report.managed,
            "closed": report.closed,
            "opened": report.opened,
            "skipped_deploy": report.skipped_deploy,
            "skipped_unmanaged": report.skipped_unmanaged,
        },
    )
    return report
