# intent: cost-transparency writers; inputs: a Store, per-call LLM metadata, or nothing (infra seed
# is deterministic); outputs: rows in llm_calls and costs tables; invariants: all writes are
# best-effort and offline-safe (no external billing calls), never block the calling path, degrade
# honestly when the store is unavailable. LLM-optional: pass store=None to skip recording.

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Monthly infra lines — sourced from cosmu.costs.operating_costs (SINGLE SOURCE
# OF TRUTH). These are STATIC estimates — no live billing API. We seed them once
# on first call and update/re-seed at most once per calendar month (idempotent).
# Flat LLM subs (Claude, Cursor) live in operating_costs.FLAT_SUBSCRIPTIONS and
# are owned by the vendor fetchers, NOT here, so each is counted exactly once.
# ---------------------------------------------------------------------------

from cosmu.costs.operating_costs import INFRA_DATA_LINES as _INFRA_LINES

# ---------------------------------------------------------------------------
# LLM cost table: ($/1k_input_tokens, $/1k_output_tokens) by model id prefix.
#
# Rules:
#   1. Model ids ending ":free" → $0 (OpenRouter free tier — no spend).
#   2. Grok / xAI models (prefix "grok-"): use published xAI pricing.
#   3. Paid OpenRouter passthrough (prefix "openai/", "anthropic/", etc.): use
#      OpenRouter published rates as of 2026-06.  Rates are per-1k tokens.
#   4. Unknown paid models → fall back to 0 (honest unknown, not fabricated).
#
# Source: https://openrouter.ai/models  /  https://x.ai/api
# Update when we wire new paid models.
# ---------------------------------------------------------------------------

# Keyed by model_id prefix (longest match wins).
# Tuple: ($/1k_in, $/1k_out)
_MODEL_COST_PER_1K: list[tuple[str, float, float]] = [
    # xAI Grok models (billed via xAI directly or OpenRouter passthrough)
    ("grok-3-mini",          0.30, 0.50),   # grok-3-mini-beta
    ("grok-3",               2.00, 10.00),  # grok-3 (flagship)
    ("grok-2",               2.00, 10.00),  # grok-2-1212 / grok-2-vision
    ("grok-1",               0.00, 0.00),   # open-weights, $0
    ("grok-",                2.00, 10.00),  # catch-all for any future grok variant
    # OpenRouter passthrough: anthropic
    ("anthropic/claude-3-5-sonnet",  3.00, 15.00),
    ("anthropic/claude-3-5-haiku",   0.80,  4.00),
    ("anthropic/claude-3-opus",     15.00, 75.00),
    ("anthropic/claude-3-sonnet",    3.00, 15.00),
    ("anthropic/claude-3-haiku",     0.25,  1.25),
    # OpenRouter passthrough: openai (longer/more-specific prefixes must come first)
    ("openai/gpt-4o-mini",   0.15,  0.60),
    ("openai/gpt-4o",        2.50, 10.00),
    ("openai/o3-mini",       1.10,  4.40),
    ("openai/o1",           15.00, 60.00),
    # OpenRouter passthrough: google
    ("google/gemini-2.0-flash",  0.10, 0.40),
    ("google/gemini-2.5-pro",    1.25, 10.00),
    # OpenRouter passthrough: meta / mistral
    ("meta-llama/",          0.07, 0.07),   # rough average for 70B tiers
    ("mistralai/mistral-large", 2.00, 6.00),
]


def _llm_cost_usd(model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Return the estimated USD cost for one LLM call given a model id and token counts.

    Falls back to $0.0 for:
      - model ids ending ":free" (OpenRouter free tier)
      - unknown model ids (honest unknown — never fabricated)

    Cost table is a static snapshot; update _MODEL_COST_PER_1K when wiring new paid models.
    """
    if not model_id or model_id.endswith(":free"):
        return 0.0
    # Longest-prefix match (table is ordered longest-first for each prefix group).
    for prefix, cost_in, cost_out in _MODEL_COST_PER_1K:
        if model_id.startswith(prefix):
            return (tokens_in / 1000.0) * cost_in + (tokens_out / 1000.0) * cost_out
    # Unknown paid model — record $0 (honest unknown).
    return 0.0


def _utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def _month_key() -> str:
    """YYYY-MM — used to make the infra seed idempotent per calendar month."""
    return datetime.now(tz=UTC).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# LLM call writer
# ---------------------------------------------------------------------------


@dataclass
class LlmCallRecorder:
    """Context-manager that times an LLM call and writes one row to llm_calls.

    Usage (in the chat seam):
        with LlmCallRecorder(store=store, task="author", tier="mid", model_id=model) as rec:
            raw = chat(model, prompt)
            rec.tokens_in = count_tokens(prompt)    # optional; 0 if unknown
            rec.tokens_out = count_tokens(raw or "")

    If store is None or the write fails, recording is silently skipped — the calling path
    (LLM seam) must never depend on this writer.
    """

    store: Any  # cosmu.knowledge.store.Store | None
    task: str
    tier: str
    model_id: str
    strategy_version_id: str | None = None
    trace_id: str | None = None
    account_id: str | None = None  # which model account paid (set by the failover router); NULL for flat-sub paths
    tokens_in: int = 0
    tokens_out: int = 0
    _start: float = field(default_factory=time.monotonic, init=False)

    def __enter__(self) -> "LlmCallRecorder":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        if self.store is None:
            return
        latency_ms = int((time.monotonic() - self._start) * 1000)
        # Compute real cost from the model pricing table.  Falls back to $0 for :free tier
        # models and unknown model ids (never fabricates a number).
        cost = _llm_cost_usd(self.model_id, self.tokens_in, self.tokens_out)
        try:
            self.store.insert(
                "llm_calls",
                {
                    "ts": _utcnow(),
                    "tier": self.tier,
                    "model_id": self.model_id,
                    "task": self.task,
                    "tokens_in": self.tokens_in,
                    "tokens_out": self.tokens_out,
                    "cost": cost,
                    "latency_ms": latency_ms,
                    "confidence": None,
                    "strategy_version_id": self.strategy_version_id,
                    "trace_id": self.trace_id,
                    "account_id": self.account_id,
                },
            )
        except Exception:  # noqa: BLE001 — cost recording must never crash the caller
            pass


# ---------------------------------------------------------------------------
# Infra seed writer
# ---------------------------------------------------------------------------


def seed_infra_costs(store: Any) -> int:
    """Write the static monthly infra lines (from MASTER_PLAN §9) into the costs table.

    Idempotent: inserts only ONE set of rows per calendar month — identified by a meta JSON
    field `{"seed": "infra", "month": "YYYY-MM"}`.  Returns the number of rows written
    (0 if already seeded this month or if the store is unavailable).

    Call this on app startup or whenever GET /costs is invoked — it is cheap, deterministic,
    and requires no external billing API.  Degrades silently if the store is not ready.
    """
    if store is None:
        return 0
    month = _month_key()
    import json

    try:
        # Idempotency check: is this month's infra seed already present? The inserted rows carry extra
        # keys (note/amount_min/amount_max), so match on the stable seed+month substrings, NOT exact meta
        # equality (an exact meta match never matched because inserted rows carry additional keys).
        existing = store.row(
            "SELECT id FROM costs WHERE meta LIKE ? AND meta LIKE ? LIMIT 1",
            ('%"seed": "infra"%', f'%"month": "{month}"%'),
        )
        if existing:
            return 0

        written = 0
        for line in _INFRA_LINES:
            # Use the midpoint of the min/max range as the recorded amount.
            # If min == max (e.g. free tiers), that value is used directly.
            amount = (line["amount_min"] + line["amount_max"]) / 2.0
            meta = json.dumps(
                {"seed": "infra", "month": month, "note": line["note"],
                 "amount_min": line["amount_min"], "amount_max": line["amount_max"]},
                sort_keys=True,
            )
            store.insert(
                "costs",
                {
                    "ts": _utcnow(),
                    "vendor": line["vendor"],
                    "category": line["category"],
                    "amount": amount,
                    "currency": "USD",
                    "strategy_version_id": None,
                    "meta": meta,
                },
            )
            written += 1
        return written
    except Exception:  # noqa: BLE001 — seed is best-effort; never crash the caller
        return 0


# ---------------------------------------------------------------------------
# Trading-fee aggregator
# ---------------------------------------------------------------------------


def record_trading_fees(store: Any) -> int:
    """Aggregate real fees paid from the executions table into the costs table.

    Writes one ``category="trading"`` row per (strategy_version_id, month) for
    any month that has fees not yet recorded.  Idempotent: skips months already
    present, identified by matching the seed and month substrings in the meta
    JSON field for the same (strategy_version_id, month) combination.

    Returns the number of new cost rows written (0 on error or when all months
    are already recorded).  Best-effort — never crashes the caller.
    """
    if store is None:
        return 0
    import json

    try:
        # Sum fees per (strategy_version_id, month).  The ts column is ISO-8601 text;
        # strftime works on both SQLite and Postgres (via the substring fallback).
        # We use SUBSTR(ts, 1, 7) which is portable: "2026-06" from "2026-06-15T12:00:00+00:00".
        fee_rows = store.rows(
            """
            SELECT strategy_version_id,
                   SUBSTR(ts, 1, 7) AS month,
                   SUM(CAST(fee AS REAL)) AS total_fee
            FROM executions
            WHERE fee IS NOT NULL AND CAST(fee AS REAL) > 0
            GROUP BY strategy_version_id, SUBSTR(ts, 1, 7)
            """
        )
        if not fee_rows:
            return 0

        written = 0
        for r in fee_rows:
            svid = r.get("strategy_version_id")
            month = r.get("month") or ""
            total_fee = float(r.get("total_fee") or 0)
            if total_fee <= 0 or not month:
                continue

            # Idempotency: skip this (strategy, month) if already recorded.
            # The meta is serialized with json.dumps(sort_keys=True) which adds a space after ':',
            # so we match `"seed": "trading_fees"` (with the space).
            seed_marker = '"seed": "trading_fees"'
            params: tuple
            if svid:
                existing = store.row(
                    "SELECT id FROM costs WHERE strategy_version_id = ? AND meta LIKE ? AND meta LIKE ? LIMIT 1",
                    (svid, f'%{seed_marker}%', f'%"month": "{month}"%'),
                )
            else:
                existing = store.row(
                    "SELECT id FROM costs WHERE strategy_version_id IS NULL AND meta LIKE ? AND meta LIKE ? LIMIT 1",
                    (f'%{seed_marker}%', f'%"month": "{month}"%'),
                )
            if existing:
                continue

            meta = json.dumps({"seed": "trading_fees", "month": month}, sort_keys=True)
            store.insert(
                "costs",
                {
                    "ts": _utcnow(),
                    "vendor": "Exchange",
                    "category": "trading",
                    "amount": total_fee,
                    "currency": "USD",
                    "strategy_version_id": svid,
                    "meta": meta,
                },
            )
            written += 1

        return written
    except Exception:  # noqa: BLE001 — fee recording is best-effort; never crash the caller
        return 0
