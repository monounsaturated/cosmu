# intent: lean Slack notifier — best-effort, never blocks caller, no-op when webhook unset.
from cosmu.notify.slack import SlackNotifier, notify_gate_verdict, notify_health_change, notify_tick_error

__all__ = ["SlackNotifier", "notify_gate_verdict", "notify_health_change", "notify_tick_error"]
