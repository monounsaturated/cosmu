# intent: the model_accounts REGISTRY — one row per metered model account (e.g. an OpenRouter key with ~$30 free
# credit). The failover router (costs/failover.py) rotates through ACTIVE accounts with remaining credit when one
# busts. inputs: a Store + process env (for key resolution); outputs: typed ModelAccount rows + spend reconciled
# from the llm_calls ledger. invariants: secrets NEVER touch the DB (key_ref holds the ENV VAR NAME, the secret is
# resolved from os.environ at call time); all writes best-effort + offline-safe; selection is deterministic
# (priority asc, then account_id) so failover order is stable and testable.
#
# ⚠️ ToS NOTE (surfaced to the operator, who accepts the risk): chaining serial free-credit accounts to dodge
# limits likely violates provider ToS (multi-account / payment-less-signup detection). This module is the
# mechanism; the operator owns the decision. Strategy AUTHORING stays on the flat Claude Code sub — the metered
# failover pool is for the recurring LIVE/research agent loop only.

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Account lifecycle vocabulary (no DB CHECK by repo convention — enforced here + by a guard test).
STATUS_ACTIVE = "active"
STATUS_COOLING = "cooling"      # transiently rate-limited / 429 — skip for now, may recover
STATUS_EXHAUSTED = "exhausted"  # hard-blocked (402/403/insufficient credit) — out of the pool

DEFAULT_FREE_CREDIT_USD = 30.0
# Leave a small head-room buffer so we fail OVER before a hard 402 mid-unit, not after.
SELECT_REMAINING_FLOOR_USD = 0.25


def _utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class ModelAccount:
    account_id: str
    provider: str
    key_ref: str
    free_credit_usd: float = DEFAULT_FREE_CREDIT_USD
    spend_used: float = 0.0
    status: str = STATUS_ACTIVE
    notified_floor: int = 0
    priority: int = 0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, float(self.free_credit_usd) - float(self.spend_used))

    @property
    def has_headroom(self) -> bool:
        """True if this account can still pay for a (small) call without busting immediately."""
        return self.status == STATUS_ACTIVE and self.remaining_usd > SELECT_REMAINING_FLOOR_USD

    def resolve_key(self) -> str | None:
        """Resolve the actual secret from process env by its NAME. The secret never lives in the DB or the row."""
        val = os.environ.get(self.key_ref)
        return val.strip() if val and val.strip() else None


def _row_to_account(r: dict[str, Any]) -> ModelAccount:
    return ModelAccount(
        account_id=str(r["account_id"]),
        provider=str(r["provider"]),
        key_ref=str(r["key_ref"]),
        free_credit_usd=float(r.get("free_credit_usd") or 0),
        spend_used=float(r.get("spend_used") or 0),
        status=str(r.get("status") or STATUS_ACTIVE),
        notified_floor=int(r.get("notified_floor") or 0),
        priority=int(r.get("priority") or 0),
    )


def list_accounts(store: Any, *, provider: str | None = None) -> list[ModelAccount]:
    """All registered accounts, ordered by (priority asc, account_id) — the stable failover order. Empty on error."""
    if store is None:
        return []
    try:
        if provider:
            rows = store.rows(
                "SELECT * FROM model_accounts WHERE provider = ? ORDER BY priority ASC, account_id ASC",
                (provider,),
            )
        else:
            rows = store.rows("SELECT * FROM model_accounts ORDER BY priority ASC, account_id ASC")
        return [_row_to_account(r) for r in rows]
    except Exception:  # noqa: BLE001 — registry reads are best-effort; never crash the caller
        return []


def get_account(store: Any, account_id: str) -> ModelAccount | None:
    if store is None:
        return None
    try:
        r = store.row("SELECT * FROM model_accounts WHERE account_id = ?", (account_id,))
        return _row_to_account(r) if r else None
    except Exception:  # noqa: BLE001
        return None


def register_account(
    store: Any,
    *,
    account_id: str,
    provider: str,
    key_ref: str,
    free_credit_usd: float = DEFAULT_FREE_CREDIT_USD,
    priority: int = 0,
) -> bool:
    """Idempotent upsert of one account. Does NOT reset spend_used/status/notified_floor on a re-register (so a
    redeploy can re-declare the pool without wiping live spend state). Returns True if a row now exists."""
    if store is None:
        return False
    try:
        existing = store.row("SELECT account_id FROM model_accounts WHERE account_id = ?", (account_id,))
        now = _utcnow()
        if existing:
            # Refresh only the declarative fields; preserve spend/status/notified_floor.
            with store.batch() as w:
                w.execute(
                    "UPDATE model_accounts SET provider = ?, key_ref = ?, free_credit_usd = ?, "
                    "priority = ?, updated_ts = ? WHERE account_id = ?",
                    (provider, key_ref, float(free_credit_usd), int(priority), now, account_id),
                )
            return True
        # Explicit INSERT (not store.insert) — model_accounts' PK is account_id, but Writer.insert auto-injects
        # a surrogate `id` column this table does not have.
        with store.batch() as w:
            w.execute(
                "INSERT INTO model_accounts "
                "(account_id, provider, key_ref, free_credit_usd, spend_used, status, notified_floor, "
                "priority, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, provider, key_ref, float(free_credit_usd), 0.0, STATUS_ACTIVE, 0,
                 int(priority), now, now),
            )
        return True
    except Exception:  # noqa: BLE001
        return False


def set_status(store: Any, account_id: str, status: str) -> None:
    """Move an account between active/cooling/exhausted. Best-effort."""
    if store is None:
        return
    try:
        with store.batch() as w:
            w.execute(
                "UPDATE model_accounts SET status = ?, updated_ts = ? WHERE account_id = ?",
                (status, _utcnow(), account_id),
            )
    except Exception:  # noqa: BLE001
        pass


def bump_notified_floor(store: Any, account_id: str, floor: int) -> None:
    if store is None:
        return
    try:
        with store.batch() as w:
            w.execute(
                "UPDATE model_accounts SET notified_floor = ?, updated_ts = ? WHERE account_id = ?",
                (int(floor), _utcnow(), account_id),
            )
    except Exception:  # noqa: BLE001
        pass


def select_account(store: Any, *, provider: str | None = None) -> ModelAccount | None:
    """The next account the failover router should try: the lowest-priority ACTIVE account that still has credit
    head-room. Returns None when the pool is dry → the router degrades to :free, then deterministic."""
    for acct in list_accounts(store, provider=provider):
        if acct.has_headroom and acct.resolve_key() is not None:
            return acct
    return None


def sync_spend_from_ledger(store: Any, *, period: str | None = None) -> int:
    """Reconcile each account's spend_used from the llm_calls ledger (SUM(cost) WHERE account_id = ?). When a
    `period` (YYYY-MM) is given, only that month's calls are summed — matching the monthly free-credit cycle.
    Re-activates an account whose reconciled spend dropped back under its free credit (new month). Returns the
    number of accounts updated. Best-effort."""
    if store is None:
        return 0
    updated = 0
    try:
        accounts = list_accounts(store)
        for acct in accounts:
            if period:
                row = store.row(
                    "SELECT COALESCE(SUM(CAST(cost AS REAL)), 0) AS total FROM llm_calls "
                    "WHERE account_id = ? AND ts LIKE ?",
                    (acct.account_id, f"{period}%"),
                )
            else:
                row = store.row(
                    "SELECT COALESCE(SUM(CAST(cost AS REAL)), 0) AS total FROM llm_calls WHERE account_id = ?",
                    (acct.account_id,),
                )
            total = float(row["total"] or 0) if row else 0.0
            # An exhausted account that has credit again (e.g. a fresh monthly cycle) returns to the pool; an
            # active account that has now spent its credit is parked exhausted.
            new_status = acct.status
            if acct.status == STATUS_EXHAUSTED and total < float(acct.free_credit_usd) - SELECT_REMAINING_FLOOR_USD:
                new_status = STATUS_ACTIVE
            elif acct.status == STATUS_ACTIVE and total >= float(acct.free_credit_usd) - SELECT_REMAINING_FLOOR_USD:
                new_status = STATUS_EXHAUSTED
            with store.batch() as w:
                w.execute(
                    "UPDATE model_accounts SET spend_used = ?, status = ?, updated_ts = ? WHERE account_id = ?",
                    (total, new_status, _utcnow(), acct.account_id),
                )
            updated += 1
        return updated
    except Exception:  # noqa: BLE001
        return updated


# ---------------------------------------------------------------------------
# Env-driven seeding — register the pool from process env, idempotently.
# ---------------------------------------------------------------------------

# Convention: the PRIMARY OpenRouter key is OPENROUTER_API_KEY (priority 0); failover keys are OPENROUTER_API_KEY_2,
# _3, ... (priority = the suffix). xAI uses XAI_API_KEY (+ _2, ...). key_ref stores the env var NAME, so the secret
# stays in process env. This lets the operator grow the pool by adding numbered env vars — no code change.
_PROVIDER_ENV_PREFIX: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
}


def seed_accounts_from_env(store: Any, *, free_credit_usd: float = DEFAULT_FREE_CREDIT_USD, max_suffix: int = 10) -> int:
    """Register one model account per present API-key env var (primary + numbered failover keys). Idempotent —
    safe to call on every boot/refresh. Returns the number of accounts registered/refreshed."""
    if store is None:
        return 0
    seeded = 0
    for provider, prefix in _PROVIDER_ENV_PREFIX.items():
        # primary key has priority 0; OPENROUTER_API_KEY_2 → priority 2, etc.
        candidates: list[tuple[str, int]] = [(prefix, 0)]
        for n in range(2, max_suffix + 1):
            candidates.append((f"{prefix}_{n}", n))
        for env_name, priority in candidates:
            val = os.environ.get(env_name)
            if not val or not val.strip():
                continue
            account_id = f"{provider}-{priority}" if priority else f"{provider}-primary"
            if register_account(
                store,
                account_id=account_id,
                provider=provider,
                key_ref=env_name,
                free_credit_usd=free_credit_usd,
                priority=priority,
            ):
                seeded += 1
    return seeded
