# intent: lean Slack notifications — post to a webhook on the few high-signal events only (gate
# verdict / first forward-test survivor, deploy health change, autonomy-tick error). Never blocks
# the caller (best-effort, all errors swallowed), no-op when SLACK_WEBHOOK_URL is unset,
# offline-testable (inject _post for unit tests, never touches the network in tests).
# inputs: the webhook URL (from settings or env), a message dict; outputs: a best-effort POST.
# invariants: NEVER raises, NEVER blocks, NEVER spams per-tick noise.

from __future__ import annotations

import json
import os
from typing import Any, Callable


# Type alias for the injectable HTTP poster: (url: str, payload: bytes) -> None
_HttpPost = Callable[[str, bytes], None]


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
# High-level helpers — three high-signal events only
# ---------------------------------------------------------------------------


def notify_gate_verdict(
    notifier: SlackNotifier,
    *,
    survivors: list[str],
    authored: int,
    evolved: int = 0,
) -> None:
    """Fire when the Gate runs and at least one survivor clears — the first forward-test seam.
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
        f"Now watching in sim (forward-test clock running)."
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
