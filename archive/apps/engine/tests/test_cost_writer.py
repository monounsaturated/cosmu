# intent: offline tests for costs/writer.py — LLM pricing table and trading fee aggregator.
# Tests: (1) paid model → non-zero cost; (2) :free model → $0; (3) unknown model → $0; (4) Grok →
# real dollar cost; (5) record_trading_fees writes one category="trading" row per (strategy, month);
# (6) record_trading_fees is idempotent (second call writes 0 rows).

from __future__ import annotations

import json
import uuid

import pytest

from cosmu.costs.writer import _llm_cost_usd, record_trading_fees, seed_infra_costs


# ---------------------------------------------------------------------------
# LLM pricing table
# ---------------------------------------------------------------------------


def test_free_model_id_yields_zero_cost():
    """:free suffix → $0 regardless of token count."""
    cost = _llm_cost_usd("google/gemini-2.0-flash-exp:free", tokens_in=10_000, tokens_out=5_000)
    assert cost == 0.0


def test_unknown_model_yields_zero_cost():
    """An unknown paid model id falls back to $0 (honest unknown, not fabricated)."""
    cost = _llm_cost_usd("somevendor/unknown-model-xyz", tokens_in=1_000, tokens_out=1_000)
    assert cost == 0.0


def test_empty_model_id_yields_zero():
    cost = _llm_cost_usd("", tokens_in=1_000, tokens_out=1_000)
    assert cost == 0.0


def test_grok3_mini_paid_model_yields_nonzero():
    """grok-3-mini-beta is a paid xAI model → cost must be > 0."""
    cost = _llm_cost_usd("grok-3-mini-beta", tokens_in=1_000, tokens_out=1_000)
    assert cost > 0.0


def test_grok3_mini_cost_formula():
    """grok-3-mini: $0.30/1k in + $0.50/1k out.  1k in + 1k out → $0.80."""
    cost = _llm_cost_usd("grok-3-mini-beta", tokens_in=1_000, tokens_out=1_000)
    assert cost == pytest.approx(0.80, rel=1e-6)


def test_grok3_flagship_cost():
    """grok-3: $2.00/1k in + $10.00/1k out.  2k in + 1k out → $14."""
    cost = _llm_cost_usd("grok-3", tokens_in=2_000, tokens_out=1_000)
    assert cost == pytest.approx(2 * 2.00 + 1 * 10.00, rel=1e-6)


def test_openai_gpt4o_cost():
    """openai/gpt-4o: $2.50/1k in + $10.00/1k out.  1k + 1k → $12.50."""
    cost = _llm_cost_usd("openai/gpt-4o", tokens_in=1_000, tokens_out=1_000)
    assert cost == pytest.approx(12.50, rel=1e-6)


def test_openai_gpt4o_mini_cost():
    """openai/gpt-4o-mini: $0.15/1k in + $0.60/1k out.  1k + 1k → $0.75."""
    cost = _llm_cost_usd("openai/gpt-4o-mini", tokens_in=1_000, tokens_out=1_000)
    assert cost == pytest.approx(0.75, rel=1e-6)


def test_anthropic_claude_sonnet_cost():
    """anthropic/claude-3-5-sonnet: $3.00/1k in + $15.00/1k out."""
    cost = _llm_cost_usd("anthropic/claude-3-5-sonnet-20241022", tokens_in=1_000, tokens_out=1_000)
    assert cost == pytest.approx(18.00, rel=1e-6)


def test_zero_tokens_yields_zero():
    """Any model with 0 tokens → $0."""
    cost = _llm_cost_usd("grok-3", tokens_in=0, tokens_out=0)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# Minimal in-memory store for writer tests
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal in-memory store stub (matches the interface used in writer.py)."""

    def __init__(self, exec_rows: list[dict] | None = None):
        self._exec_rows: list[dict] = exec_rows or []
        self.costs: list[dict] = []

    def row(self, sql: str, params: tuple = ()) -> dict | None:
        """Simulate the idempotency check for record_trading_fees.

        The real SQL is one of:
          SELECT id FROM costs WHERE strategy_version_id = ? AND meta LIKE ? AND meta LIKE ?
          SELECT id FROM costs WHERE strategy_version_id IS NULL AND meta LIKE ? AND meta LIKE ?

        We determine which branch by inspecting the SQL then match accordingly.
        """
        if "strategy_version_id = ?" in sql:
            # params = (svid, like_pattern_1, like_pattern_2)
            svid, like1, like2 = params
            needle1 = str(like1).strip("%")
            needle2 = str(like2).strip("%")
            for row in self.costs:
                if (
                    row.get("strategy_version_id") == svid
                    and needle1 in (row.get("meta") or "")
                    and needle2 in (row.get("meta") or "")
                ):
                    return row
        elif "strategy_version_id IS NULL" in sql:
            # params = (like_pattern_1, like_pattern_2)
            like1, like2 = params
            needle1 = str(like1).strip("%")
            needle2 = str(like2).strip("%")
            for row in self.costs:
                if (
                    row.get("strategy_version_id") is None
                    and needle1 in (row.get("meta") or "")
                    and needle2 in (row.get("meta") or "")
                ):
                    return row
        else:
            # Fallback: match all LIKE-style params against meta
            needle_patterns = [str(p).strip("%") for p in params]
            for row in self.costs:
                meta_str = row.get("meta", "")
                if all(p in meta_str for p in needle_patterns):
                    return row
        return None

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        """Return aggregated execution fee rows."""
        if "executions" in sql:
            # Simulate the GROUP BY SUBSTR(ts, 1, 7) aggregation.
            from collections import defaultdict
            agg: dict[tuple, float] = defaultdict(float)
            for r in self._exec_rows:
                svid = r.get("strategy_version_id")
                month = str(r.get("ts", ""))[:7]  # YYYY-MM
                fee = float(r.get("fee", 0) or 0)
                if fee > 0:
                    agg[(svid, month)] += fee
            return [
                {"strategy_version_id": k[0], "month": k[1], "total_fee": v}
                for k, v in agg.items()
            ]
        return []

    def insert(self, table: str, row: dict) -> str:
        row_id = str(uuid.uuid4())
        row = {"id": row_id, **row}
        if table == "costs":
            self.costs.append(row)
        return row_id


# ---------------------------------------------------------------------------
# record_trading_fees
# ---------------------------------------------------------------------------


def test_record_trading_fees_writes_one_row_per_strategy_month():
    """One (strategy, month) pair with positive fee → one cost row with category='trading'."""
    exec_rows = [
        {"strategy_version_id": "sv-1", "ts": "2026-06-10T10:00:00+00:00", "fee": 0.42},
        {"strategy_version_id": "sv-1", "ts": "2026-06-11T10:00:00+00:00", "fee": 0.18},
    ]
    store = _FakeStore(exec_rows)
    written = record_trading_fees(store)

    assert written == 1
    assert len(store.costs) == 1
    row = store.costs[0]
    assert row["category"] == "trading"
    assert row["vendor"] == "Exchange"
    assert row["currency"] == "USD"
    assert float(row["amount"]) == pytest.approx(0.42 + 0.18, rel=1e-6)
    assert row["strategy_version_id"] == "sv-1"
    meta = json.loads(row["meta"])
    assert meta["seed"] == "trading_fees"
    assert meta["month"] == "2026-06"


def test_record_trading_fees_writes_separate_rows_per_month():
    """Two different months → two rows."""
    exec_rows = [
        {"strategy_version_id": "sv-1", "ts": "2026-05-15T00:00:00+00:00", "fee": 1.0},
        {"strategy_version_id": "sv-1", "ts": "2026-06-10T00:00:00+00:00", "fee": 2.0},
    ]
    store = _FakeStore(exec_rows)
    written = record_trading_fees(store)

    assert written == 2
    months = {r["meta"] for r in store.costs}
    assert any("2026-05" in m for m in months)
    assert any("2026-06" in m for m in months)


def test_record_trading_fees_is_idempotent():
    """Second call for the same (strategy, month) writes 0 rows."""
    exec_rows = [
        {"strategy_version_id": "sv-1", "ts": "2026-06-10T00:00:00+00:00", "fee": 0.5},
    ]
    store = _FakeStore(exec_rows)
    first = record_trading_fees(store)
    second = record_trading_fees(store)

    assert first == 1
    assert second == 0
    assert len(store.costs) == 1  # no duplicate


def test_record_trading_fees_zero_fee_skipped():
    """Executions with fee=0 do not produce cost rows."""
    exec_rows = [
        {"strategy_version_id": "sv-1", "ts": "2026-06-10T00:00:00+00:00", "fee": 0.0},
    ]
    store = _FakeStore(exec_rows)
    written = record_trading_fees(store)
    assert written == 0
    assert len(store.costs) == 0


def test_record_trading_fees_none_store_returns_zero():
    """None store → graceful 0 (best-effort)."""
    assert record_trading_fees(None) == 0


def test_record_trading_fees_two_strategies_same_month():
    """Two different strategies in the same month → two separate rows."""
    exec_rows = [
        {"strategy_version_id": "sv-1", "ts": "2026-06-10T00:00:00+00:00", "fee": 1.0},
        {"strategy_version_id": "sv-2", "ts": "2026-06-11T00:00:00+00:00", "fee": 2.5},
    ]
    store = _FakeStore(exec_rows)
    written = record_trading_fees(store)
    assert written == 2
    svids = {r["strategy_version_id"] for r in store.costs}
    assert "sv-1" in svids
    assert "sv-2" in svids


# ---------------------------------------------------------------------------
# seed_infra_costs — verify Modal is present and Fly.io is absent
# ---------------------------------------------------------------------------


class _InfraSeedStore:
    """Fake store for seed_infra_costs — always reports no prior seed so we can check the written rows."""

    def __init__(self):
        self.costs: list[dict] = []

    def row(self, sql: str, params: tuple = ()) -> dict | None:
        return None  # always "not yet seeded"

    def insert(self, table: str, row: dict) -> str:
        row_id = str(uuid.uuid4())
        self.costs.append({"id": row_id, **row})
        return row_id


def test_infra_seed_contains_modal():
    """Modal is in the infra seed (was missing; Fly.io was phantom and has been removed)."""
    store = _InfraSeedStore()
    seed_infra_costs(store)
    vendors = {r["vendor"] for r in store.costs}
    assert "Modal" in vendors


def test_infra_seed_does_not_contain_flyio():
    """Fly.io must not appear in the infra seed (was a phantom line — removed)."""
    store = _InfraSeedStore()
    seed_infra_costs(store)
    vendors = {r["vendor"] for r in store.costs}
    assert "Fly.io" not in vendors


def test_infra_seed_modal_has_zero_idle_cost():
    """Modal's amount_min should be 0 (scale-to-zero — $0 idle)."""
    store = _InfraSeedStore()
    seed_infra_costs(store)
    modal_rows = [r for r in store.costs if r["vendor"] == "Modal"]
    assert len(modal_rows) == 1
    meta = json.loads(modal_rows[0]["meta"])
    assert meta["amount_min"] == 0.0
