# intent: app startup/shutdown — health ping + best-effort boot tasks; inputs: none; outputs: lifespan context; invariants: every boot task is best-effort and offline-safe; never crashes the app or arms live.

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from cosmu.api._shared import ensure_recommendations, settings, store
from cosmu.knowledge.lifecycle_status import ALIVE_STATUSES, sql_in_list
from cosmu.spine.engine import EngineFacade
from cosmu.spine.universe import has_live_data


def _guard_production_auth(s) -> None:
    """FAIL CLOSED: refuse to start the API in production without API_SECRET_KEY. The x-api-key middleware
    (app.py) is a NO-OP when the key is unset, so a keyless prod boot would silently expose the entire
    money-moving control plane (live activate/launch/rules) unauthenticated. Scoped to API startup ONLY —
    Modal cron jobs / CLI build Settings without this lifespan, so the worker fleet is never blocked even though
    it also runs APP_ENV=production. `environment` maps both the qa and production profiles to 'production'
    (config/settings.py), so both are covered; local/test leave auth optional as documented."""
    if getattr(s, "environment", None) == "production" and not getattr(s, "api_secret_key", None):
        raise RuntimeError(
            "API_SECRET_KEY is required in production — refusing to start the control plane unauthenticated. "
            "Set API_SECRET_KEY on the engine service (and ensure the Vercel proxy forwards x-api-key)."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio
    import threading

    _guard_production_auth(settings)  # fail closed before any boot task touches the control plane

    from cosmu.notify.slack import SlackNotifier, notify_health_change

    notifier = SlackNotifier.from_settings(settings)
    notify_health_change(notifier, status="healthy", detail="cosmu-engine started")

    # Pre-open the warm read pool at boot (best-effort) so the FIRST user request — typically the slow
    # multi-read strategy-detail sheet — never pays the ~1.7s Supabase connection handshake. Without this
    # the first click after a redeploy hit a cold pool and exceeded the web timeout ("engine did not respond").
    store.warm_reads()

    def _boot():
        try:
            facade = EngineFacade.create(settings)
            if not store.row("SELECT id FROM runs LIMIT 1"):
                facade.run_backtest(seed=11)
            ensure_recommendations()
            _reclassify_unforwarded_paper_on_startup()
            _fund_tracks_on_startup()
            _kickstart_paper_fills_on_startup()  # after funding: arms hold positions → record their fills → Paper
            _scan_inbox_on_startup()
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
        # Fund paper entrants INCLUDING 'screened': an entrant is born "screened" (badge: Backtest) and
        # funding it (opening its sim positions) is what STARTS the forward test — the paper clock then promotes
        # it to "paper" once a real forward day accrues. Omitting 'screened' here would strand every new survivor
        # unfunded → never marked → never promoted (chicken-and-egg).
        if not store.row(f"SELECT sv.id FROM strategy_versions sv JOIN tracks tr ON tr.strategy_version_id = sv.id WHERE sv.status IN {sql_in_list(ALIVE_STATUSES)} LIMIT 1"):
            return  # no survivors yet — honest empty state
        fund_tracks_from_survivors(store, bankroll=settings.sim_bankroll)
    except Exception:  # noqa: BLE001 — funding is best-effort; a data/network hiccup must not break boot
        pass


def _kickstart_paper_fills_on_startup() -> None:
    """Boot wiring for orchestrator.kickstart_paper_fills: back-fill the documented arms' real held allocation
    into the executions ledger so a paper-trading arm reads "Paper" (with a fill blotter) instead of stuck on
    "Backtest". One-shot + idempotent (skips versions that already have fills). Best-effort; never blocks boot."""
    try:
        from cosmu.orchestrator.loop import kickstart_paper_fills

        n = kickstart_paper_fills(store)
        if n:
            print(f"[boot] kickstarted {n} paper-trading arm(s) screened -> paper (recorded held legs as fills)")
    except Exception:  # noqa: BLE001 — best-effort; a data/network hiccup must not break boot
        pass


def _reclassify_unforwarded_paper_on_startup() -> None:
    """Boot wiring for orchestrator.reclassify_unforwarded_paper: one-shot, idempotent, cross-backend fix for
    legacy rows the documented-deploy / survivor lanes stamped 'paper' at creation, before any forward mark —
    demoting them to 'screened' (badge: Backtest) so "Paper" means real forward evidence. Self-correcting: the
    paper clock re-promotes each once it earns a forward day. Best-effort + offline-safe; never blocks startup.
    Runs on BOTH backends (Python + store UPDATE), unlike the SQLite-only schema migrate()."""
    try:
        from cosmu.orchestrator.loop import reclassify_unforwarded_paper

        demoted = reclassify_unforwarded_paper(store)
        if demoted:
            print(f"[boot] reclassified {demoted} unforwarded paper -> screened (no forward day yet)")
    except Exception:  # noqa: BLE001 — reclassification is best-effort; a data/network hiccup must not break boot
        pass


def _scan_inbox_on_startup() -> None:
    """Scan strategies/inbox/*.{md,pine,json} on boot — idempotent (unchanged files skipped) and offline-safe, so
    a dropped-in strategy is translated into the Lab automatically. Never blocks startup on failure."""
    try:
        from cosmu.lab.inbox import scan_inbox

        scan_inbox(store, run_cohort=has_live_data(store))
    except Exception:  # noqa: BLE001 — inbox import is best-effort; a bad file must not break boot
        pass
