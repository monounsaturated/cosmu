# intent: the FAILOVER ROUTER wrapping the chat() seam (lab/llm.py). Pre-checks credits/ledger, ISSUES the call on
# the active account, and on a bust (HTTP 402/403/insufficient-credit) ADVANCES to the next account in the pool —
# then degrades paid -> next account -> OpenRouter ":free" -> deterministic (None). inputs: a Store (registry +
# ledger) + an injectable HTTP poster (offline-testable) + process env (secret resolution); outputs: model text or
# None (-> caller's deterministic path), one llm_calls row per real call stamped with the paying account_id, and a
# persisted work-unit boundary so a mid-call bust never loses progress. invariants: we do NOT use OpenRouter's
# auto-fallback (it EXCLUDES 402/403 budget errors); best-effort + offline-safe; secrets never enter prompt/DB.

from __future__ import annotations

import json
import logging
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import certifi

from cosmu.costs import accounts as acct_mod
from cosmu.costs.accounts import ModelAccount
from cosmu.lab.llm import OPENROUTER_URL, XAI_URL

_LOG = logging.getLogger(__name__)
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# The free-tier model used as the penultimate rung of the ladder (paid -> next account -> :free -> deterministic).
# A stale id just 404s -> we return None -> the caller's deterministic path. Refresh from openrouter.ai/models.
DEFAULT_FREE_MODEL = "deepseek/deepseek-chat-v3-0324:free"

_PROVIDER_URL: dict[str, str] = {"openrouter": OPENROUTER_URL, "xai": XAI_URL}

# HTTP codes that mean THIS ACCOUNT is out of budget / blocked (advance to the next account). 429 is included only
# when the body signals a credit/quota problem (a plain rate-limit is transient -> cooling, not exhausted).
_BLOCK_CODES = {402, 403}


class AccountBlocked(Exception):
    """Raised when a metered call fails because the ACCOUNT is out of credit / blocked (402/403/insufficient
    credit) — the signal for the router to advance to the next account. Distinct from a generic transport error
    (which degrades straight to the next rung), so we never burn the pool on a network blip."""

    def __init__(self, account_id: str, code: int | None, reason: str) -> None:
        super().__init__(f"account {account_id} blocked (code={code}): {reason}")
        self.account_id = account_id
        self.code = code
        self.reason = reason


def _utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


# A low-level poster: (url, headers, body) -> (status_code, response_text). Injectable so CI/tests run offline.
HttpPost = Callable[[str, dict[str, str], bytes], "tuple[int, str]"]


def _default_http_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:  # noqa: S310 — fixed host
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 4xx/5xx — keep the code so the router can classify a budget block
        try:
            text = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            text = ""
        return exc.code, text


def _looks_like_credit_block(status: int, body: str) -> bool:
    """A 429 (or any code) whose body mentions credit/quota/insufficient is an account-budget block, not a blip."""
    low = (body or "").lower()
    return any(k in low for k in ("insufficient", "credit", "quota", "out of", "payment", "billing"))


def issue_once(
    account: ModelAccount,
    model_id: str,
    prompt: str,
    *,
    http_post: HttpPost | None = None,
) -> str | None:
    """Issue ONE completion on a specific account. Returns the assistant text, or None on a non-blocking failure
    (empty/garbled response). Raises AccountBlocked on a 402/403/insufficient-credit so the router fails over.
    The secret is resolved from env here and lives ONLY in the Authorization header — never the prompt/payload."""
    key = account.resolve_key()
    if key is None:
        raise AccountBlocked(account.account_id, None, f"no secret at env {account.key_ref}")
    url = _PROVIDER_URL.get(account.provider, OPENROUTER_URL)
    post = http_post or _default_http_post
    body = json.dumps(
        {"model": model_id, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    ).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Cosmu Lab"}
    try:
        status, text = post(url, headers, body)
    except Exception as exc:  # noqa: BLE001 — a transport blip is NOT an account block; degrade, don't burn the pool
        _LOG.warning("failover issue transport error on %s: %s", account.account_id, exc)
        return None
    if status in _BLOCK_CODES or (status == 429 and _looks_like_credit_block(status, text)):
        raise AccountBlocked(account.account_id, status, text[:200])
    if status >= 400:
        # Other 4xx/5xx (bad model id, server error) — not account-specific; degrade to the next rung.
        _LOG.warning("failover issue HTTP %s on %s: %s", status, account.account_id, text[:200])
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    choices = payload.get("choices") or []
    if not choices:
        return None
    return choices[0].get("message", {}).get("content")


# Notifier hook: called when an account busts mid-flight. (account_id, code, reason) -> None. Reuses alerts.py Slack
# when wired by the caller; defaults to a log line so the bust is never silent.
Notifier = Callable[[str, "int | None", str], None]


@dataclass
class FailoverRouter:
    """Wraps the chat() seam with account rotation + the degradation ladder + the work-unit boundary.

    Use `.chat` as a drop-in ChatFn (model_id, prompt) -> str|None for propose_structure / route_and_propose, and
    wrap each unit of work in `with router.persist_unit(key, task=...):` so a bust never loses progress."""

    store: Any
    free_model_id: str = DEFAULT_FREE_MODEL
    http_post: HttpPost | None = None
    notifier: Notifier | None = None
    seed: bool = True  # register the pool from env on construction (idempotent)
    _active_unit_id: str | None = None

    def __post_init__(self) -> None:
        if self.seed and self.store is not None:
            try:
                acct_mod.seed_accounts_from_env(self.store)
            except Exception:  # noqa: BLE001 — seeding is best-effort
                pass

    # -- the ladder ---------------------------------------------------------

    def chat(self, model_id: str, prompt: str) -> str | None:
        """ChatFn with failover. Tries each ACTIVE account in priority order; on a bust marks it exhausted, pings
        the operator, and advances. When the paid pool is dry, drops to a :free model; on failure there, returns
        None so the caller uses its deterministic path. Every successful real call writes one llm_calls row
        attributed to the paying account."""
        tried: set[str] = set()
        # 1) paid pool — re-select after each bust so status changes are honoured.
        while True:
            account = acct_mod.select_account(self.store)
            if account is None or account.account_id in tried:
                break
            tried.add(account.account_id)
            try:
                text = self._issue_recorded(account, model_id, prompt)
            except AccountBlocked as blocked:
                acct_mod.set_status(self.store, account.account_id, acct_mod.STATUS_EXHAUSTED)
                self._notify(blocked.account_id, blocked.code, blocked.reason)
                continue  # advance to the next account
            if text is not None:
                return text
            # Non-blocking failure on a healthy account — don't burn the rest of the pool; drop to :free.
            break

        # 2) :free rung — any account whose key resolves can ride the free tier (cost $0).
        free_text = self._try_free(prompt)
        if free_text is not None:
            return free_text

        # 3) deterministic — the caller falls back when we return None.
        return None

    def _try_free(self, prompt: str) -> str | None:
        for account in acct_mod.list_accounts(self.store, provider="openrouter"):
            if account.resolve_key() is None:
                continue
            try:
                return self._issue_recorded(account, self.free_model_id, prompt, tier="free")
            except AccountBlocked:
                continue  # even the free tier blocked on this key — try the next
        return None

    def _issue_recorded(
        self, account: ModelAccount, model_id: str, prompt: str, *, tier: str = "auto"
    ) -> str | None:
        """Issue one call AND record it in llm_calls stamped with the paying account_id (best-effort). Also stamps
        the active work-unit (if any) with the account + an attempt bump so a resume knows who was paying."""
        from cosmu.costs.writer import LlmCallRecorder

        self._stamp_unit(account.account_id)
        with LlmCallRecorder(
            store=self.store, task="live_loop", tier=tier, model_id=model_id, account_id=account.account_id
        ) as rec:
            text = issue_once(account, model_id, prompt, http_post=self.http_post)
            rec.tokens_in = len(prompt) // 4
            rec.tokens_out = len(text) // 4 if text else 0
        return text

    def _notify(self, account_id: str, code: int | None, reason: str) -> None:
        if self.notifier is not None:
            try:
                self.notifier(account_id, code, reason)
            except Exception:  # noqa: BLE001 — a notify failure must never break the loop
                pass
        else:
            _LOG.warning("model account %s busted (code=%s): %s — failing over", account_id, code, reason)

    # -- the work-unit boundary --------------------------------------------

    @contextmanager
    def persist_unit(self, unit_key: str, *, task: str, trace_id: str | None = None) -> Iterator[str]:
        """Persist the work-unit boundary BEFORE the call is issued (status='pending'), mark it 'done' on success
        and 'failed' on error — re-raising. A crash/bust mid-call leaves a resumable 'pending' row, so the research
        cohorts (which already iterate per-asset/per-headline) never silently lose progress. Best-effort: a store
        failure degrades to a plain pass-through (the call still runs)."""
        unit_id = str(uuid4())
        prev_active = self._active_unit_id
        self._record_unit(unit_id, unit_key=unit_key, task=task, trace_id=trace_id, status="pending")
        self._active_unit_id = unit_id
        try:
            yield unit_id
        except Exception:
            self._set_unit_status(unit_id, "failed")
            self._active_unit_id = prev_active
            raise
        else:
            self._set_unit_status(unit_id, "done")
            self._active_unit_id = prev_active

    def open_units(self, *, task: str | None = None) -> list[dict[str, Any]]:
        """Resumable units left 'pending' by a previous crash/bust — the caller re-runs these. Best-effort."""
        if self.store is None:
            return []
        try:
            if task:
                return self.store.rows(
                    "SELECT * FROM llm_work_units WHERE status = 'pending' AND task = ? ORDER BY ts ASC", (task,)
                )
            return self.store.rows("SELECT * FROM llm_work_units WHERE status = 'pending' ORDER BY ts ASC")
        except Exception:  # noqa: BLE001
            return []

    def _record_unit(
        self, unit_id: str, *, unit_key: str, task: str, trace_id: str | None, status: str
    ) -> None:
        if self.store is None:
            return
        try:
            now = _utcnow()
            self.store.insert(
                "llm_work_units",
                {
                    "id": unit_id,
                    "ts": now,
                    "trace_id": trace_id,
                    "task": task,
                    "unit_key": unit_key,
                    "status": status,
                    "account_id": None,
                    "attempts": 0,
                    "updated_ts": now,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def _set_unit_status(self, unit_id: str, status: str) -> None:
        if self.store is None:
            return
        try:
            with self.store.batch() as w:
                w.execute(
                    "UPDATE llm_work_units SET status = ?, updated_ts = ? WHERE id = ?",
                    (status, _utcnow(), unit_id),
                )
        except Exception:  # noqa: BLE001
            pass

    def _stamp_unit(self, account_id: str) -> None:
        """Attribute the active work-unit to the account now paying for it + bump the attempt counter."""
        if self.store is None or self._active_unit_id is None:
            return
        try:
            with self.store.batch() as w:
                w.execute(
                    "UPDATE llm_work_units SET account_id = ?, attempts = attempts + 1, updated_ts = ? WHERE id = ?",
                    (account_id, _utcnow(), self._active_unit_id),
                )
        except Exception:  # noqa: BLE001
            pass
