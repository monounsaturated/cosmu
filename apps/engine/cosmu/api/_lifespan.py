# intent: app startup/shutdown — health ping + best-effort boot tasks; inputs: none; outputs: lifespan context; invariants: every boot task is best-effort and offline-safe; never crashes the app or arms live.

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from cosmu.api._shared import ensure_recommendations, settings, store
from cosmu.spine.engine import EngineFacade
from cosmu.spine.universe import has_live_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio
    import threading

    from cosmu.notify.slack import SlackNotifier, notify_health_change

    notifier = SlackNotifier.from_settings(settings)
    notify_health_change(notifier, status="healthy", detail="cosmu-engine started")

    def _boot():
        try:
            facade = EngineFacade.create(settings)
            if not store.row("SELECT id FROM runs LIMIT 1"):
                facade.run_backtest(seed=11)
            ensure_recommendations()
            _scan_inbox_on_startup()
            _fund_tracks_on_startup()
        except Exception:  # noqa: BLE001 — boot tasks are best-effort; never crash the app
            pass

    threading.Thread(target=_boot, daemon=True).start()

    # Realtime recording worker (realtime-data-lane P3) — IN-PROCESS, OFF by default (the operator's
    # lean-infra decision: no second Railway service; REALTIME_WORKER_ENABLED=1 activates). It records
    # only (WS bars / events / heartbeat) — a worker failure degrades freshness to the cron lane, and the
    # supervised task can never crash the API.
    worker_stop: asyncio.Event | None = None
    worker_task: asyncio.Task | None = None
    if getattr(settings, "realtime_worker_enabled", False):
        from cosmu.realtime.worker import run_worker

        worker_stop = asyncio.Event()
        worker_task = asyncio.create_task(run_worker(store, settings=settings, stop=worker_stop))
    try:
        yield
    finally:
        if worker_stop is not None and worker_task is not None:
            worker_stop.set()
            try:
                await asyncio.wait_for(worker_task, timeout=10)
            except (TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001 — shutdown is best-effort
                worker_task.cancel()
        notify_health_change(notifier, status="down", detail="cosmu-engine shutting down")


def _fund_tracks_on_startup() -> None:
    """Close the loop on boot: if gate-passed survivors exist with tracks but no sim positions are open yet, open
    a standalone paper track for each so GET /overview reflects genuinely funded tracks (no fabricated
    numbers). Best-effort + offline-safe; never blocks startup."""
    try:
        from cosmu.orchestrator import fund_tracks_from_survivors

        if store.row("SELECT id FROM positions WHERE CAST(qty AS REAL) != 0 LIMIT 1"):
            return  # already funded — idempotent, don't double-open
        if not store.row("SELECT sv.id FROM strategy_versions sv JOIN tracks tr ON tr.strategy_version_id = sv.id WHERE sv.status IN ('paper','forward_test','live') LIMIT 1"):
            return  # no survivors yet — honest empty state
        fund_tracks_from_survivors(store, bankroll=settings.sim_bankroll)
    except Exception:  # noqa: BLE001 — funding is best-effort; a data/network hiccup must not break boot
        pass


def _scan_inbox_on_startup() -> None:
    """Scan strategies/inbox/*.{md,pine,json} on boot — idempotent (unchanged files skipped) and offline-safe, so
    a dropped-in strategy is translated into the Lab automatically. Never blocks startup on failure."""
    try:
        from cosmu.lab.inbox import scan_inbox

        scan_inbox(store, run_cohort=has_live_data(store))
    except Exception:  # noqa: BLE001 — inbox import is best-effort; a bad file must not break boot
        pass
