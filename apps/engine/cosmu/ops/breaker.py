# intent: the LATCHING CIRCUIT-BREAKER — the aviation/rail-model actuator that, on a HARD aggregate breach,
# LIQUIDATES the armed book and DISARMS live, then STAYS tripped until a human explicitly re-arms. It is the
# missing hard-stop the old guards never had: the drawdown kill-switch + daily-loss disarm only BLOCK the next
# entry (append an issue rejecting the NEXT order) — nothing liquidates the already-armed live book, and the only
# auto liquidation (capital_guard's floor) runs on the 4h cron. This SENSE→DECIDE→STATE module wires into the
# paper clock (mark_tracks, every tick — far more often than 4h) and delegates ACTUATION to the EXISTING,
# gauntlet-exempt capital_guard.kill (reduce-only, sim-closes until a venue is armed). Three aviation primitives:
#   • a LATCHING breaker (is_latched — survives process death via the append-only events ledger; re-arm is
#     human-only, never on a timer), mirroring master.scheduler.is_paused;
#   • a weight-on-wheels INTERLOCK (toggle_live refuses to re-enable live while latched);
#   • a black-box FREEZE-FRAME (the deterministic reason snapshot logged on the breaker_tripped event).
# inputs: the store (+ optional catalog/router for the delegated kill) and a portfolio/marks read; outputs: a
# pure verdict (assess) + audited latch/liquidate/disarm (trip) + human re-arm (rearm). invariants: PURELY
# DEFENSIVE — it can only PREVENT loss, NEVER open/grow a position or arm anything; the Gate is untouched; trip is
# a NO-OP when !breaker_enabled or already latched (it liquidates EXACTLY ONCE); SIM/paper is unaffected (the
# executor sets breaker_latched only for LIVE-ARMED orders); fully verifiable OFFLINE on the sim book.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio

# The ledger markers that carry the latch state (append-only, so the last one wins — mirrors scheduler.is_paused's
# _PAUSED/_RESUMED pattern). breaker_warn is an OBSERVE-ONLY caution the paper clock emits on a warn/halt band; it
# is NOT a latch marker (it never trips the interlock). breaker_tripped/breaker_rearmed are the latch pair.
_TRIPPED = "breaker_tripped"
_REARMED = "breaker_rearmed"
_WARN = "breaker_warn"
# The per-latch dwell counter marker (the SOFT/warn band must persist consecutive ticks before it escalates). It
# lives in the same ledger — read as the count of these since the last dwell EDGE, so a spike that leaves the soft
# band resets the debounce. The dwell edges are the latch pair (a trip/rearm) AND an explicit dwell-reset marker.
_DWELL = "breaker_dwell"
_DWELL_RESET = "breaker_dwell_reset"


@dataclass(frozen=True)
class BreakerVerdict:
    """The PURE read the paper clock acts on. `tier` is the graduated band the aggregate book is in:
      • "none"       — nothing breached; no action.
      • "warn"       — the earliest CAUTION band (breaker_warn_drawdown_pct); emit a breaker_warn, no liquidation.
      • "halt"       — the existing drawdown_killswitch_pct band (entry-blocking today); escalated to a warn-with-
                       dwell, still no liquidation — the "block new entries" behaviour is preserved + made observable.
      • "liquidate"  — the HARD band (breaker_liquidate_drawdown_pct, or daily_loss ≥ cap × mult): TRIP the latch.
    `soft` is True for the warn/halt tiers (which need breaker_dwell_ticks consecutive marks before escalation); the
    liquidate tier is hard (trips at ONE tick, never debounced). `freeze_frame` is the deterministic black-box
    snapshot (the numbers that put the book in this tier) logged verbatim on the breaker_tripped event."""

    tier: str  # "none" | "warn" | "halt" | "liquidate"
    soft: bool
    freeze_frame: dict = field(default_factory=dict)


def _last_marker_id(store: Store, kinds: tuple[str, ...]) -> int:
    """The ledger id of the most-recent event whose kind is in `kinds`, or 0 if none. Used to bound the dwell
    read to 'since the last latch edge' and to decide latched vs not (last _TRIPPED after last _REARMED)."""
    placeholders = ",".join("?" for _ in kinds)
    row = store.row(
        f"SELECT id FROM events WHERE kind IN ({placeholders}) ORDER BY id DESC LIMIT 1", kinds
    )
    return int(row["id"]) if row and row.get("id") is not None else 0


def is_latched(store: Store) -> bool:
    """True when the breaker is TRIPPED and NOT since re-armed — the weight-on-wheels state. Mirrors
    scheduler.is_paused exactly: read the single most-recent latch marker off the append-only ledger (no in-memory
    daemon, so it survives process death) — a _TRIPPED that is newer than any _REARMED means the latch is closed."""
    row = store.row(
        f"SELECT kind FROM events WHERE kind IN ('{_TRIPPED}', '{_REARMED}') ORDER BY id DESC LIMIT 1"
    )
    return bool(row and row["kind"] == _TRIPPED)


def latch_reason(store: Store) -> dict | None:
    """The black-box FREEZE-FRAME of the CURRENT latch — the payload of the most-recent breaker_tripped event, or
    None when not latched. Lets the ops read-out surface WHY the breaker fired (drawdown/daily-loss numbers +
    trip time) without re-deriving it. Returns None (not {}) when the breaker is open so callers can branch cleanly."""
    if not is_latched(store):
        return None
    row = store.row(
        f"SELECT payload FROM events WHERE kind = '{_TRIPPED}' ORDER BY id DESC LIMIT 1"
    )
    if not row or row.get("payload") is None:
        return {}
    payload = row["payload"]
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return {}
    return payload if isinstance(payload, dict) else {}


def _dec(value) -> Decimal:  # noqa: ANN001 — Decimal | int | float | str
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 — a malformed setting must never crash the safety read
        return Decimal("0")


def assess(
    store: Store,
    *,
    portfolio: Portfolio | None = None,
    now: datetime | None = None,
) -> BreakerVerdict:
    """PURE READ → a graduated verdict, no side effects (never writes, never orders). Judges the AGGREGATE book
    (Σ of standalone tracks) against the RiskSettings bands: aggregate drawdown vs warn/HALT/liquidate, and today's
    daily-loss vs cap × liquidate-mult. The HALT band READS the existing drawdown_killswitch_pct (never mutates or
    duplicates it). Deterministic for a fixed store: same snapshots → same tier + freeze-frame. Offline-safe (reads
    persisted snapshots only). The freeze-frame is the black-box payload the trip logs verbatim."""
    now = now or datetime.now(tz=UTC)
    pf = portfolio or Portfolio(store, bankroll=store.settings.sim_bankroll)
    risk = store.settings.risk

    drawdown = pf.drawdown()  # aggregate drawdown from high-water, as a fraction (Decimal)
    daily = pf.daily_loss()  # DailyLossStatus: .daily_loss (positive), .cap

    warn_dd = _dec(risk.breaker_warn_drawdown_pct)
    halt_dd = _dec(risk.drawdown_killswitch_pct)  # the EXISTING kill-switch band — read, never mutated
    liq_dd = _dec(risk.breaker_liquidate_drawdown_pct)
    liq_loss_mult = _dec(risk.breaker_liquidate_daily_loss_mult)
    liq_loss = daily.cap * liq_loss_mult

    # The deterministic black-box: every number that decided the tier, stamped so the ledger reads the full picture.
    freeze_frame = {
        "at": now.isoformat(),
        "drawdown_pct": str(drawdown),
        "daily_loss": str(daily.daily_loss),
        "daily_loss_cap": str(daily.cap),
        "warn_drawdown_pct": str(warn_dd),
        "halt_drawdown_pct": str(halt_dd),
        "liquidate_drawdown_pct": str(liq_dd),
        "liquidate_daily_loss": str(liq_loss),
    }

    # HARD band first — a real hard breach outranks (and is never debounced by) the soft bands.
    hard_dd = liq_dd > 0 and drawdown >= liq_dd
    hard_loss = liq_loss > 0 and daily.daily_loss >= liq_loss
    if hard_dd or hard_loss:
        freeze_frame["trigger"] = "drawdown" if hard_dd else "daily_loss"
        return BreakerVerdict(tier="liquidate", soft=False, freeze_frame=freeze_frame)
    if halt_dd > 0 and drawdown >= halt_dd:
        freeze_frame["trigger"] = "drawdown"
        return BreakerVerdict(tier="halt", soft=True, freeze_frame=freeze_frame)
    if warn_dd > 0 and drawdown >= warn_dd:
        freeze_frame["trigger"] = "drawdown"
        return BreakerVerdict(tier="warn", soft=True, freeze_frame=freeze_frame)
    return BreakerVerdict(tier="none", soft=False, freeze_frame=freeze_frame)


def trip(
    store: Store,
    freeze_frame: dict,
    *,
    catalog=None,  # noqa: ANN001 — VenueCatalog; None → capital_guard.kill defaults to default_catalog()
    router=None,  # noqa: ANN001 — orchestrator.loop.PricingRouter (or a stub exposing last_price)
    now: datetime | None = None,
) -> bool:
    """CLOSE THE LATCH — the one actuating call, in FAIL-SAFE order so a partial failure still leaves the machine
    safer, never more exposed:
      (1) DISARM FIRST — flip live_toggle.enabled → 0 (no new live order can route even if step 2 or 3 raises);
      (2) LIQUIDATE   — capital_guard.kill(scope='all'): a threshold-free, reduce-only close of every funded
                        holding, routed through the ONE order path (real reduce-only on an armed venue, sim-close
                        otherwise). Reduce-only is gauntlet-EXEMPT, so a close always routes;
      (3) RECORD      — append breaker_tripped with the freeze-frame (the latch marker + the black-box). Written
                        LAST so is_latched only reports latched once the disarm+liquidate have actually run.

    NO-OP (returns False, touches nothing) when the breaker is config-disabled (!breaker_enabled) OR already
    latched — so the book is LIQUIDATED EXACTLY ONCE per latch (a re-run on the next tick can't double-liquidate,
    and re-arming is the only way to re-enable). Returns True when it tripped this call. PURELY DEFENSIVE: it can
    only disarm + reduce; it never opens/grows/arms anything."""
    if not store.settings.risk.breaker_enabled:
        return False  # config-kill: the actuator is disabled without a deploy (assess still reads)
    if is_latched(store):
        return False  # already latched — liquidate exactly ONCE; re-arm is the only reset

    now = now or datetime.now(tz=UTC)

    # (1) DISARM FIRST (weight-on-wheels): no new LIVE order can route past this even if step 2/3 raises. The SIM
    # lane is unaffected (the executor only reads breaker_latched for live-armed orders). Same UPDATE toggle_live uses.
    store.rows(
        "UPDATE live_toggle SET enabled = 0, enabled_at = ?, enabled_by = ? WHERE id = 'global'",
        (utcnow(), "breaker"),
    )

    # (2) LIQUIDATE — delegate to the EXISTING gauntlet-exempt reduce-only kill. scope='all' force-closes every
    # funded holding; sim-closes until a venue is armed (byte-identical to the paper executor's own exits).
    from cosmu.ops import capital_guard

    report = capital_guard.kill(store, scope="all", catalog=catalog, router=router, now=now)

    # (3) RECORD LAST — the latch marker + the black-box freeze-frame. is_latched flips True only now, AFTER the
    # disarm + liquidation have run, so a reader never sees "latched" while the actuation is still incomplete.
    payload = dict(freeze_frame)
    payload["liquidated"] = report.protected
    payload["evaluated"] = report.evaluated
    store.append_event(
        actor="master",
        kind=_TRIPPED,
        ref_type="breaker",
        ref_id="global",
        payload=payload,
    )
    return True


def rearm(store: Store, *, actor: str = "human") -> bool:
    """OPEN THE LATCH — the HUMAN-ONLY reset (called only by the ops route, NEVER on a timer). Appends a
    breaker_rearmed marker so is_latched reads False again and the toggle_live interlock lets live be re-enabled.
    NO-OP (returns False) when not currently latched — re-arming an open breaker is meaningless and must not write a
    spurious marker. Does NOT itself re-enable live (the operator re-arms live separately via toggle_live) and does
    NOT fund/open anything — it only clears the safety latch."""
    if not is_latched(store):
        return False
    store.append_event(
        actor=actor,
        kind=_REARMED,
        ref_type="breaker",
        ref_id="global",
        payload={"at": utcnow()},
    )
    return True


def dwell_count(store: Store) -> int:
    """How many consecutive SOFT-band marks have been observed since the last dwell EDGE — the debounce counter the
    paper clock reads to decide whether a warn/halt band has persisted breaker_dwell_ticks ticks. An edge is a latch
    trip/rearm OR an explicit dwell-reset (a tick that left the soft band). Bounded to 'since the last edge' so a
    spike that drops out of the band, or a fresh latch, starts the count over."""
    edge = _last_marker_id(store, (_TRIPPED, _REARMED, _DWELL_RESET))
    row = store.row(
        f"SELECT COUNT(*) AS n FROM events WHERE kind = '{_DWELL}' AND id > ?", (edge,)
    )
    return int(row["n"]) if row and row.get("n") is not None else 0


def note_soft_dwell(store: Store, verdict: BreakerVerdict) -> int:
    """Append ONE dwell marker for a soft-band tick and return the running count (since the last latch edge). The
    paper clock calls this on a warn/halt tick; when the count reaches breaker_dwell_ticks the band has persisted
    long enough to escalate to a breaker_warn. A single spike therefore never raises a warn (count 1 < dwell). A
    non-soft tick must instead call reset_dwell to clear the debounce."""
    store.append_event(
        actor="master",
        kind=_DWELL,
        ref_type="breaker",
        ref_id="global",
        payload={"tier": verdict.tier, "drawdown_pct": verdict.freeze_frame.get("drawdown_pct")},
    )
    return dwell_count(store)


def reset_dwell(store: Store) -> None:
    """Clear the soft-band debounce — the book left the warn/halt band without escalating, so the consecutive-tick
    count must start over. Appends a dwell-reset EDGE (which dwell_count bounds against). Idempotent: appends
    nothing when the count is already 0, so a run of 'none' ticks logs at most one reset marker."""
    if dwell_count(store) == 0:
        return
    store.append_event(
        actor="master",
        kind=_DWELL_RESET,
        ref_type="breaker",
        ref_id="global",
        payload={},
    )
