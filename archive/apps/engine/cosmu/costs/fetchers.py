# intent: live vendor spend fetchers; stdlib urllib only; key-gated (no key → return None, honest skip);
# xAI spend derived from llm_calls ledger; offline-testable via injectable _http_get/_http_post seams.
# invariants: best-effort, never crash caller, no magic numbers.

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable


@dataclass
class VendorSpend:
    vendor: str
    category: str   # "llm" | "infra" | "data"
    amount: float
    period: str     # YYYY-MM
    meta: dict = field(default_factory=dict)


def _month() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m")


def _default_http_get(url: str, headers: dict[str, str]) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return resp.read()


def _default_http_post(url: str, headers: dict[str, str], payload: bytes) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return resp.read()


# ---------------------------------------------------------------------------
# Per-vendor fetchers
# ---------------------------------------------------------------------------


def fetch_openrouter(
    api_key: str | None,
    *,
    _http_get: Callable[[str, dict[str, str]], bytes] | None = None,
) -> VendorSpend | None:
    """GET /api/v1/credits → (usage, limit). No key → None (honest skip)."""
    if not api_key:
        return None
    http_get = _http_get or _default_http_get
    try:
        raw = http_get(
            "https://openrouter.ai/api/v1/credits",
            {"Authorization": f"Bearer {api_key}"},
        )
        data = json.loads(raw)
        d = data.get("data", {}) or {}
        usage = float(d.get("usage") or 0)
        limit = float(d.get("limit") or 0)
        return VendorSpend(
            vendor="OpenRouter",
            category="llm",
            amount=usage,
            period=_month(),
            meta={"limit": limit, "source": "api"},
        )
    except Exception:  # noqa: BLE001
        return None


def fetch_xai_from_ledger(store: Any, period: str | None = None) -> VendorSpend:
    """Derive xAI/Grok spend from our llm_calls ledger — tokens × cost already logged.
    This is the source of truth for LLM spend regardless of provider."""
    mo = period or _month()
    if store is None:
        return VendorSpend(vendor="xAI", category="llm", amount=0.0, period=mo, meta={"source": "ledger"})
    try:
        row = store.row(
            "SELECT COALESCE(SUM(CAST(cost AS REAL)), 0) AS total FROM llm_calls "
            "WHERE (model_id LIKE ? OR model_id LIKE ?) AND ts LIKE ?",
            ("%grok%", "%xai%", f"{mo}%"),
        )
        amount = float(row["total"] or 0) if row else 0.0
        return VendorSpend(vendor="xAI", category="llm", amount=amount, period=mo, meta={"source": "ledger"})
    except Exception:  # noqa: BLE001
        return VendorSpend(vendor="xAI", category="llm", amount=0.0, period=mo, meta={"source": "ledger"})


def fetch_railway(
    api_token: str | None,
    *,
    _http_post: Callable[[str, dict[str, str], bytes], bytes] | None = None,
) -> VendorSpend | None:
    """GraphQL estimated-cost query against Railway backboard. No key → None."""
    if not api_token:
        return None
    http_post = _http_post or _default_http_post
    query = "{ me { projects { edges { node { name usage { estimatedCost } } } } } }"
    payload = json.dumps({"query": query}).encode()
    try:
        raw = http_post(
            "https://backboard.railway.app/graphql/v2",
            {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            payload,
        )
        data = json.loads(raw)
        total = 0.0
        for edge in (data.get("data") or {}).get("me", {}).get("projects", {}).get("edges", []):
            est = (edge.get("node") or {}).get("usage", {}).get("estimatedCost") or 0
            total += float(est)
        return VendorSpend(
            vendor="Railway",
            category="infra",
            amount=total,
            period=_month(),
            meta={"source": "api"},
        )
    except Exception:  # noqa: BLE001
        return None


def fetch_modal(
    *,
    _run_cli: Callable[[], Any] | None = None,
) -> VendorSpend | None:
    """Modal workspace usage via CLI (`modal usage`). Uses existing Modal token.
    Returns None if CLI unavailable or doesn't emit a dollar amount."""
    import re

    run_cli = _run_cli or (
        lambda: subprocess.run(["modal", "usage"], capture_output=True, text=True, timeout=15)
    )
    try:
        result = run_cli()
        m = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", result.stdout)
        if m:
            return VendorSpend(
                vendor="Modal",
                category="infra",
                amount=float(m.group(1)),
                period=_month(),
                meta={"source": "cli"},
            )
    except Exception:  # noqa: BLE001
        pass
    return None


def fetch_vercel() -> VendorSpend:
    # TODO: wire Vercel billing API when plan goes paid
    return VendorSpend(
        vendor="Vercel",
        category="infra",
        amount=0.0,
        period=_month(),
        meta={"source": "constant", "note": "hobby free — wire billing API when paid"},
    )


def fetch_supabase() -> VendorSpend:
    # TODO: wire Supabase billing API when plan goes paid
    return VendorSpend(
        vendor="Supabase",
        category="infra",
        amount=0.0,
        period=_month(),
        meta={"source": "constant", "note": "free tier — wire billing API when paid"},
    )


def fetch_claude_max() -> VendorSpend:
    """Claude flat subscription — amount + note from operating_costs (single source of truth).
    No billing API exists for the consumer Max/Pro sub; this is a known fixed number."""
    from cosmu.costs.operating_costs import flat_subscription

    sub = flat_subscription("Claude") or {"category": "llm", "amount": 200.0, "note": "Claude Max 20x"}
    return VendorSpend(
        vendor="Claude",
        category=str(sub["category"]),
        amount=float(sub["amount"]),
        period=_month(),
        meta={"source": "constant", "note": str(sub["note"])},
    )


def fetch_cursor() -> VendorSpend:
    """Cursor flat subscription — amount + note from operating_costs (single source of truth).
    Personal Pro plan is a flat fee with no clean self-spend billing API."""
    from cosmu.costs.operating_costs import flat_subscription

    sub = flat_subscription("Cursor") or {"category": "llm", "amount": 20.0, "note": "Cursor Pro"}
    return VendorSpend(
        vendor="Cursor",
        category=str(sub["category"]),
        amount=float(sub["amount"]),
        period=_month(),
        meta={"source": "constant", "note": str(sub["note"])},
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def refresh_vendor_costs(
    store: Any,
    settings: Any,
    *,
    _http_get: Callable | None = None,
    _http_post: Callable | None = None,
    _run_cli: Callable | None = None,
) -> list[VendorSpend]:
    """Fetch all vendor spends and upsert rows into costs (meta seed='vendor'). Best-effort.

    Returns the list of fetched spends regardless of write success. Keyed vendors that
    lack a configured key are omitted from the result (honest skip, not a $0 fabrication).
    """
    fetchers = [
        lambda: fetch_openrouter(settings.openrouter_api_key, _http_get=_http_get),
        lambda: fetch_xai_from_ledger(store),
        lambda: fetch_railway(getattr(settings, "railway_api_token", None), _http_post=_http_post),
        lambda: fetch_modal(_run_cli=_run_cli),
        fetch_vercel,
        fetch_supabase,
        fetch_claude_max,
        fetch_cursor,
    ]
    spends: list[VendorSpend] = []
    for fn in fetchers:
        try:
            result = fn()
            if result is not None:
                spends.append(result)
        except Exception:  # noqa: BLE001
            pass

    if store is not None:
        _write_vendor_rows(store, spends)
    return spends


def _write_vendor_rows(store: Any, spends: list[VendorSpend]) -> None:
    """Upsert vendor rows: delete stale rows for this vendor+month, then insert fresh."""
    if not spends:
        return
    month = _month()
    try:
        with store.batch() as w:
            for spend in spends:
                w.execute(
                    "DELETE FROM costs WHERE vendor = ? AND meta LIKE ? AND meta LIKE ?",
                    (spend.vendor, '%"seed": "vendor"%', f'%"month": "{month}"%'),
                )
                meta = json.dumps(
                    {"seed": "vendor", "month": month, **spend.meta},
                    sort_keys=True,
                )
                w.insert(
                    "costs",
                    {
                        "ts": datetime.now(tz=UTC).isoformat(),
                        "vendor": spend.vendor,
                        "category": spend.category,
                        "amount": spend.amount,
                        "currency": "USD",
                        "strategy_version_id": None,
                        "meta": meta,
                    },
                )
    except Exception:  # noqa: BLE001
        pass
