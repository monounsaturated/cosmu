# Offline tests for the modular compute-spend failover: the model_accounts registry, the failover ROUTER
# (paid -> next account -> :free -> deterministic), the $15-fixed-stride notifier, account_id on the llm_calls
# ledger, and the persisted work-unit boundary. All HTTP is injected (no sockets — the session conftest blocks them).

from __future__ import annotations

import json

import pytest

from cosmu.config.settings import Settings
from cosmu.costs import accounts as acct_mod
from cosmu.costs.accounts import (
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    list_accounts,
    register_account,
    seed_accounts_from_env,
    select_account,
    sync_spend_from_ledger,
)
from cosmu.costs.alerts import check_account_strides
from cosmu.costs.failover import AccountBlocked, FailoverRouter, issue_once
from cosmu.knowledge.store import Store


@pytest.fixture
def store(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/cs.sqlite3", openrouter_api_key=None)
    return Store(settings=settings)


def _ok_body(text: str = "hello from model") -> str:
    return json.dumps({"choices": [{"message": {"content": text}}]})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_register_is_idempotent_and_preserves_spend(store):
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A", free_credit_usd=30)
    # simulate spend accrued
    with store.batch() as w:
        w.execute("UPDATE model_accounts SET spend_used = 12.0, notified_floor = 0 WHERE account_id = 'or-a'")
    # re-register (e.g. a redeploy) must NOT wipe spend
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A", free_credit_usd=30, priority=5)
    accts = list_accounts(store)
    assert len(accts) == 1
    assert accts[0].spend_used == 12.0
    assert accts[0].priority == 5


def test_seed_from_env_registers_primary_and_numbered(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY_PRIMARY")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "KEY_SECOND")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    n = seed_accounts_from_env(store)
    assert n == 2
    accts = list_accounts(store, provider="openrouter")
    ids = [a.account_id for a in accts]
    assert ids == ["openrouter-primary", "openrouter-2"]  # ordered by priority
    assert accts[0].priority == 0 and accts[1].priority == 2


def test_select_account_skips_keyless_and_exhausted(store, monkeypatch):
    monkeypatch.setenv("OR_A", "")  # present but empty -> no usable key
    monkeypatch.setenv("OR_B", "KEY_B")
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A", priority=0)
    register_account(store, account_id="or-b", provider="openrouter", key_ref="OR_B", priority=1)
    chosen = select_account(store)
    assert chosen is not None and chosen.account_id == "or-b"  # or-a skipped (no key)

    acct_mod.set_status(store, "or-b", STATUS_EXHAUSTED)
    assert select_account(store) is None  # both unusable -> dry


# ---------------------------------------------------------------------------
# issue_once classification
# ---------------------------------------------------------------------------


def test_issue_once_raises_on_402(store, monkeypatch):
    monkeypatch.setenv("OR_A", "KEY_A")
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A")
    acct = list_accounts(store)[0]

    def post(url, headers, body):
        return 402, '{"error":"insufficient credits"}'

    with pytest.raises(AccountBlocked) as ei:
        issue_once(acct, "some/model", "hi", http_post=post)
    assert ei.value.code == 402


def test_issue_once_transport_blip_returns_none_not_block(store, monkeypatch):
    monkeypatch.setenv("OR_A", "KEY_A")
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A")
    acct = list_accounts(store)[0]

    def post(url, headers, body):
        raise OSError("connection reset")

    # a network blip is NOT an account block -> None (degrade), no AccountBlocked
    assert issue_once(acct, "some/model", "hi", http_post=post) is None


# ---------------------------------------------------------------------------
# Failover ladder
# ---------------------------------------------------------------------------


def test_failover_advances_to_next_account_on_block(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY_PRIMARY")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "KEY_SECOND")
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    calls: list[str] = []

    def post(url, headers, body):
        auth = headers["Authorization"]
        calls.append(auth)
        if "KEY_PRIMARY" in auth:
            return 402, '{"error":"insufficient credits"}'  # primary busts
        return 200, _ok_body("second-account reply")

    router = FailoverRouter(store=store, http_post=post)
    out = router.chat("paid/model", "do the thing")

    assert out == "second-account reply"
    # primary tried then second
    assert any("KEY_PRIMARY" in c for c in calls) and any("KEY_SECOND" in c for c in calls)
    # primary marked exhausted, second still active
    accts = {a.account_id: a for a in list_accounts(store)}
    assert accts["openrouter-primary"].status == STATUS_EXHAUSTED
    assert accts["openrouter-2"].status == STATUS_ACTIVE
    # ledger row attributed to the paying (second) account
    rows = store.rows("SELECT account_id, model_id FROM llm_calls WHERE account_id IS NOT NULL")
    assert any(r["account_id"] == "openrouter-2" for r in rows)


def test_failover_degrades_to_free_then_deterministic(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY_PRIMARY")
    monkeypatch.delenv("OPENROUTER_API_KEY_2", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    seen_models: list[str] = []

    def post(url, headers, body):
        model = json.loads(body)["model"]
        seen_models.append(model)
        if model.endswith(":free"):
            return 200, _ok_body("free-tier reply")
        return 402, '{"error":"insufficient credits"}'  # paid blocked

    router = FailoverRouter(store=store, http_post=post)
    out = router.chat("paid/model", "prompt")
    assert out == "free-tier reply"
    assert any(m.endswith(":free") for m in seen_models)

    # now make even :free fail -> deterministic (None)
    def post_all_block(url, headers, body):
        return 402, '{"error":"insufficient credits"}'

    # reset the account so it's active again
    acct_mod.set_status(store, "openrouter-primary", STATUS_ACTIVE)
    with store.batch() as w:
        w.execute("UPDATE model_accounts SET spend_used = 0")
    router2 = FailoverRouter(store=store, http_post=post_all_block, seed=False)
    assert router2.chat("paid/model", "prompt") is None


def test_failover_notifier_fires_on_bust(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY_PRIMARY")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "KEY_SECOND")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    busts: list[tuple] = []

    def post(url, headers, body):
        if "KEY_PRIMARY" in headers["Authorization"]:
            return 403, "blocked"
        return 200, _ok_body()

    router = FailoverRouter(
        store=store, http_post=post, notifier=lambda aid, code, reason: busts.append((aid, code))
    )
    router.chat("paid/model", "x")
    assert busts == [("openrouter-primary", 403)]


# ---------------------------------------------------------------------------
# Work-unit boundary
# ---------------------------------------------------------------------------


def test_persist_unit_marks_done_and_stamps_account(store, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY_PRIMARY")
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    def post(url, headers, body):
        return 200, _ok_body()

    router = FailoverRouter(store=store, http_post=post)
    with router.persist_unit("ETHUSDT", task="live_loop", trace_id="t1") as uid:
        assert router.chat("paid/model", "p") is not None
    row = store.row("SELECT * FROM llm_work_units WHERE id = ?", (uid,))
    assert row["status"] == "done"
    assert row["account_id"] == "openrouter-primary"
    assert int(row["attempts"]) == 1
    assert router.open_units() == []  # nothing left pending


def test_persist_unit_marks_failed_and_keeps_resumable(store):
    router = FailoverRouter(store=store, seed=False)
    with pytest.raises(ValueError):
        with router.persist_unit("BTCUSDT", task="live_loop"):
            raise ValueError("boom mid-unit")
    row = store.row("SELECT status FROM llm_work_units WHERE unit_key = 'BTCUSDT'")
    assert row["status"] == "failed"


# ---------------------------------------------------------------------------
# Ledger reconciliation + $15 stride notifier
# ---------------------------------------------------------------------------


def test_sync_spend_from_ledger_parks_exhausted(store, monkeypatch):
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A", free_credit_usd=30)
    # 31 dollars of calls this month attributed to or-a
    store.insert("llm_calls", {
        "ts": "2026-06-10T00:00:00+00:00", "tier": "auto", "model_id": "paid/m", "task": "live_loop",
        "tokens_in": 1000, "tokens_out": 1000, "cost": 31.0, "latency_ms": 10, "account_id": "or-a",
    })
    n = sync_spend_from_ledger(store, period="2026-06")
    assert n == 1
    acct = list_accounts(store)[0]
    assert acct.spend_used == 31.0
    assert acct.status == STATUS_EXHAUSTED  # over free credit -> parked


def test_15_dollar_stride_notifier_fires_once_per_stride(store, monkeypatch):
    posts: list[str] = []
    settings = type("S", (), {"slack_webhook_url": "http://hook"})()
    register_account(store, account_id="or-a", provider="openrouter", key_ref="OR_A", free_credit_usd=30)
    with store.batch() as w:
        w.execute("UPDATE model_accounts SET spend_used = 16.0 WHERE account_id = 'or-a'")  # crosses $15

    def http_post(url, payload):
        posts.append(json.loads(payload)["text"])

    alerts = check_account_strides(store, settings, _http_post=http_post)
    assert len(alerts) == 1 and alerts[0].floor == 1
    assert len(posts) == 1 and "$15 stride" in posts[0]
    # notified_floor bumped -> no re-fire
    assert check_account_strides(store, settings, _http_post=http_post) == []
    assert len(posts) == 1
    # a recommendation row was written
    recs = store.rows("SELECT kind FROM recommendations WHERE kind = 'account_spend_stride'")
    assert len(recs) == 1

    # crossing the NEXT stride ($30 ~ exhaustion) fires again
    with store.batch() as w:
        w.execute("UPDATE model_accounts SET spend_used = 30.0 WHERE account_id = 'or-a'")
    alerts2 = check_account_strides(store, settings, _http_post=http_post)
    assert len(alerts2) == 1 and alerts2[0].floor == 2
    assert "EXHAUSTED" in posts[-1]
