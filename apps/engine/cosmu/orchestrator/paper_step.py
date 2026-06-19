# intent: THE PAPER EXECUTOR — make a funded track a GENUINE paper run by running each survivor's OWN
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
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from cosmu.data.alt_join import build_alt_by_symbol, resolve_alt_store
from cosmu.data.backtest import (
    _entry_signal,
    _exit_signal,
    _feature_matrix,
    _setup_entry_gate,
    _warmup_bars,
)
from cosmu.data.market import _cache_is_fresh, _equity_cache_is_fresh
from cosmu.knowledge.lifecycle_status import ALIVE_STATUSES
from cosmu.knowledge.store import Store, tracks_has_cell_columns, tracks_has_exposure_factor
from cosmu.master.drift import monitor_drift
from cosmu.master.execution import (
    IntendedOrder,
    OrderOutcome,
    _already_filled,
    execute_orders,
    reconcile_fills,
)
from cosmu.master.portfolio import Portfolio, PositionView
from cosmu.master.sizing import size_fraction
from cosmu.orchestrator.loop import PricingRouter, _instrument_venue
from cosmu.spine.venue import VenueCatalog, default_catalog
from cosmu.strategy.spec import StrategySpec

# Fallback brackets used ONLY when a track re-enters and its fitted stop/take params are missing from the
# persisted row (historical rows) — the same conservative protective structure the funder uses, NOT edge numbers.
_FALLBACK_STOP = Decimal("0.95")
_FALLBACK_TAKE = Decimal("1.10")

# Statuses that are ALIVE in the forward test — a version the executor still steps forward (vs killed/lab/gone,
# which it stops stepping and liquidates). "screened" is included: a paper entrant is born "screened"
# (badge: Backtest) and IS actively paper-trading — the paper clock promotes it to "paper" once it accrues a
# real forward day. Omitting it would freeze every new survivor's clock (never stepped → never promoted).
_ALIVE_STATUSES = tuple(sorted(ALIVE_STATUSES))


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
    # `status` is the strategy_version status; `routing` is where THIS track's fills go this tick: "sim" (the
    # default paper book) or "live" (status='live' on an armed venue → real CLOB/exchange order). The
    # managed `position` is read from the matching book, so a live track exits its live position and a
    # paper track exits its sim position.
    status: str = "screened"
    routing: str = "sim"


def _load_spec_params(store: Store, version_id: str) -> tuple[StrategySpec, dict[str, float], str] | None:
    """The persisted spec + FITTED params + STATUS for a version — the exact hypothesis the Gate passed. Params
    drop non-numeric carriers (config_tag); missing fitted params fall back to fit_params(spec) (mid-of-space,
    the same fallback the finder persists with). The status is returned so the executor can route a 'live'
    track's fills to its real venue adapter. None when the row/spec is missing or unparsable — the caller skips
    honestly (mark-only) rather than inventing logic for a position it can't explain."""
    row = store.row("SELECT spec, params, status FROM strategy_versions WHERE id = ?", (version_id,))
    if row is None or row.get("status") not in _ALIVE_STATUSES:
        return None
    status = str(row.get("status"))
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
    return spec, params, status


def _frozen_config_ok(store: Store, version_id: str, params: dict[str, float]) -> bool:
    """True when a NEW live ENTRY may open for this version: it has a frozen promotion record whose params_hash
    matches the numeric params the executor is about to trade. Refuses (False) on a MISSING record OR a hash
    MISMATCH — so a real position only ever opens on the EXACT config the Gate proved, never a silently re-fitted
    one (master/promotion freezes it at promotion; this is the read side). Exits of an existing live leg are
    NEVER gated by this — a close must never be trapped behind a config check."""
    from cosmu.master.promotion import params_hash, promotion_record

    record = promotion_record(store, version_id)
    if not record or not record.get("params_hash"):
        return False
    return params_hash(params) == record["params_hash"]


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


def _managed_tracks(
    store: Store, portfolio: Portfolio, cat: VenueCatalog, *, armed_venues: frozenset[str] = frozenset()
) -> tuple[list[_Managed], StepReport]:
    """Resolve every executor-managed track: held positions (exit candidates) plus flat-but-funded gate-lane
    tracks (re-entry candidates). Deploy-lane specs are counted + skipped — their arm modules own rotation.

    Book-aware for live ignition: positions are read from BOTH the sim book and the live/testnet book. A track
    whose status is 'live' AND whose venue is in `armed_venues` (live toggle on + that venue's adapter active)
    is routed LIVE and managed on its live book; everything else is routed SIM and managed on its sim book
    exactly as before. When `armed_venues` is empty (no toggle / no keys — every existing run) this is
    identical to the prior sim-only behaviour. A live position whose venue is NOT armed (keys pulled / live
    off) is left UNMANAGED this tick (an honest skip + event) — never closed via a fake sim fill."""
    report = StepReport()
    positions = portfolio.positions()
    held_sim = {p.strategy_version_id: p for p in positions if p.strategy_version_id and p.venue == "sim"}
    held_live = {
        p.strategy_version_id: p
        for p in positions
        if p.strategy_version_id and p.venue in ("live", "testnet")
    }
    flat_rows = store.rows(
        "SELECT DISTINCT strategy_version_id, symbol, instrument_id FROM positions "
        "WHERE CAST(qty AS REAL) = 0 AND strategy_version_id IS NOT NULL AND venue = 'sim'"
    )
    out: list[_Managed] = []
    seen: set[str] = set()
    # Candidates: every track with an open position (live first so a real leg wins over a stale sim row), then
    # flat funded registration rows (re-entry candidates). `book` records which book the candidate position is in.
    candidates = (
        [(vid, p, p.symbol, p.instrument_id, "live") for vid, p in held_live.items()]
        + [(vid, p, p.symbol, p.instrument_id, "sim") for vid, p in held_sim.items()]
        + [(r["strategy_version_id"], None, r["symbol"], r["instrument_id"], "sim") for r in flat_rows]
    )
    for vid, pos, symbol, instrument_id, book in candidates:
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
            dead = status_row is None or status_row.get("status") not in _ALIVE_STATUSES
            if pos is not None and dead:
                venue_id = _instrument_venue(cat, instrument_id)
                # A dead LIVE leg can only be liquidated on the venue if it is still armed; otherwise leave it
                # unmanaged (skip) rather than fake-close it on the sim book.
                if venue_id is not None and (book != "live" or venue_id in armed_venues):
                    out.append(_Managed(vid, None, {}, symbol, venue_id, pos, liquidate_reason="version_killed", routing=book))
                    continue
            report.skipped_unmanaged += 1
            continue
        spec, params, status = loaded
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
        # A real (live/testnet) position on a venue that is NOT armed right now can't be managed safely (no
        # active adapter to close it) — skip + audit, never close it via a sim fill.
        if held_live.get(vid) is not None and venue_id not in armed_venues:
            report.skipped_unmanaged += 1
            store.append_event(
                actor="master", kind="live_position_unmanaged", ref_type="strategy_version", ref_id=vid,
                payload={"symbol": symbol, "venue_id": venue_id, "reason": "venue_not_armed"},
            )
            continue
        live_pos = held_live.get(vid)
        if live_pos is not None:
            # A real (live/testnet) position is ALWAYS managed on its own book and routed live — exitable on
            # its own rules regardless of the current status, so a live→paper demotion can never orphan an
            # open real position. (We only reach here armed: the unarmed-live case skipped above.) NEVER gated
            # by the freeze check — a close must never be trapped.
            routing, book_pos = "live", live_pos
        elif status == "live" and venue_id in armed_venues and _frozen_config_ok(store, vid, params):
            # Flat live track → its entry signal opens on the live book, but ONLY on the EXACT frozen proven
            # config (params_hash matches the promotion record) — live replicates what the Gate proved.
            routing, book_pos = "live", None
        elif status == "live" and venue_id in armed_venues:
            # status='live' + armed, but the config drifted from / lacks the frozen promotion record → do NOT
            # open a REAL position on an unproven config. Route SIM this tick + audit (re-promote to refreeze).
            store.append_event(
                actor="master", kind="live_entry_blocked_unfrozen", ref_type="strategy_version", ref_id=vid,
                payload={"symbol": symbol, "venue_id": venue_id, "reason": "params_hash_mismatch_or_missing"},
            )
            routing, book_pos = "sim", held_sim.get(vid)
        else:
            routing, book_pos = "sim", held_sim.get(vid)  # paper / not-yet-armed → sim book (unchanged)
        out.append(_Managed(vid, spec, params, symbol, venue_id, book_pos, status=status, routing=routing))
    return out, report


def _resolve_live_adapters(store: Store) -> dict[str, object]:
    """The ACTIVE execution adapter per venue when live is armed — the live-ignition switch. Returns {} (so the
    executor is SIM-only, unchanged) unless BOTH (a) the global live toggle is ON in the DB AND (b) a venue's
    adapter resolves active (keys present + live.mode=='real' / testnet keys). Resolving an adapter is itself
    safe — a venue without keys/mode yields a disabled adapter that is filtered out here — so this can never
    arm anything by itself; it only HANDS the order path a real adapter when the operator has already armed."""
    row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    if not (row and row["enabled"]):
        return {}
    from cosmu.adapters.exec.registry import EXEC_ADAPTER_VENUES, adapter_for

    out: dict[str, object] = {}
    for venue_id in EXEC_ADAPTER_VENUES:
        adapter = adapter_for(venue_id, store.settings)
        if adapter is not None and getattr(adapter, "active", False):
            out[venue_id] = adapter
    return out


def step_tracks(
    store: Store,
    *,
    catalog: VenueCatalog | None = None,
    router=None,  # noqa: ANN001 — orchestrator.loop.PricingRouter (import-cycle-free at runtime)
    now: datetime | None = None,
    bar_sizes: set[str] | frozenset[str] | None = None,
) -> StepReport:
    """ONE executor tick: for every gate-lane funded track, re-evaluate ITS OWN spec + fitted params on the
    latest real bars and act — close a held position on its stop/take/time/signal exit, open a flat track when
    its entry signal fires (drift-defunded tracks excepted). Every fill goes through the one order path (fees,
    sim slippage, gauntlet, audit). Run BEFORE mark_tracks so the marked snapshot reflects post-trade state.

    `bar_sizes` scopes the tick to tracks whose spec trades those horizons (the HOURLY intraday lane passes
    {"1h","4h"}): a sub-daily crypto track reacts within ~an hour of its bar close instead of once a day, while
    daily/equity tracks — whose Yahoo source serves an in-progress day bar with no closed-candle guard — stay
    on the daily clock. Liquidations (dead versions, no spec) also stay on the daily clock. None = all tracks
    (the daily full clock; unchanged behaviour). Re-running on the same closed bar is a no-op either way — the
    client_order_id is stamped with the decision bar."""
    cat = catalog or default_catalog()
    # settings → the equity mark leg prefers Alpaca when keyed, else keyless Yahoo (see PricingRouter).
    pricer = router or PricingRouter(cat, settings=store.settings)
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    now = now or datetime.now(tz=UTC)

    # LIVE IGNITION: the active execution adapters per venue when live is armed (DB toggle on + keys + mode).
    # Empty unless the operator has armed live — so this tick is SIM-only and byte-identical to before by default.
    live_adapters = _resolve_live_adapters(store)
    tracks, report = _managed_tracks(store, portfolio, cat, armed_venues=frozenset(live_adapters))
    if bar_sizes is not None:
        tracks = [m for m in tracks if m.spec is not None and m.spec.horizon.bar_size in bar_sizes]
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
    # Each pending order carries its report metadata. Counts + forward_exit/forward_entry events are emitted
    # ONLY for fills the order path ACCEPTED — a gauntlet-rejected order must never put a phantom trade in the
    # ledger (the rejection itself is audited by the order path). The client_order_id is stamped with the
    # DECISION BAR, so re-running the executor on the same bars is a true no-op (no double fills, no churn).
    pending: list[tuple[IntendedOrder, str, dict, str]] = []

    def _close(m: _Managed, fill: Decimal, reason: str, stamp: str) -> None:
        coid = f"fstep-{m.version_id}-close-{stamp}"
        if _already_filled(store, coid):
            return
        pending.append(
            (
                IntendedOrder(
                    strategy_version_id=m.version_id,
                    symbol=m.symbol,
                    venue_id=m.venue_id,
                    side=-1,
                    qty=m.position.qty,
                    price=fill,
                    stop_loss=None,
                    take_profit=None,
                    conviction=Decimal(str(m.spec.risk.conviction)) if m.spec is not None else Decimal("0.5"),
                    gate_passed=True,
                    client_order_id=coid,
                    reduce_only=True,
                ),
                "exit",
                {"version_id": m.version_id, "symbol": m.symbol, "reason": reason,
                 "price": str(fill), "qty": str(m.position.qty)},
                m.routing,
            )
        )

    for m in tracks:
        report.managed += 1
        if m.liquidate_reason is not None:
            # Dead version, held position: liquidate at the latest real mark — no spec to evaluate. A missing
            # mark (offline) defers to the next tick rather than inventing an exit price.
            mark = pricer.last_price(m.symbol, m.venue_id)
            if mark > 0:
                _close(m, mark, m.liquidate_reason, now.date().isoformat())
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
            fill = mark
            if reason == "take_profit":
                # A real OCO fills AT the take limit, never beyond it — booking the close's overshoot would
                # flatter the paper run vs the screen that funded it. The stop side stays at the observed
                # close (worse than the stop level when price gapped through — honestly pessimistic).
                _, take_f = _bracket_fractions(m.spec, m.params)
                fill = min(mark, m.position.avg_price * (Decimal("1") + Decimal(str(take_f))))
            _close(m, fill, reason, bars[-1].ts.isoformat())
        else:
            if m.version_id in defunded:
                continue
            if _already_filled(store, f"fstep-{m.version_id}-close-{bars[-1].ts.isoformat()}"):
                continue  # exited on THIS bar — the screen convention never re-enters the bar it exited
            highs = [float(b.high) for b in bars]
            lows = [float(b.low) for b in bars]
            closes = [float(b.close) for b in bars]
            setup_ok = _setup_entry_gate(m.spec, m.params, highs, lows, closes)
            if not (setup_ok[i] and _entry_signal(m.spec, m.params, features, i)):
                continue
            # Resolve the instrument once: feeds both the data-recency guard (asset-aware) and tick-size
            # bracket quantization below. Degrade-safe — a missing instrument never blocks (defaults preserve
            # prior behaviour: fresh + cent ticks).
            try:
                _instr = cat.instrument(m.symbol, m.venue_id)
            except KeyError:
                _instr = None
            # DATA RECENCY: activates the risk.py `stale_data` gauntlet check, previously DEAD on this path
            # (IntendedOrder.data_fresh defaulted True and was never set). A dark/offline cron serves a covering
            # but STALE bar cache rather than raising, so without this an entry could fill at a multi-day-old
            # price. Asset-aware: equity daily bars live on the US-session clock (weekend/holiday gaps are normal,
            # not stale), crypto on the closed-candle 2*period clock — same logic the providers cache on. The
            # reduce_only CLOSE is never freshness-gated (default True), so a stale tick can never TRAP an exit.
            _is_equity_daily = _instr is not None and _instr.asset_class == "equity" and m.spec.horizon.bar_size == "1d"
            data_fresh = (
                _equity_cache_is_fresh(bars, now) if _is_equity_daily
                else _cache_is_fresh(bars, m.spec.horizon.bar_size, now)
            )
            # SIZING PARITY (audit #7): T1 when target_vol is frozen on this track, T0 otherwise.
            # T1 vol-target: scale with current realized vol vs the strategy's frozen baseline. CELL-SCOPED when
            # the per-cell columns are live (a version with multiple cells reads THIS cell's own anchor), else the
            # legacy version-only read. `exposure_factor` (crowding cap, master/crowding) is read on the SAME row
            # and multiplied into the sized fraction below — NULL/absent → 1.0 (no cap), so behaviour is unchanged
            # until the crowding overlay sets it for a redundant cluster member.
            _has_cap = tracks_has_exposure_factor(store)
            _cap_sel = ", exposure_factor" if _has_cap else ""
            if tracks_has_cell_columns(store):
                _tv_row = store.row(
                    f"SELECT target_vol{_cap_sel} FROM tracks "
                    "WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
                    (m.version_id, m.symbol, m.venue_id),
                )
            else:
                _tv_row = store.row(
                    f"SELECT target_vol{_cap_sel} FROM tracks WHERE strategy_version_id = ?", (m.version_id,)
                )
            _target_vol = float(_tv_row["target_vol"]) if _tv_row and _tv_row.get("target_vol") is not None else None
            # Crowding exposure cap (portfolio risk, post-gate): scales the sized fraction DOWN for a redundant
            # cluster member. Default 1.0 (no row, no column, or NULL) so the un-crowded path is byte-identical.
            _exposure = (
                float(_tv_row["exposure_factor"])
                if _has_cap and _tv_row and _tv_row.get("exposure_factor") is not None
                else 1.0
            )
            frac = Decimal(str(size_fraction(m.spec, closes=closes, target_vol=_target_vol))) * Decimal(str(_exposure))
            qty = (per_track_capital * frac / mark).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            if qty <= 0:
                continue
            coid = f"fstep-{m.version_id}-open-{bars[-1].ts.isoformat()}"
            if _already_filled(store, coid):
                continue
            stop_f, take_f = _bracket_fractions(m.spec, m.params)
            stop = mark * (Decimal("1") - Decimal(str(stop_f))) if stop_f is not None else mark * _FALLBACK_STOP
            take = mark * (Decimal("1") + Decimal(str(take_f))) if take_f is not None else mark * _FALLBACK_TAKE
            # Quantize brackets to the instrument's REAL tick_size, not a hardcoded $0.01 (which is coarser
            # than a cheap asset's true tick — e.g. XRP ticks at 0.0001 — distorting/invalidating the level).
            # Stop rounds DOWN, take rounds UP — always AWAY from entry, so tick rounding can never invert a
            # bracket through the entry price (which would trip validate_order's invalid_stop_loss/take).
            _tick = _instr.tick_size if _instr is not None else Decimal("0.01")
            pending.append(
                (
                    IntendedOrder(
                        strategy_version_id=m.version_id,
                        symbol=m.symbol,
                        venue_id=m.venue_id,
                        side=1,
                        qty=qty,
                        price=mark,
                        stop_loss=stop.quantize(_tick, rounding=ROUND_DOWN),
                        take_profit=take.quantize(_tick, rounding=ROUND_UP),
                        conviction=Decimal(str(m.spec.risk.conviction)),
                        gate_passed=True,
                        client_order_id=coid,
                        data_fresh=data_fresh,
                    ),
                    "entry",
                    {"version_id": m.version_id, "symbol": m.symbol, "price": str(mark), "qty": str(qty)},
                    m.routing,
                )
            )

    if pending:
        # Two lanes through the ONE order path. SIM intents (paper) fill deterministically with no
        # adapter, exactly as before. LIVE intents (status='live' on an armed venue) route through that
        # venue's real adapter with the toggle ON — execute_orders' 5 interlocks (gate-passed, caps,
        # kill-switch, adapter.active, regime) still decide sim-vs-live per order, so a mis-set flag can only
        # fail SAFE to a sim fill. Live fills reconcile against the venue's true fills out-of-band.
        outcome_by_coid: dict[str, OrderOutcome] = {}
        sim_intents = [io for io, _k, _p, routing in pending if routing == "sim"]
        if sim_intents:
            for oc in execute_orders(
                sim_intents, live_enabled=False, kill_switch=False, adapter=None,
                store=store, portfolio=portfolio, risk=store.settings.risk, catalog=cat,
            ):
                outcome_by_coid[oc.client_order_id] = oc
        live_intents = [io for io, _k, _p, routing in pending if routing == "live"]
        if live_intents:
            from cosmu.master.scheduler import (
                is_paused,  # local import: avoid an orchestrator import cycle
            )

            kill = is_paused(store)  # operator pause freezes live routing (orders fail safe to sim)
            by_venue: dict[str, list[IntendedOrder]] = {}
            for io in live_intents:
                by_venue.setdefault(io.venue_id, []).append(io)
            for venue_id, group in by_venue.items():
                adapter = live_adapters.get(venue_id)
                if adapter is None:  # routing is 'live' only for armed venues, so this is defensive
                    continue
                for oc in execute_orders(
                    group, live_enabled=True, kill_switch=kill, adapter=adapter,
                    store=store, portfolio=portfolio, risk=store.settings.risk, catalog=cat,
                ):
                    outcome_by_coid[oc.client_order_id] = oc
                reconcile_fills(adapter, store, portfolio)  # intended → actual venue fill, out-of-band
        # Counts + events reflect what actually BOOKED. A rejected order was audited by the order path
        # (order_rejected) — it must not appear in the forward ledger as a trade that happened.
        for _intent, kind, payload, _routing in pending:
            outcome = outcome_by_coid.get(_intent.coid())
            if outcome is None or not outcome.accepted:
                continue
            if kind == "exit":
                report.closed += 1
                report.exits.append({k: payload[k] for k in ("version_id", "symbol", "reason", "price")})
                store.append_event(actor="master", kind="forward_exit", ref_type="strategy_version",
                                   ref_id=payload["version_id"], payload=payload)
            else:
                report.opened += 1
                report.entries.append({k: payload[k] for k in ("version_id", "symbol", "price")})
                store.append_event(actor="master", kind="forward_entry", ref_type="strategy_version",
                                   ref_id=payload["version_id"], payload=payload)
    store.append_event(
        actor="master",
        kind="paper_stepped",
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
