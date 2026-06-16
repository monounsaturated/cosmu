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
DEFAULT_THRESHOLDS_H: dict[str, float] = {"ingest": 3.0, "tick": 9.0, "mark": 30.0}


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


def check(store: Store, *, now: datetime | None = None, thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """Compute the age of each fleet signal and which are stale. Pure read; deterministic for a fixed `now`."""
    now = now or datetime.now(UTC)
    th = {**DEFAULT_THRESHOLDS_H, **(thresholds or {})}
    canary = store.row("SELECT MAX(ingested_at) AS t FROM alt_data")
    marked = store.row("SELECT MAX(ts) AS t FROM events WHERE kind = 'tracks_marked'")
    ages: dict[str, float | None] = {
        "ingest": _age_hours(canary.get("t") if canary else None, now),
        "tick": _age_hours(autonomy_status(store).last_tick_at, now),
        "mark": _age_hours(marked.get("t") if marked else None, now),
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
