# intent: the WATCHER'S WATCHER — a Railway-side cross-monitor of the Modal cron fleet (Direction A of
# docs/reports/modal-railway-fallback-2026-06-26.md). The Modal heartbeat dead-man's-switch
# (cosmu/ops/heartbeat.py) runs ON the very Modal app it watches, so a TOTAL Modal death (eviction, token
# rotation, Free-tier schedule prune) takes the watcher down WITH the fleet and NOTHING pages — the one
# genuinely silent failure mode left in the stack. This module closes it: an env-flagged, in-process loop on
# the always-on Railway FastAPI engine periodically re-runs the SAME pure `heartbeat.check()` from Railway,
# which reads the shared Supabase that Modal writes — so a dark Modal fleet (the DB signals all stale at once)
# is visible from here even though the Modal-resident heartbeat can't see its own death.
#
# DETECTION ONLY — NO failover/takeover. The Modal crons are idempotent + SIM-only; a missed run self-heals or
# is one `modal run …` away once you're PAGED. The asset bought here is detection latency, not redundant
# execution. We reuse `heartbeat.check()` verbatim (one source of truth — the two watchers can never drift).
#
# WHAT IT PAGES ON — "Modal looks dead", not every normal Modal alert: only the MODAL-DRIVEN DB signals
# (ingest/tick/mark/exec — all written by the Modal fleet to Supabase) being stale. We deliberately do NOT
# re-page the Modal-resident heartbeat's own alerts (a single partial-job stall it already catches faster from
# inside): the cross-monitor fires on the cross-platform "Modal is dark" condition. The `backup` signal is
# DROPPED here on purpose — it probes R2 via boto3, which is NOT on the Railway image (`pip install .` skips the
# `[ops]` extra), so reading it from Railway would hit boto3's absence and false-positive every run. Backup
# freshness stays the Modal-resident heartbeat's job. Page-once-per-stale-episode dedup → a long Modal outage is
# ONE ping, not 48.

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.notify.slack import SlackNotifier
from cosmu.ops import heartbeat

logger = logging.getLogger("cosmu.ops.modal_watch")

# The fleet signals written to Supabase by the MODAL crons — the only ones a Railway-side reader can verify
# without leaving the shared DB. `backup` (R2/boto3) is intentionally excluded (see header). When EVERY one of
# these is stale at once, the Modal fleet has gone dark as a whole — the cross-platform condition we page on.
MODAL_DB_SIGNALS: tuple[str, ...] = ("ingest", "tick", "mark", "exec")

# How often Railway re-checks Modal liveness. Hourly mirrors the Modal heartbeat's own cadence — frequent enough
# to catch a dark fleet within the same window the inside watcher would have, cheap enough to be free (≈5 cheap
# reads/hour on the always-on process).
DEFAULT_INTERVAL_S = 3600.0


def check_modal_liveness(
    store: Store,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run the SHARED `heartbeat.check()` from Railway and decide whether MODAL looks dead — i.e. whether the
    Modal-driven DB signals (ingest/tick/mark/exec) are stale. Pure read; deterministic for a fixed `now`.

    `modal_dark` is True only when AT LEAST ONE Modal DB signal is stale — that's the cross-platform "Modal
    isn't writing" condition. We restrict the verdict to MODAL_DB_SIGNALS (dropping `backup`, which the Railway
    image can't probe) so this never false-positives on the missing boto3 dep."""
    report = heartbeat.check(store, settings=settings, now=now)
    stale_all: dict[str, object] = report["stale"]  # type: ignore[assignment]
    modal_stale = {k: stale_all[k] for k in MODAL_DB_SIGNALS if k in stale_all}
    return {
        "now": report["now"],
        "ages_h": report["ages_h"],
        "modal_stale": modal_stale,           # the stale Modal DB signals (the page payload)
        "modal_dark": bool(modal_stale),      # True ⇒ page (Modal looks dead from Railway)
    }


def _page(notifier: SlackNotifier, verdict: dict[str, object]) -> None:
    """Emit the one cross-monitor page: Modal looks dark, as SEEN FROM RAILWAY (the watcher's watcher)."""
    ages = verdict["ages_h"]  # type: ignore[index]
    stale: dict[str, object] = verdict["modal_stale"]  # type: ignore[assignment]

    def _fmt(k: str) -> str:
        v = ages[k]  # type: ignore[index]
        return "NEVER" if v is None else f"{v}h"

    lines = [f"• {k}: {_fmt(k)}" for k in stale]
    notifier.send(
        ":red_circle: *MODAL FLEET DARK (seen from Railway)* — the Modal-driven signals stopped writing to the "
        "shared DB, so the on-Modal heartbeat may be down WITH the fleet:\n"
        + "\n".join(lines)
        + "\nCheck the Modal app `cosmu-engine` (eviction / token rotation / Free-tier schedule prune)."
    )


async def run_modal_watch_loop(
    store: Store,
    *,
    settings: Settings | None = None,
    notifier: SlackNotifier | None = None,
    stop: asyncio.Event | None = None,
    interval_s: float = DEFAULT_INTERVAL_S,
    now_fn=None,  # noqa: ANN001 — clock seam (tests inject a fixed/advancing clock)
) -> int:
    """The supervised in-process loop: every `interval_s`, re-run the Modal-liveness check from Railway and PAGE
    once per stale episode if Modal looks dark. Near-clone of realtime/worker.py::_heartbeat_task — crash-
    isolated (a DB blip skips one cycle, never kills the API), clean stop. Returns the number of pages sent
    (tests assert on it). Page-once dedup: we only page on the RISING edge (healthy→dark), so a long outage is
    one ping; recovery (dark→healthy) re-arms the alarm for the next episode."""
    settings = settings or store.settings
    notifier = notifier or SlackNotifier.from_settings(settings)
    stop = stop or asyncio.Event()
    now_fn = now_fn or (lambda: datetime.now(UTC))

    pages = 0
    was_dark = False  # rising-edge dedup state
    while not stop.is_set():
        try:
            verdict = await asyncio.to_thread(check_modal_liveness, store, settings=settings, now=now_fn())
            is_dark = bool(verdict["modal_dark"])
            if is_dark and not was_dark:
                _page(notifier, verdict)
                pages += 1
                logger.warning("modal_watch: MODAL DARK from Railway — paged (stale=%s)", verdict["modal_stale"])
            elif not is_dark and was_dark:
                logger.info("modal_watch: Modal fleet recovered (seen from Railway)")
            was_dark = is_dark
        except Exception as exc:  # noqa: BLE001 — a transient read error skips one cycle, never kills the API
            logger.warning("modal_watch: check failed (retried next cycle): %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass
    return pages
