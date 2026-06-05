# intent: budget threshold checks + Slack emit + recommendation rows; inputs: VendorSpend list +
# BudgetConfig + store; outputs: Slack POST and open recommendation rows; invariants: best-effort,
# never crash caller, idempotent recommendations (no duplicate open bodies).

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

# (threshold_pct, action, level) — highest threshold that applies is emitted (break after first match)
_THRESHOLDS = [
    (1.00, "throttle-suggest", "critical"),
    (0.80, "warn", "warning"),
    (0.50, "info", "info"),
]


@dataclass
class BudgetAlert:
    vendor: str
    threshold_pct: float
    level: str
    action: str
    spend: float
    budget: float


def check_budget(spends: list[Any], settings: Any) -> list[BudgetAlert]:
    """Return one alert per vendor (or global) that has crossed a threshold.
    Returns empty list if no caps are configured (all caps == 0 → uncapped)."""
    budget_cfg = getattr(settings, "budget", None)
    if budget_cfg is None:
        return []

    spends_by_vendor = {s.vendor: s.amount for s in spends}
    alerts: list[BudgetAlert] = []

    vendor_cfg_map = {
        "OpenRouter": getattr(budget_cfg, "openrouter", None),
        "xAI": getattr(budget_cfg, "xai", None),
        "Railway": getattr(budget_cfg, "railway", None),
        "Modal": getattr(budget_cfg, "modal", None),
        "Claude": getattr(budget_cfg, "claude", None),
    }
    for vendor, cfg in vendor_cfg_map.items():
        cap = float(getattr(cfg, "monthly_cap", 0) or 0) if cfg is not None else 0.0
        if cap <= 0:
            continue
        spend = spends_by_vendor.get(vendor, 0.0)
        for pct, action, level in _THRESHOLDS:
            if spend >= cap * pct:
                alerts.append(BudgetAlert(vendor=vendor, threshold_pct=pct, level=level, action=action, spend=spend, budget=cap))
                break

    global_cap = float(getattr(budget_cfg, "global_monthly_cap", 0) or 0)
    if global_cap > 0:
        total = sum(spends_by_vendor.values())
        for pct, action, level in _THRESHOLDS:
            if total >= global_cap * pct:
                alerts.append(BudgetAlert(vendor="global", threshold_pct=pct, level=level, action=action, spend=total, budget=global_cap))
                break

    return alerts


def emit_alerts(
    alerts: list[BudgetAlert],
    store: Any,
    settings: Any,
    *,
    _http_post: Callable[[str, bytes], Any] | None = None,
) -> None:
    """Post budget alerts to Slack and write open recommendation rows. Best-effort."""
    if not alerts:
        return
    webhook_url = getattr(settings, "slack_webhook_url", None)
    if webhook_url:
        _post_slack(alerts, webhook_url, _http_post=_http_post)
    if store is not None:
        _write_recommendations(alerts, store)


def _post_slack(
    alerts: list[BudgetAlert],
    webhook_url: str,
    *,
    _http_post: Callable[[str, bytes], Any] | None = None,
) -> None:
    import urllib.request

    def _live_post(url: str, payload: bytes) -> None:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as _:  # noqa: S310
            pass

    http_post = _http_post or _live_post
    icon = {"info": ":information_source:", "warning": ":warning:", "critical": ":rotating_light:"}
    for alert in alerts:
        pct_str = f"{int(alert.threshold_pct * 100)}%"
        text = (
            f"{icon.get(alert.level, ':moneybag:')} *Cosmu budget alert — {alert.vendor}*\n"
            f"Spend ${alert.spend:.2f} crossed the {pct_str} threshold (cap ${alert.budget:.2f}).\n"
            f"Action: {alert.action}"
        )
        payload = json.dumps({"text": text}).encode()
        try:
            http_post(webhook_url, payload)
        except Exception:  # noqa: BLE001
            pass


def _write_recommendations(alerts: list[BudgetAlert], store: Any) -> None:
    try:
        open_bodies = {r["body"] for r in store.rows("SELECT body FROM recommendations WHERE state = 'open'")}
        for alert in alerts:
            pct_str = f"{int(alert.threshold_pct * 100)}%"
            body = (
                f"Budget alert: {alert.vendor} spend ${alert.spend:.2f} crossed the {pct_str} cap "
                f"(${alert.budget:.2f}/mo). Recommended action: {alert.action}."
            )
            if body in open_bodies:
                continue
            store.insert(
                "recommendations",
                {
                    "ts": datetime.now(tz=UTC).isoformat(),
                    "kind": "budget_threshold",
                    "body": body,
                    "state": "open",
                    "payload": {
                        "vendor": alert.vendor,
                        "threshold_pct": alert.threshold_pct,
                        "spend": alert.spend,
                        "budget": alert.budget,
                        "action": alert.action,
                    },
                },
            )
    except Exception:  # noqa: BLE001
        pass
