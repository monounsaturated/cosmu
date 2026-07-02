# intent: lean Slack notifications — post to a webhook on the few high-signal events only (gate
# verdict / first paper survivor, deploy health change, autonomy-tick error). Never blocks
# the caller (best-effort, all errors swallowed), no-op when SLACK_WEBHOOK_URL is unset,
# offline-testable (inject _post for unit tests, never touches the network in tests).
# inputs: the webhook URL (from settings or env), a message dict; outputs: a best-effort POST.
# invariants: NEVER raises, NEVER blocks, NEVER spams per-tick noise.

from __future__ import annotations

import json
import os
from typing import Any, Callable, Literal


# Type alias for the injectable HTTP poster: (url: str, payload: bytes) -> None
_HttpPost = Callable[[str, bytes], None]

# Aviation two-tier severity. 'log' = master-CAUTION (routine high-signal notices → slack_webhook_url).
# 'page' = master-WARNING (the few "wake me up" events → slack_webhook_url_page, falling back to
# slack_webhook_url when the page bus is unset). SlackNotifier.tiered(settings, severity) picks the URL.
Severity = Literal["page", "log"]


def _live_post(url: str, payload: bytes) -> None:
    """Default live poster — import deferred so tests that inject a fake never pull urllib."""
    import urllib.request

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as _:  # noqa: S310
        pass


class SlackNotifier:
    """Best-effort Slack webhook poster.  No-op when webhook_url is None/empty.
    Pass ``_post`` in tests so no network socket is ever opened."""

    def __init__(self, webhook_url: str | None = None, *, _post: _HttpPost | None = None) -> None:
        self._url = webhook_url or None
        self._post: _HttpPost = _post or _live_post

    @classmethod
    def from_env(cls, *, _post: _HttpPost | None = None) -> "SlackNotifier":
        """Read SLACK_WEBHOOK_URL from the environment (graceful no-op if unset)."""
        return cls(os.environ.get("SLACK_WEBHOOK_URL"), _post=_post)

    @classmethod
    def from_settings(cls, settings: Any, *, _post: _HttpPost | None = None) -> "SlackNotifier":
        """Read slack_webhook_url off a Settings object (graceful no-op if unset)."""
        url = getattr(settings, "slack_webhook_url", None) or os.environ.get("SLACK_WEBHOOK_URL")
        return cls(url, _post=_post)

    @classmethod
    def tiered(cls, settings: Any, severity: Severity, *, _post: _HttpPost | None = None) -> "SlackNotifier":
        """Aviation two-tier routing. 'page' → slack_webhook_url_page if set, else slack_webhook_url (a
        single-channel operator keeps one channel); 'log' → slack_webhook_url. Falls back to the SLACK_WEBHOOK_URL
        / SLACK_WEBHOOK_URL_PAGE env vars when a field is absent (Modal secret injection). Graceful no-op when the
        chosen bus is unset — the never-raise/never-block invariant is unchanged (see send())."""
        log_url = getattr(settings, "slack_webhook_url", None) or os.environ.get("SLACK_WEBHOOK_URL")
        if severity == "page":
            page_url = (
                getattr(settings, "slack_webhook_url_page", None)
                or os.environ.get("SLACK_WEBHOOK_URL_PAGE")
                or log_url  # single-channel fallback: the page tier rides the log bus when no page bus is set
            )
            return cls(page_url, _post=_post)
        return cls(log_url, _post=_post)

    def send(self, text: str) -> None:
        """Best-effort POST to the webhook.  Silently swallows ALL errors — never raises."""
        if not self._url:
            return
        try:
            payload = json.dumps({"text": text}).encode()
            self._post(self._url, payload)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Watchdog self-pulse — the dead-man's heartbeat-of-the-heartbeat
# ---------------------------------------------------------------------------


def record_watchdog_pulse(store: Any) -> None:
    """Append an event kind='watchdog_pulse' meaning "the heartbeat cron ran AND found the fleet healthy".
    The ABSENCE of a fresh watchdog_pulse is what tells the external prober the heartbeat CRON ITSELF died —
    the SPOF the on-Modal heartbeat can't report on (it can't page about its own non-execution). Called by
    ops.heartbeat.run() after a HEALTHY check. Best-effort: swallows ALL errors so it can never crash the
    heartbeat (a store hiccup must not turn a healthy run red). No-op-safe on a None store."""
    if store is None:
        return
    try:
        store.append_event(actor="ops", kind="watchdog_pulse", ref_type="heartbeat", ref_id="fleet", payload={})
    except Exception:  # noqa: BLE001 — never let the self-pulse crash the heartbeat
        pass


# ---------------------------------------------------------------------------
# High-level helpers — high-signal events only
# ---------------------------------------------------------------------------


def notify_gate_verdict(
    notifier: SlackNotifier,
    *,
    survivors: list[str],
    authored: int,
    evolved: int = 0,
) -> None:
    """Fire when the Gate runs and at least one survivor clears — the first paper seam.
    Silently no-ops when the webhook is unset or survivors is empty."""
    if not survivors:
        return
    names = ", ".join(survivors[:3])
    extra = f" (+{len(survivors) - 3} more)" if len(survivors) > 3 else ""
    evolved_note = f" | evolved {evolved}" if evolved else ""
    text = (
        f":white_check_mark: *Gate passed* — {len(survivors)}/{authored} survived"
        f"{evolved_note}\n"
        f"Survivors: {names}{extra}\n"
        f"Now watching in sim (paper clock running)."
    )
    notifier.send(text)


def notify_health_change(
    notifier: SlackNotifier,
    *,
    status: str,
    detail: str = "",
) -> None:
    """Fire on a deploy health transition (healthy / degraded / down).
    Silently no-ops when the webhook is unset."""
    icon = {"healthy": ":large_green_circle:", "degraded": ":large_yellow_circle:", "down": ":red_circle:"}.get(
        status, ":white_circle:"
    )
    body = f"{icon} *Cosmu engine — {status}*"
    if detail:
        body += f"\n{detail}"
    notifier.send(body)


def notify_tick_error(
    notifier: SlackNotifier,
    *,
    kind: str,
    error: str,
) -> None:
    """Fire when a critical autonomy-tick stage fails (ingest / funding / evolution / uncaught).
    Silently no-ops when the webhook is unset."""
    notifier.send(f":rotating_light: *Autonomy tick error — {kind}*\n`{error}`")


def notify_ingest_degraded(
    notifier: SlackNotifier,
    *,
    all_zero: bool,
    stale: list[tuple[str, int]],
) -> None:
    """Fire when the data lane is SILENTLY degrading: an ingest pass where every source returned 0 points,
    and/or previously-flowing providers gone stale (no new data in days). The caller (ingest/health.py)
    dedupes to one alert per cooldown window — this never spams per-tick.
    Silently no-ops when the webhook is unset."""
    lines: list[str] = []
    if all_zero:
        lines.append(":large_yellow_circle: *Ingest degraded* — every source returned 0 points this pass (network / keys / provider outage?)")
    if stale:
        worst = ", ".join(f"{source} ({hours}h)" for source, hours in stale[:6])
        extra = f" (+{len(stale) - 6} more)" if len(stale) > 6 else ""
        lines.append(f":hourglass: *Stale sources* — no new data in >72h: {worst}{extra}")
    if lines:
        notifier.send("\n".join(lines))
