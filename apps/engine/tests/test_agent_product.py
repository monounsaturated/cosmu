# Guard test for the PRODUCT-aware observe context (symbol × venue): the split between MARKET-WIDE metrics
# (fear_greed, macro — one shared value) and PER-SYMBOL metrics (funding, sentiment — resolved per asset). Proves
# the observe loop reasons on THIS asset's funding, never leaking the symbol-blind summary value onto a symbol
# that has no row, and that the default reason_fn turns divergent per-symbol funding into divergent reads — all
# offline (no LLM, judge=None). See docs/epics/agentic-lane.md.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.mind.analysts import PER_SYMBOL_METRICS, context_for_symbol, gather_context
from cosmu.strategy.agent_author import open_agent_strategy
from cosmu.strategy.agent_executor import default_reason_fn
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/product.sqlite3"))


def _seed_alt(store: Store, rows: list[tuple[str, str, str, float, str]]) -> None:
    # rows: (provider, symbol, metric, value, available_at)
    with store.batch() as b:
        for provider, symbol, metric, value, at in rows:
            b.execute(
                "INSERT INTO alt_data (provider, symbol, metric, ts, available_at, value, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (provider, symbol, metric, at, at, value, at),
            )


def _seed_summary(store: Store, rows: list[tuple[str, str, float, str]]) -> None:
    # rows: (provider, metric, value, available_at) — the symbol-BLIND market-wide rollup
    with store.batch() as b:
        for provider, metric, value, at in rows:
            b.execute(
                "INSERT INTO alt_data_provider_summary (provider, metric, n_rows, latest_available_at, latest_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (provider, metric, 1, at, str(value), at),
            )


def test_funding_is_a_per_symbol_metric_and_fear_greed_is_market_wide():
    # the deliberate split (don't par-symbolise the shared metrics)
    assert "funding_rate" in PER_SYMBOL_METRICS
    assert "social_sentiment" in PER_SYMBOL_METRICS
    assert "fear_greed" not in PER_SYMBOL_METRICS
    assert "macro_regime" not in PER_SYMBOL_METRICS


def test_context_for_symbol_resolves_funding_per_symbol_and_shares_fear_greed(tmp_path):
    store = _store(tmp_path)
    # market-wide summary: a single fear/greed index (shared) AND a symbol-BLIND funding rollup value (99) that
    # must NEVER leak into a per-symbol read.
    _seed_summary(store, [("alternative.me", "fear_greed", 40.0, "2026-06-10T00:00:00+00:00"),
                          ("binance", "funding_rate", 99.0, "2026-06-10T00:00:00+00:00")])
    # per-symbol funding in alt_data: AAA bullish (neg z), BBB bearish (pos z). CCC has NO funding row.
    _seed_alt(store, [("binance", "AAA", "funding_rate", -1.0, "2026-06-11T00:00:00+00:00"),
                      ("binance", "BBB", "funding_rate", 1.0, "2026-06-11T00:00:00+00:00")])

    market_ctx = gather_context(store)
    # the symbol-blind summary carried funding_rate=99 — that is exactly the leak the split must prevent.
    assert market_ctx.values["funding_rate"][0] == 99.0

    ctx_aaa = context_for_symbol(store, market_ctx, "AAA")
    ctx_bbb = context_for_symbol(store, market_ctx, "BBB")
    ctx_ccc = context_for_symbol(store, market_ctx, "CCC")

    # per-symbol funding is THIS asset's value, NOT the symbol-blind 99
    assert ctx_aaa.values["funding_rate"][0] == -1.0
    assert ctx_bbb.values["funding_rate"][0] == 1.0
    # CCC has no funding row → the per-symbol metric is ABSENT (honest abstain), never the leaked 99
    assert "funding_rate" not in ctx_ccc.values
    # fear/greed is market-wide → shared identically across all three products
    assert ctx_aaa.values["fear_greed"] == ctx_bbb.values["fear_greed"] == ctx_ccc.values["fear_greed"]
    assert ctx_aaa.values["fear_greed"][0] == 40.0


def test_default_reason_fn_turns_per_symbol_funding_into_divergent_reads(tmp_path):
    # Only per-symbol funding is seeded (no shared metrics), so the Positioning analyst is the sole vote and the
    # two symbols MUST diverge: AAA (negative funding z → uncrowded → bullish) long, BBB (crowded longs) short.
    store = _store(tmp_path)
    _seed_alt(store, [("binance", "AAA", "funding_rate", -1.0, "2026-06-11T00:00:00+00:00"),
                      ("binance", "BBB", "funding_rate", 1.0, "2026-06-11T00:00:00+00:00")])
    agent = AgentSpec(
        name="a", rationale="r", symbols=["AAA", "BBB"], venues=["binance"],
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03),
    )
    open_agent_strategy(store, agent)
    rf = default_reason_fn(store)  # judge=None → fully offline heuristic panel

    d_aaa = rf(agent, "AAA", "binance")
    d_bbb = rf(agent, "BBB", "binance")
    assert d_aaa is not None and d_aaa.side == "long"
    assert d_bbb is not None and d_bbb.side == "short"
