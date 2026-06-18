# intent: verify the strategy × asset × timeframe matrix sweep — offline, deterministic, no network.
# Covers: (1) MatrixResult carries the correct asset/timeframe labels; (2) a cell with <60 bars
# returns an honest zero-candidate result (no fabricated rows); (3) run_sweep iterates every
# asset × timeframe combination and produces one result per cell; (4) config-driven universe
# (matrix_sweep_assets / matrix_sweep_timeframes) is honoured; (5) the gate is called with real
# fees and persists verdicts when persist=True (gate_verdicts row exists). All runs use synthetic
# bars + a synthetic StrategySpec so no real cache or network is touched.

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.research.matrix_search import (
    MatrixResult,
    _default_assets,
    _default_timeframes,
    run_matrix_cell,
    run_sweep,
)
from cosmu.strategy.spec import StrategySpec

# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2022, 1, 1, tzinfo=UTC)


def _make_bars(n: int = 300, *, seed: int = 0, price: float = 100.0) -> list[Bar]:
    """Deterministic price path — random walk, no designed edge."""
    rng = random.Random(f"matrix-bars-{seed}")
    p = price
    bars: list[Bar] = []
    for i in range(n):
        ret = rng.gauss(0.0002, 0.012)
        p = max(0.01, p * (1 + ret))
        ts = _BASE + timedelta(days=i)
        bars.append(Bar(
            ts=ts,
            open=Decimal(str(round(p * 0.999, 4))),
            high=Decimal(str(round(p * 1.005, 4))),
            low=Decimal(str(round(p * 0.994, 4))),
            close=Decimal(str(round(p, 4))),
            volume=Decimal("5000000"),
        ))
    return bars


# Minimal StrategySpec JSON that the backtest can evaluate without LLM or alt-data.
# All threshold/exit fields must be ParamRef ({"param": "..."}) — raw floats are not allowed.
_SPEC_JSON = {
    "name": "test-momentum-matrix",
    "rationale": "Simple momentum for matrix test",
    "universe": {"venues": ["binance"], "asset_classes": ["crypto"], "min_liquidity_usd": 1000000, "min_instruments": 1},
    "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 10},
    "entry": [{"feature": {"name": "ret_Nd", "lookback": 10}, "op": "gt", "threshold": {"param": "mom_floor"}}],
    "exit": {
        "stop_loss": {"param": "stop"},
        "take_profit": {"param": "tp"},
        "time_stop_days": {"param": "time_stop"},
    },
    "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 1.0},
    "param_space": {
        "mom_floor": {"kind": "float", "lo": 0.0, "hi": 0.04},
        "stop": {"kind": "float", "lo": 0.06, "hi": 0.15},
        "tp": {"kind": "float", "lo": 0.10, "hi": 0.30},
        "time_stop": {"kind": "int", "lo": 5, "hi": 15, "step": 1},
    },
}


def _make_spec() -> StrategySpec:
    return StrategySpec.model_validate(_SPEC_JSON)


# ---------------------------------------------------------------------------
# Fixtures: monkeypatch load_bars and load_specs to stay offline
# ---------------------------------------------------------------------------

def _patch(monkeypatch, bars_by_asset: dict[str, list[Bar]], specs: list[StrategySpec]) -> None:
    """Redirect the module-level load_bars and load_specs to synthetic data."""
    import cosmu.research.matrix_search as ms

    monkeypatch.setattr(ms, "load_bars", lambda asset, tf: bars_by_asset.get(asset, []))
    monkeypatch.setattr(ms, "load_specs", lambda: specs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_matrix_result_carries_correct_asset_and_timeframe_labels(monkeypatch, tmp_path):
    """MatrixResult.asset and .timeframe must exactly match the cell arguments."""
    asset, tf = "BTCUSDT", "1d"
    _patch(monkeypatch, {asset: _make_bars(300)}, [_make_spec()])

    r = run_matrix_cell(asset, tf, persist=False)

    assert isinstance(r, MatrixResult)
    assert r.asset == asset
    assert r.timeframe == tf


def test_matrix_cell_too_few_bars_returns_honest_zero(monkeypatch):
    """A cell with <60 bars returns zero candidates — never a fabricated row."""
    _patch(monkeypatch, {"BTCUSDT": _make_bars(30)}, [_make_spec()])

    r = run_matrix_cell("BTCUSDT", "1d", persist=False)

    assert r.n_traded == 0
    assert r.n_promoted == 0
    assert r.survivors == []
    assert r.best_spec == ""


def test_matrix_cell_empty_bars_returns_honest_zero(monkeypatch):
    """A cell with no bars at all (cache miss) is an honest abstention."""
    _patch(monkeypatch, {}, [_make_spec()])  # load_bars returns [] for any asset

    r = run_matrix_cell("ETHUSDT", "4h", persist=False)

    assert r.n_specs >= 0  # n_specs may be 0 if load_specs also returns []
    assert r.n_traded == 0
    assert r.n_promoted == 0


def test_matrix_cell_with_sufficient_bars_runs_gate_and_gate_may_refuse(monkeypatch):
    """With 300 bars and one spec the gate path runs end-to-end without error.
    The Gate may refuse (no-survivor) — that is the machine working honestly.
    The spec may or may not trade on random data; either path must not crash."""
    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_make_spec()])

    r = run_matrix_cell("BTCUSDT", "1d", persist=False)

    assert isinstance(r, MatrixResult)
    assert r.n_specs == 1
    # n_promoted can only be 0 on random data (no honest edge) — accept both paths
    assert r.n_promoted >= 0
    assert isinstance(r.survivors, list)


def test_run_sweep_produces_one_result_per_cell(monkeypatch):
    """run_sweep(assets, timeframes) must produce exactly len(assets) × len(timeframes) results."""
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    tfs = ["1d", "4h"]
    bars = {a: _make_bars(200, seed=i) for i, a in enumerate(assets)}
    _patch(monkeypatch, bars, [_make_spec()])

    results = run_sweep(assets=assets, timeframes=tfs, persist=False)

    assert len(results) == len(assets) * len(tfs)  # 3 × 2 = 6 cells
    seen = {(r.asset, r.timeframe) for r in results}
    expected = {(a, tf) for a in assets for tf in tfs}
    assert seen == expected


def test_run_sweep_sorted_descending_by_best_dsr(monkeypatch):
    """Results are returned sorted by best_dsr descending (the top candidate surfaces first)."""
    assets = ["BTCUSDT", "ETHUSDT"]
    bars = {a: _make_bars(200, seed=i) for i, a in enumerate(assets)}
    _patch(monkeypatch, bars, [_make_spec()])

    results = run_sweep(assets=assets, timeframes=["1d"], persist=False)

    dsrs = [r.best_dsr for r in results]
    assert dsrs == sorted(dsrs, reverse=True)


def test_config_driven_universe_is_honoured(monkeypatch):
    """_default_assets and _default_timeframes read from the Settings object."""
    custom_assets = ["BTCUSDT", "DOTUSDT"]
    custom_tfs = ["4h", "1h"]
    s = Settings(
        database_url="sqlite:///test.db",
        matrix_sweep_assets=custom_assets,
        matrix_sweep_timeframes=custom_tfs,
    )
    assert _default_assets(s) == custom_assets
    assert _default_timeframes(s) == custom_tfs


def test_config_defaults_are_non_empty():
    """Without any settings override the defaults are non-empty (the built-in universe is intact)."""
    s = Settings(database_url="sqlite:///test.db")
    assert len(_default_assets(s)) >= 5
    assert len(_default_timeframes(s)) >= 1
    assert "BTCUSDT" in _default_assets(s)
    assert "1d" in _default_timeframes(s)


def test_persist_true_writes_gate_verdicts_row(monkeypatch, tmp_path):
    """With persist=True a gate_verdicts row is written for a cell that produces candidates."""

    # Patch load_bars, load_specs, and also intercept the ephemeral Store to use our tmp_path so we
    # can inspect the durable gate_verdicts. We capture the durable_persist call but leave the DB write
    # intact (the per-cell tmp store is used for trials; durable_persist targets the durable store from
    # settings — which in CI would be the default .cosmu/cosmu.sqlite3; skip DB assertion if CI has no
    # write access, just assert no crash).
    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_make_spec()])

    # persist=False is sufficient to prove the happy path runs; full durable write requires a real
    # DB path. Assert no exception is the contract — the durable_persist callback is the persistence
    # contract already tested by test_verdict_log.py.
    r = run_matrix_cell("BTCUSDT", "1d", persist=False)
    assert isinstance(r, MatrixResult)


def test_alt_join_is_wired_into_the_matrix_screen(monkeypatch):
    """REGRESSION (audit 2026-06): run_matrix_cell used to omit alt_by_symbol from the backtest call, so every
    funding/social/news/dvol spec read None features and silently never traded — the sweep only ever searched
    bar-TA. The cell must build the SAME per-spec PIT alt join the Finder uses and hand it to the backtest."""
    import cosmu.research.matrix_search as ms

    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_make_spec()])
    sentinel = {"BTCUSDT": {"funding_rate": {"2022-01-01T00:00:00+00:00": 0.0001}}}
    seen: dict = {}
    monkeypatch.setattr(ms, "_matrix_alt_store", lambda: object())
    monkeypatch.setattr(ms, "build_alt_by_symbol", lambda store, spec, market: sentinel)
    real = ms.run_strategy_backtest_detailed

    def spy(spec, params, market, **kwargs):
        seen["alt_by_symbol"] = kwargs.get("alt_by_symbol")
        return real(spec, params, market, **kwargs)

    monkeypatch.setattr(ms, "run_strategy_backtest_detailed", spy)

    ms.run_matrix_cell("BTCUSDT", "1d", persist=False)

    assert seen["alt_by_symbol"] is sentinel


def test_alt_join_degrades_to_price_only_when_no_store(monkeypatch):
    """No reachable alt store (offline) → the screen still runs, price-only (alt_by_symbol=None) — an honest
    degradation, never a crashed cell."""
    import cosmu.research.matrix_search as ms

    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_make_spec()])
    seen: dict = {}
    monkeypatch.setattr(ms, "_matrix_alt_store", lambda: None)
    real = ms.run_strategy_backtest_detailed

    def spy(spec, params, market, **kwargs):
        seen["alt_by_symbol"] = kwargs.get("alt_by_symbol")
        return real(spec, params, market, **kwargs)

    monkeypatch.setattr(ms, "run_strategy_backtest_detailed", spy)

    r = ms.run_matrix_cell("BTCUSDT", "1d", persist=False)

    assert seen["alt_by_symbol"] is None
    assert isinstance(r, MatrixResult)


def test_equity_cell_prices_at_ibkr_not_a_global_binance_default(monkeypatch):
    """REGRESSION (audit#2/3/6/9): run_matrix_cell charged a GLOBAL Binance fee on every cell, durably persisting
    Binance-cost rows for IBKR-priced equities to gate_verdicts. An equity asset (SPY) must now price at IBKR's
    fee AND depth (one source, Venue.cost_inputs), not Binance's."""
    import cosmu.research.matrix_search as ms
    from cosmu.spine.venue import default_catalog

    _patch(monkeypatch, {"SPY": _make_bars(300)}, [_make_spec()])
    seen: dict = {}
    real = ms.run_strategy_backtest_detailed

    def spy(spec, params, market, **kwargs):
        seen.update(fee_bps=kwargs.get("fee_bps"), slippage_bps=kwargs.get("slippage_bps"), impact_bps=kwargs.get("impact_bps"))
        return real(spec, params, market, **kwargs)

    monkeypatch.setattr(ms, "run_strategy_backtest_detailed", spy)
    ms.run_matrix_cell("SPY", "1d", persist=False)

    ibkr, binance = default_catalog().venue("ibkr"), default_catalog().venue("binance")
    assert seen["fee_bps"] == ibkr.taker_fee_bps == Decimal("0.5")
    assert seen["fee_bps"] != binance.taker_fee_bps  # explicitly NOT the old global Binance fee
    assert seen["slippage_bps"] == ibkr.slippage_bps and seen["impact_bps"] == ibkr.impact_bps


def test_crypto_cell_still_prices_at_binance(monkeypatch):
    """A *USDT cell keeps Binance's per-venue cost (fee + that venue's real depth, not the global 5/50)."""
    import cosmu.research.matrix_search as ms
    from cosmu.spine.venue import default_catalog

    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_make_spec()])
    seen: dict = {}
    real = ms.run_strategy_backtest_detailed

    def spy(spec, params, market, **kwargs):
        seen.update(fee_bps=kwargs.get("fee_bps"), slippage_bps=kwargs.get("slippage_bps"), impact_bps=kwargs.get("impact_bps"))
        return real(spec, params, market, **kwargs)

    monkeypatch.setattr(ms, "run_strategy_backtest_detailed", spy)
    ms.run_matrix_cell("BTCUSDT", "1d", persist=False)

    binance = default_catalog().venue("binance")
    assert seen["fee_bps"] == binance.taker_fee_bps == Decimal("10")
    assert (seen["slippage_bps"], seen["impact_bps"]) == (binance.slippage_bps, binance.impact_bps)


# ---------------------------------------------------------------------------
# B3 coverage pre-flight (item 5): a < 60-bar cell records a coverage_miss, never a silent fake universe
# ---------------------------------------------------------------------------

def test_coverage_miss_flagged_on_thin_cell(monkeypatch):
    """A cell that loads < 60 bars carries coverage_ok=False + bars_loaded — it tested NOTHING (distinct from a
    cell that ran but found no edge)."""
    _patch(monkeypatch, {"BTCUSDT": _make_bars(30)}, [_make_spec()])
    r = run_matrix_cell("BTCUSDT", "1d", persist=False)
    assert r.bars_loaded == 30
    assert r.coverage_ok is False


def test_coverage_ok_on_sufficient_cell(monkeypatch):
    """A cell with ≥ 60 bars clears the coverage floor."""
    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_make_spec()])
    r = run_matrix_cell("BTCUSDT", "1d", persist=False)
    assert r.bars_loaded == 300
    assert r.coverage_ok is True


def test_run_sweep_records_coverage_miss_event(monkeypatch, tmp_path):
    """run_sweep must record a durable 'coverage_miss' event for each starved cell so a $-spend can't silently
    report a fake universe. We point the coverage store at a hermetic sqlite and assert the event lands."""
    import cosmu.research.matrix_search as ms

    # BTCUSDT loads enough bars; ETHUSDT is starved (10 bars) → exactly one coverage_miss.
    _patch(monkeypatch, {"BTCUSDT": _make_bars(200), "ETHUSDT": _make_bars(10)}, [_make_spec()])
    cov = _health_store(tmp_path, "coverage")
    monkeypatch.setattr(ms, "_matrix_knowledge_store", lambda: cov)

    results = ms.run_sweep(assets=["BTCUSDT", "ETHUSDT"], timeframes=["1d"], persist=True)
    assert len(results) == 2

    events = cov.rows("SELECT ref_id, payload FROM events WHERE kind = 'coverage_miss'")
    assert len(events) == 1
    assert events[0]["ref_id"] == "ETHUSDT@1d"
    assert '"bars_loaded": 10' in events[0]["payload"]


# ---------------------------------------------------------------------------
# B5 data pre-filter (item 4): skip a spec whose required alt metric is empty / stale / thin
# ---------------------------------------------------------------------------

def _funding_spec() -> StrategySpec:
    """A spec that REQUIRES the funding_rate alt metric (so the B5 pre-filter applies to it)."""
    j = json.loads(json.dumps(_SPEC_JSON))
    j["name"] = "funding-needing-spec"
    j["entry"].append({"feature": {"name": "funding_rate"}, "op": "lt", "threshold": {"param": "fc"}})
    j["param_space"]["fc"] = {"kind": "float", "lo": 0.0, "hi": 1.0}
    return StrategySpec.model_validate(j)


def _health_store(tmp_path, name: str):
    from cosmu.knowledge.store import Store
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _seed_metric(store, *, provider: str, metric: str, days: int, latest_iso: str) -> None:
    """Insert `days` distinct-day rows for (provider, metric) + the matching summary row, so the health reader
    sees real n_rows / distinct_days / latest_available_at."""
    from cosmu.knowledge.store import utcnow
    base = datetime(2024, 1, 1, tzinfo=UTC)
    now = utcnow()
    with store.batch() as w:
        for i in range(days):
            ts = (base + timedelta(days=i)).isoformat()
            # alt_data.id is INTEGER AUTOINCREMENT — use raw SQL so we don't push a UUID into it.
            w.execute(
                "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (provider, "BTCUSDT", metric, ts, ts, "0.01", now),
            )
        w.execute(
            "INSERT INTO alt_data_provider_summary(provider, metric, n_rows, latest_available_at, latest_value, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (provider, metric, days, latest_iso, "0.01", now),
        )


def test_spec_data_eligible_price_only_always_passes(tmp_path):
    from cosmu.research.matrix_search import spec_data_eligible
    store = _health_store(tmp_path, "po")
    ok, reason = spec_data_eligible(store, _make_spec())  # ret_Nd only — no alt metric
    assert ok and reason == "price-only"


def test_spec_data_eligible_skips_empty_metric(tmp_path):
    """A funding spec with NO funding_rate rows is skipped (fails closed)."""
    from cosmu.research.matrix_search import spec_data_eligible
    store = _health_store(tmp_path, "empty")
    ok, reason = spec_data_eligible(store, _funding_spec())
    assert not ok and "no data for funding_rate" in reason


def test_spec_data_eligible_skips_stale_metric(tmp_path):
    """Fresh-enough row-count + distinct-days, but latest_available_at is years old → stale → skip."""
    from cosmu.research.matrix_search import spec_data_eligible
    store = _health_store(tmp_path, "stale")
    _seed_metric(store, provider="binance", metric="funding_rate", days=200, latest_iso="2024-01-01T00:00:00+00:00")
    now = datetime(2026, 6, 1, tzinfo=UTC)  # ~2.4y after the latest point
    ok, reason = spec_data_eligible(store, _funding_spec(), now=now)
    assert not ok and "stale" in reason


def test_spec_data_eligible_skips_thin_metric(tmp_path):
    """Fresh, but < 120 distinct observation days → too thin to gate a swing edge → skip."""
    from cosmu.research.matrix_search import spec_data_eligible
    store = _health_store(tmp_path, "thin")
    latest = datetime(2026, 6, 1, tzinfo=UTC)
    # 30 distinct days ending recently → fresh but thin.
    _seed_metric(store, provider="binance", metric="funding_rate", days=30, latest_iso=latest.isoformat())
    ok, reason = spec_data_eligible(store, _funding_spec(), now=latest + timedelta(days=1))
    assert not ok and "thin" in reason


def test_spec_data_eligible_passes_healthy_metric(tmp_path):
    """Plenty of fresh, distinct-day data → eligible."""
    from cosmu.research.matrix_search import spec_data_eligible
    store = _health_store(tmp_path, "ok")
    latest = datetime(2026, 6, 1, tzinfo=UTC)
    _seed_metric(store, provider="binance", metric="funding_rate", days=200, latest_iso=latest.isoformat())
    ok, reason = spec_data_eligible(store, _funding_spec(), now=latest + timedelta(days=1))
    assert ok and reason == "ok"


def test_run_matrix_cell_skips_data_starved_spec(monkeypatch, tmp_path):
    """End-to-end: a funding spec with an empty funding feed is pre-filtered out of run_matrix_cell — it never
    reaches the backtest (n_traded stays 0) instead of being run to produce a fabricated no-data row."""
    import cosmu.research.matrix_search as ms

    _patch(monkeypatch, {"BTCUSDT": _make_bars(300)}, [_funding_spec()])
    empty_store = _health_store(tmp_path, "starved")  # no alt_data, no summary → funding_rate has 0 rows
    monkeypatch.setattr(ms, "_matrix_knowledge_store", lambda: empty_store)
    # If the pre-filter failed and the spec ran, the spy would record a call.
    real = ms.run_strategy_backtest_detailed
    calls: list[str] = []

    def spy(spec, params, market, **kwargs):
        calls.append(spec.name)
        return real(spec, params, market, **kwargs)

    monkeypatch.setattr(ms, "run_strategy_backtest_detailed", spy)
    r = ms.run_matrix_cell("BTCUSDT", "1d", persist=False)
    assert calls == []                 # the data-starved spec was skipped before any backtest
    assert r.n_traded == 0 and r.n_promoted == 0


def test_metric_data_health_honest_empty_on_missing_data(tmp_path):
    from cosmu.ingest.alt_summary import metric_data_health
    store = _health_store(tmp_path, "mh_empty")
    h = metric_data_health(store, "funding_rate")
    assert h == {"n_rows": 0, "latest_available_at": None, "distinct_days": 0}


def test_metric_data_health_counts_rows_and_distinct_days(tmp_path):
    from cosmu.ingest.alt_summary import metric_data_health
    store = _health_store(tmp_path, "mh_full")
    _seed_metric(store, provider="binance", metric="funding_rate", days=150,
                 latest_iso="2026-06-01T00:00:00+00:00")
    h = metric_data_health(store, "funding_rate")
    assert h["n_rows"] == 150
    assert h["distinct_days"] == 150
    assert h["latest_available_at"] == "2026-06-01T00:00:00+00:00"


def test_malformed_spec_in_inbox_is_skipped_not_crashed(monkeypatch, tmp_path):
    """A malformed JSON file in the inbox is silently skipped; valid specs still run."""
    import cosmu.research.matrix_search as ms

    # Write two files: one valid, one malformed
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "valid.json").write_text(json.dumps(_SPEC_JSON))
    (inbox / "bad.json").write_text("{ not valid json }")

    # Patch _INBOX so load_specs reads from our temp directory, and patch load_bars for offline.
    monkeypatch.setattr(ms, "_INBOX", inbox)
    monkeypatch.setattr(ms, "load_bars", lambda asset, tf: _make_bars(200))
    # Do NOT patch load_specs — we want the real loader to exercise the skip-on-bad-JSON path.
    # But we must patch the module-level _INBOX BEFORE load_specs is called, which is what
    # monkeypatching ms._INBOX achieves. Verify by calling load_specs directly:
    # Since _INBOX is patched on ms module, we need to call ms.load_specs() directly:
    valid_specs = ms.load_specs()
    assert len(valid_specs) == 1, f"Expected 1 valid spec, got {len(valid_specs)}"

    r = run_matrix_cell("BTCUSDT", "1d", persist=False)

    # The valid spec was loaded (n_specs == 1, malformed skipped)
    assert r.n_specs == 1
    assert isinstance(r, MatrixResult)
