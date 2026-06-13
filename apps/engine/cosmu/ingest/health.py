# intent: the stale-source alarm — after a scheduled ingest pass, detect SILENT data-lane degradation (every
# source returned 0 this pass, or a previously-flowing provider has stopped producing) and push ONE deduped
# Slack alert + an `ingest_degraded` event; inputs: the knowledge store (summary rollup + events ledger) and
# the pass's per-source counts; outputs: at most one alert per cooldown window, else None; invariants: NEVER
# raises (alerting must never break ingest), no alert without evidence, the events ledger is the dedupe clock,
# and the threshold clears weekends (72h) so a quiet Saturday never pages.

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from cosmu.ingest.alt_summary import latest_per_provider
from cosmu.notify.slack import SlackNotifier, notify_ingest_degraded

logger = logging.getLogger("cosmu.ingest.health")

# A provider whose newest point is older than this has gone quiet long enough to matter — 72h clears a normal
# weekend for daily sources (Friday data read on Monday morning ≈ 65h) without paging on every Sunday.
_STALE_AFTER_HOURS = 72
# At most one alert per cooldown window — the deep review's "silent death" gap is fixed by ONE loud page,
# not by re-paging every 15-minute cron pass.
_COOLDOWN_HOURS = 24


def check_ingest_health(
    store: Any,
    counts: dict[str, int],
    *,
    notifier: SlackNotifier | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Evaluate one ingest pass for silent degradation. Returns the degradation payload when an alert fired,
    None otherwise (healthy, in cooldown, or any internal failure — this helper must never break ingest)."""
    try:
        return _check(store, counts, notifier, now or datetime.now(tz=UTC))
    except Exception:  # noqa: BLE001 — best-effort by invariant
        logger.exception("ingest health check failed (alerting is best-effort; the ingest pass is unaffected)")
        return None


def _check(store: Any, counts: dict[str, int], notifier: SlackNotifier | None, now: datetime) -> dict[str, Any] | None:
    meaningful = {k: v for k, v in counts.items() if k != "error"}
    all_zero = bool(meaningful) and all(v == 0 for v in meaningful.values())

    stale: list[tuple[str, int]] = []
    for row in latest_per_provider(store):
        last_raw = row.get("last_at")
        if not last_raw:
            continue
        try:
            last = datetime.fromisoformat(str(last_raw))
        except ValueError:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age_hours = (now - last).total_seconds() / 3600.0
        if age_hours > _STALE_AFTER_HOURS:
            stale.append((str(row.get("source", "?")), int(round(age_hours))))

    if not all_zero and not stale:
        return None

    recent = store.row(
        "SELECT ts FROM events WHERE kind = 'ingest_degraded' ORDER BY id DESC LIMIT 1"
    )
    if recent and recent.get("ts"):
        try:
            last_alert = datetime.fromisoformat(str(recent["ts"]))
            if last_alert.tzinfo is None:
                last_alert = last_alert.replace(tzinfo=UTC)
            if (now - last_alert).total_seconds() < _COOLDOWN_HOURS * 3600:
                return None  # already paged inside the cooldown window — stay quiet
        except ValueError:
            pass

    payload: dict[str, Any] = {
        "all_zero": all_zero,
        "stale": [{"source": s, "age_hours": h} for s, h in sorted(stale, key=lambda x: -x[1])],
    }
    store.append_event(actor="master", kind="ingest_degraded", ref_type="ingest", ref_id="sources", payload=payload)
    if notifier is not None:
        notify_ingest_degraded(notifier, all_zero=all_zero, stale=stale)
    return payload
