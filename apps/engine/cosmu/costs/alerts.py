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


def _tier_webhook(settings: Any, severity: str) -> str | None:
    """Resolve the Slack webhook for a severity via the shared aviation two-tier router. 'page' →
    slack_webhook_url_page (falling back to slack_webhook_url); 'log' → slack_webhook_url. Reused so the budget
    100%-crossed (critical) and account-EXHAUSTED events reach the PAGE bus while info/warn/stride stay on LOG.
    Deferred import so this module stays importable without pulling notify at module load."""
    from cosmu.notify.slack import SlackNotifier

    return SlackNotifier.tiered(settings, "page" if severity == "page" else "log")._url


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
    """Post budget alerts to Slack and write open recommendation rows. Best-effort. The 100%-crossed (critical)
    tier routes to the aviation PAGE bus; info/warn stay on the LOG bus (per-alert routing inside _post_slack)."""
    if not alerts:
        return
    _post_slack(alerts, settings, _http_post=_http_post)
    if store is not None:
        _write_recommendations(alerts, store)


def _live_slack_post(url: str, payload: bytes) -> None:
    import urllib.request

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as _:  # noqa: S310
        pass


def post_slack_text(
    webhook_url: str,
    text: str,
    *,
    _http_post: Callable[[str, bytes], Any] | None = None,
) -> None:
    """Post one Slack message (best-effort). Shared by the budget alerter and the $15-stride account notifier."""
    http_post = _http_post or _live_slack_post
    payload = json.dumps({"text": text}).encode()
    try:
        http_post(webhook_url, payload)
    except Exception:  # noqa: BLE001
        pass


def _post_slack(
    alerts: list[BudgetAlert],
    settings: Any,
    *,
    _http_post: Callable[[str, bytes], Any] | None = None,
) -> None:
    http_post = _http_post or _live_slack_post
    icon = {"info": ":information_source:", "warning": ":warning:", "critical": ":rotating_light:"}
    # Resolve both buses once. A 100%-crossed (critical) budget alert is a "wake me up" event → PAGE bus;
    # info/warn are routine → LOG bus. When no page bus is configured, tiered() falls the page tier back to the
    # log webhook, so a single-channel operator still gets every alert on their one channel.
    log_url = _tier_webhook(settings, "log")
    page_url = _tier_webhook(settings, "page")
    for alert in alerts:
        webhook_url = page_url if alert.level == "critical" else log_url
        if not webhook_url:
            continue
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


# ---------------------------------------------------------------------------
# $15-fixed-stride per-account notifier (modular compute-spend failover)
# ---------------------------------------------------------------------------

# Notify the operator every $15 of an account's metered spend (NOT every $5 — the point is don't-lose-progress,
# not penny-watching). free_credit ~$30 → strides land at ~$15 (halfway warn) and ~$30 (exhausted). Reuses the
# Slack webhook + recommendation rows above; bumps notified_floor on the account so each stride pings exactly once.
SPEND_STRIDE_USD = 15.0


@dataclass
class AccountStrideAlert:
    account_id: str
    provider: str
    spend: float
    free_credit: float
    floor: int          # the $15 stride crossed (floor(spend/15))
    prev_floor: int     # the last stride already notified


def check_account_strides(store: Any, settings: Any, *, _http_post: Callable[[str, bytes], Any] | None = None) -> list[AccountStrideAlert]:
    """For every model account, fire one Slack ping + recommendation row each time its metered spend crosses a new
    $15 stride, then bump notified_floor so the stride never re-fires. Run AFTER spend is reconciled from the
    ledger (see costs.refresh). Best-effort; returns the alerts emitted (empty when nothing crossed / no store)."""
    if store is None:
        return []
    from cosmu.costs.accounts import bump_notified_floor, list_accounts

    # Two buses: an EXHAUSTED account (failing over) is a "wake me up" event → PAGE; a mid-run stride crossing
    # is routine → LOG. tiered() falls the page tier back to the log webhook for a single-channel operator.
    log_url = _tier_webhook(settings, "log")
    page_url = _tier_webhook(settings, "page")
    emitted: list[AccountStrideAlert] = []
    try:
        open_bodies = {r["body"] for r in store.rows("SELECT body FROM recommendations WHERE state = 'open'")}
    except Exception:  # noqa: BLE001
        open_bodies = set()

    for acct in list_accounts(store):
        floor = int(acct.spend_used // SPEND_STRIDE_USD)
        if floor <= acct.notified_floor:
            continue
        alert = AccountStrideAlert(
            account_id=acct.account_id,
            provider=acct.provider,
            spend=acct.spend_used,
            free_credit=acct.free_credit_usd,
            floor=floor,
            prev_floor=acct.notified_floor,
        )
        exhausted = acct.spend_used >= acct.free_credit_usd - 0.25
        head = ":rotating_light:" if exhausted else ":moneybag:"
        state = "EXHAUSTED — failing over" if exhausted else "metered spend crossing"
        text = (
            f"{head} *Cosmu model-account {state} — {acct.account_id}* ({acct.provider})\n"
            f"Spend ${acct.spend_used:.2f} of ${acct.free_credit_usd:.2f} free credit "
            f"(${floor * SPEND_STRIDE_USD:.0f} stride). "
            + ("Pool advancing to the next account." if exhausted else "On track; will fail over near exhaustion.")
        )
        webhook_url = page_url if exhausted else log_url  # EXHAUSTED → PAGE bus; stride crossing → LOG bus
        if webhook_url:
            post_slack_text(webhook_url, text, _http_post=_http_post)

        body = (
            f"Model account {acct.account_id} ({acct.provider}) spend ${acct.spend_used:.2f} crossed the "
            f"${floor * SPEND_STRIDE_USD:.0f} stride (free credit ${acct.free_credit_usd:.2f})."
        )
        if body not in open_bodies:
            try:
                store.insert(
                    "recommendations",
                    {
                        "ts": datetime.now(tz=UTC).isoformat(),
                        "kind": "account_spend_stride",
                        "body": body,
                        "state": "open",
                        "payload": {
                            "account_id": acct.account_id,
                            "provider": acct.provider,
                            "spend": acct.spend_used,
                            "free_credit": acct.free_credit_usd,
                            "stride_usd": SPEND_STRIDE_USD,
                            "floor": floor,
                            "exhausted": exhausted,
                        },
                    },
                )
                open_bodies.add(body)
            except Exception:  # noqa: BLE001
                pass

        bump_notified_floor(store, acct.account_id, floor)
        emitted.append(alert)

    return emitted
