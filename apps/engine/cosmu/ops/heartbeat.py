# intent: the dead-man's-switch for the autonomous cron fleet. A scheduled probe (Modal cron) that detects
# SILENT fleet death — the ingest / autonomous-tick / paper-mark jobs not running (or running but writing
# nothing) — and pings Slack ONCE per stale run. This is the alarm that was MISSING when the Railway cron fleet
# went dark for ~10 days unnoticed (no job that doesn't run can emit a failure). Read-only: never moves money,
# never touches the Gate. Lives off the same DB the jobs write, so a stale signal means "a writer stopped".
#
# Watched signals (each ~2x its job's cadence so a single missed run doesn't page, but a dark fleet does):
#   ingest → MAX(alt_data.ingested_at)            (Modal ingest hourly)
#   tick   → autonomy_status().last_tick_at        (Modal gate_sweep every 4h)
#   mark   → MAX(events.ts WHERE kind=tracks_marked) (Modal paper_mark daily)
#   exec   → MAX(events.ts WHERE kind IN (paper_stepped, forward_entry)) (Modal paper-exec — the EXECUTOR clock)
#   backup → age of the newest r2://<bucket>/backups/pg/*.dump   (Modal daily_backup at 05:00 UTC)
#
# `backup` is the ONLY non-DB signal: the daily_backup cron writes to R2, not the DB, so its liveness can't be
# read from `events`/`alt_data`. It probes the R2 newest-object age directly (best-effort boto3 list); a silent
# backup death (Modal evicts the schedule, pg_dump version drift, R2 creds rotate) pages instead of going
# unnoticed for days — the exact silent-death class this whole module exists to catch.
#
# `exec` is the executor-liveness probe: paper_step.step_tracks emits `paper_stepped` EVERY tick (even a tick
# that opens/closes nothing) and `forward_entry` when a track actually trades. A stalled executor (the paper
# clock dark) means funded tracks stop being stepped forward — survivors freeze on a stale mark and never trade
# — so this pages even when ingest/mark are healthy (a partial fleet death the other three signals miss).
#
# CAVEAT: this probe runs ON the same Modal app it watches, so it catches "a job ran but wrote nothing" and
# "one job died" — not a total Modal outage (Modal's own run-failure alerts cover that). Far better than the
# zero-alert state that let the Railway fleet die silently.

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.scheduler import autonomy_status
from cosmu.notify.slack import SlackNotifier

# Staleness ceilings in HOURS. None of these gate money; they only decide when to page.
# `exec` shares the daily paper-clock cadence (paper_step runs alongside paper_mark), so 30h ~= 2x a daily run —
# a single missed run won't page, a dark executor will. `backup` rides the same 2x-daily logic: the dump fires
# at 05:00 UTC daily, so 30h means a single missed run is tolerated but a dark backup job pages.
DEFAULT_THRESHOLDS_H: dict[str, float] = {
    "ingest": 3.0, "tick": 9.0, "mark": 30.0, "exec": 30.0, "backup": 30.0,
}


def _age_hours(ts: Any, now: datetime) -> float | None:
    """Hours since an ISO timestamp; None if missing/unparseable (treated as STALE by the caller)."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return (now - t).total_seconds() / 3600.0


def _newest_backup_age_h(settings: Settings, now: datetime) -> float | None:
    """Hours since the newest r2://<bucket>/backups/pg/*.dump. None ⇒ STALE (missing creds / empty prefix /
    any error). This is the only signal that reads R2 instead of the DB — the daily_backup cron writes there,
    not to events/alt_data. Best-effort by design: a transient R2 blip returns None (PAGE) rather than crashing
    the probe, and keyless-degrades (None) in offline tests; prod's `cosmu-engine` secret always carries R2_*."""
    if not all(
        (settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket)
    ):
        return None  # keyless degradation (offline tests); prod secret always has R2_*
    try:
        # Reuse pg_backup's R2 client + prefix so the writer and the watcher can never drift on endpoint/path.
        from cosmu.data.pg_backup import _PREFIX, _r2_client

        s3 = _r2_client(settings)
        objs = s3.list_objects_v2(Bucket=settings.r2_bucket, Prefix=f"{_PREFIX}/").get("Contents", [])
        dumps = [o for o in objs if o["Key"].endswith(".dump")]
        if not dumps:
            return None  # prefix exists but no dump yet (or all pruned) — treat as stale
        newest = max(dumps, key=lambda o: o["LastModified"])
        last_modified = newest["LastModified"]
        if last_modified.tzinfo is None:  # boto3 returns tz-aware UTC, but be defensive for stubs
            last_modified = last_modified.replace(tzinfo=UTC)
        return (now - last_modified).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001 — a transient R2 error ⇒ page (None), never crash the probe
        return None


def check(
    store: Store,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute the age of each fleet signal and which are stale. Pure read; deterministic for a fixed `now`.
    `settings` defaults to the Store's own Settings (which carries the R2_* creds) — the `backup` signal needs
    it to probe R2; tests inject it (or stub `_newest_backup_age_h`) to stay offline."""
    now = now or datetime.now(UTC)
    settings = settings or store.settings
    th = {**DEFAULT_THRESHOLDS_H, **(thresholds or {})}
    canary = store.row("SELECT MAX(ingested_at) AS t FROM alt_data")
    marked = store.row("SELECT MAX(ts) AS t FROM events WHERE kind = 'tracks_marked'")
    stepped = store.row(
        "SELECT MAX(ts) AS t FROM events WHERE kind IN ('paper_stepped', 'forward_entry')"
    )
    ages: dict[str, float | None] = {
        "ingest": _age_hours(canary.get("t") if canary else None, now),
        "tick": _age_hours(autonomy_status(store).last_tick_at, now),
        "mark": _age_hours(marked.get("t") if marked else None, now),
        "exec": _age_hours(stepped.get("t") if stepped else None, now),
        "backup": _newest_backup_age_h(settings, now),  # R2 freshness — the only non-DB signal
    }
    # A signal is stale if it has NEVER fired (None) or exceeds its ceiling.
    stale = {k: ages[k] for k in ages if ages[k] is None or ages[k] > th[k]}
    rounded = {k: (round(v, 1) if v is not None else None) for k, v in ages.items()}
    return {"now": now.isoformat(), "ages_h": rounded, "thresholds_h": th,
            "stale": {k: rounded[k] for k in stale}, "ok": not stale}


def run(store: Store | None = None, *, notifier: SlackNotifier | None = None, now: datetime | None = None) -> int:
    """Probe the fleet; Slack-alert (once) if anything is stale. Returns 0 when healthy, 1 when stale — so the
    Modal run itself goes RED on a dark fleet (a second signal alongside the Slack ping)."""
    store = store or Store(Settings())
    notifier = notifier or SlackNotifier.from_env()
    report = check(store, now=now)
    if report["ok"]:
        print(f"[heartbeat] OK ages_h={report['ages_h']}")
        return 0

    def _fmt(k: str) -> str:
        v = report["ages_h"][k]
        return "NEVER" if v is None else f"{v}h"

    lines = [f"• {k}: {_fmt(k)}" for k in report["stale"]]
    notifier.send(
        ":red_circle: *Cron fleet stale* — an autonomous job stopped writing:\n"
        + "\n".join(lines)
        + f"\n(thresholds_h={report['thresholds_h']}). Check the Modal app `cosmu-engine`."
    )
    print(f"[heartbeat] STALE {report['stale']} — alerted Slack")
    return 1


if __name__ == "__main__":
    sys.exit(run())
