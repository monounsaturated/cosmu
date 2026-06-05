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
# Monthly infra lines from MASTER_PLAN §9 (source of truth).
# These are STATIC estimates — no live billing API. We seed them once on first
# call and update/re-seed at most once per calendar month (idempotent).
# ---------------------------------------------------------------------------

_INFRA_LINES: list[dict[str, Any]] = [
    {"vendor": "Railway",  "category": "infra",  "amount_min": 5.0,  "amount_max": 20.0,  "note": "always-on engine API + crons"},
    {"vendor": "Supabase", "category": "infra",  "amount_min": 0.0,  "amount_max": 25.0,  "note": "Postgres + pgvector; free tier → Pro"},
    {"vendor": "Vercel",   "category": "infra",  "amount_min": 0.0,  "amount_max": 0.0,   "note": "web; hobby tier — $0"},
    {"vendor": "Fly.io",   "category": "infra",  "amount_min": 25.0, "amount_max": 35.0,  "note": "24/7 4 GB sims/ML/scrape worker (planned)"},
    {"vendor": "FRED",     "category": "data",   "amount_min": 0.0,  "amount_max": 0.0,   "note": "macro — free"},
    {"vendor": "GDELT",    "category": "data",   "amount_min": 0.0,  "amount_max": 0.0,   "note": "news — free"},
    {"vendor": "Polymarket","category": "data",  "amount_min": 0.0,  "amount_max": 0.0,   "note": "prediction markets — free"},
    {"vendor": "LunarCrush","category": "data",  "amount_min": 0.0,  "amount_max": 24.0,  "note": "social signals — optional paid tier"},
]

# ---------------------------------------------------------------------------
# OpenRouter approximate cost-per-token for the :free tier models.
# All :free models are $0/token. Recorded as $0 so the ledger is honest
# (no spend tracked) rather than estimating paid usage that hasn't happened.
# If a paid model id is wired, we fall back to 0 (unknown) — still honest.
# ---------------------------------------------------------------------------

_FREE_COST: float = 0.0


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
        # :free tier → $0; if a paid model is used the cost is unknown here (no billing API).
        # We record 0 rather than fabricate an estimate — the ledger stays honest.
        cost = _FREE_COST
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
        # equality (the old `meta = seed_meta` check never matched its own rows → re-seeded every call).
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
