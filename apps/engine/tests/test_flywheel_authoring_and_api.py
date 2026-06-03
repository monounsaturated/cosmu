# The flywheel wired into the loop: authoring CONSULTS long-term memory (a dead structure is down-weighted, a
# winner pattern is leaned into) — LLM still only proposes, the Gate still disposes. Plus the API contract
# shapes for GET /skills and GET /memory/insights (and the cost-transparency GET /costs the web consumes).

from __future__ import annotations

import math

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.evolution.seeder import seed_meanrev_spec, seed_momentum_spec
from cosmu.evolution.loop import fit_params
from cosmu.knowledge.memory import GraveyardMemory
from cosmu.knowledge.store import Store, utcnow
from cosmu.lab.author import draft_from_brief
from cosmu.strategy.compiler import compile_spec


class _Ev:
    def __init__(self, vid, name, origin, passed, reasons=None, ds=0.6, oos=4.0):  # noqa: ANN001
        self.version_id = vid
        self.name = name
        self.origin = origin
        self.passed = passed
        self.reasons = reasons or []
        self.deflated_sharpe = ds
        self.oos_return_pct = oos


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/fly.sqlite3", openrouter_api_key=None))


def _persist_version(store: Store, spec, *, passed: bool) -> str:  # noqa: ANN001
    params = fit_params(spec)
    compiled = compile_spec(spec, params)
    sid = store.insert("strategies", {"name": spec.name, "thesis": spec.rationale, "origin": "seed", "created_at": utcnow()})
    vid = store.insert(
        "strategy_versions",
        {
            "strategy_id": sid, "parent_id": None, "spec": spec.model_dump(mode="json"),
            "generated_code": compiled.code, "code_hash": compiled.code_hash, "params": params,
            "mutation_operator": None, "mutation_rationale": None, "origin": "seed",
            "status": "forward_test" if passed else "killed", "created_at": utcnow(),
            "killed_at": None if passed else utcnow(), "kill_reason": None if passed else "pbo",
        },
    )
    store.insert(
        "backtests",
        {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.04", "sharpe": "1", "sortino": "1",
            "deflated_sharpe": "0.6", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 40, "pbo": "0.2",
            "trials_counted": 1, "regime_label": "mixed", "folds_positive": 4,
            "passed_gates": 1 if passed else 0, "holdout_passed": 1, "created_at": utcnow(),
        },
    )
    return vid


def test_authoring_downweights_a_dead_structure(tmp_path):
    store = _store(tmp_path)
    mem = GraveyardMemory(store)

    # Plant a DEAD end whose entry structure uses rsi+bb_z (the mean-reversion seed).
    dead = seed_meanrev_spec()
    dead.name = "Oversold RSI/BB fade"
    mem.remember(dead, _Ev("v-dead", dead.name, "seed", passed=False, reasons=["deflated_sharpe", "pbo"]))

    brief = "Fade oversold RSI on crypto when the band z-score is washed out, swing horizon"
    # WITHOUT memory the author picks rsi (+ bb_z); WITH memory those dead features are down-weighted.
    base = draft_from_brief(brief, features=["rsi", "bb_z"], store=None)
    informed = draft_from_brief(brief, features=["rsi", "bb_z"], store=store)

    assert "rsi" in base.features  # baseline proposes the dead structure
    assert informed.memory_avoided, "memory should have flagged a dead structure to avoid"
    assert "rsi" in informed.memory_avoided
    # the informed draft no longer leads with the dead feature
    assert "rsi" not in informed.features or informed.features != base.features
    # and it stays a VALID, compilable proposal (the Gate still disposes downstream)
    assert informed.spec is not None


def test_authoring_leans_toward_a_winner_pattern(tmp_path):
    store = _store(tmp_path)
    mem = GraveyardMemory(store)
    win = seed_momentum_spec()  # uses ret_Nd / adx
    win.name = "Trend momentum ADX"
    mem.remember(win, _Ev("v-win", win.name, "seed", passed=True, reasons=[]))

    informed = draft_from_brief("Trend-confirmed momentum on crypto with ADX confirmation", features=["ret_Nd", "adx"], store=store)
    # winner features survive (they are not down-weighted); memory_leaned may add reinforcing features.
    assert any(f in informed.features for f in ("ret_Nd", "adx"))


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.sqlite3", openrouter_api_key=None)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app), store  # no `with` → lifespan does not run the boot backtest


def test_skills_and_memory_insights_api_shapes(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    mem = GraveyardMemory(store)

    # plant a winner + a dead end so both feeds have content
    win = seed_momentum_spec(); win.name = "Trend momentum ADX"
    dead = seed_meanrev_spec(); dead.name = "Oversold fade"
    mem.remember(win, _Ev("v-win", win.name, "seed", passed=True, reasons=[]))
    mem.remember(dead, _Ev("v-dead", dead.name, "seed", passed=False, reasons=["pbo"]))

    from cosmu.lab.curator import distill_skill, grade_skills

    vid = _persist_version(store, win, passed=True)
    distill_skill(store, win, _Ev(vid, win.name, "seed", passed=True))
    grade_skills(store)

    skills = client.get("/skills").json()
    assert "skills" in skills and skills["skills"]
    s = skills["skills"][0]
    assert set(s.keys()) == {"name", "grade", "success_count", "lineage", "recipe_summary", "created_at"}
    assert isinstance(s["grade"], (int, float)) and isinstance(s["success_count"], int)

    insights = client.get("/memory/insights").json()
    assert "insights" in insights and insights["insights"]
    kinds = {i["kind"] for i in insights["insights"]}
    assert kinds <= {"dead_end", "winner_pattern"}
    for i in insights["insights"]:
        assert set(i.keys()) == {"kind", "text", "ref"}
    assert {"dead_end", "winner_pattern"} <= kinds  # both a death and a win were learned


def test_costs_api_shape(tmp_path, monkeypatch):
    client, _store = _client(tmp_path, monkeypatch)
    body = client.get("/costs").json()
    # Core cost fields always present
    assert {"total_usd", "by_category", "opex_vs_alpha", "per_strategy"}.issubset(body.keys())
    # Extended cost/ROI fields added in W1.5
    assert "infra_lines" in body, "infra_lines should be present (static §9 seed)"
    assert "llm_calls" in body, "llm_calls summary should be present"
    assert isinstance(body["by_category"], list)
    assert isinstance(body["per_strategy"], list)
    assert isinstance(body["infra_lines"], list)
    # Static infra seed should have populated lines
    assert len(body["infra_lines"]) > 0, "infra_lines should be seeded on first GET /costs"
    first_line = body["infra_lines"][0]
    assert {"vendor", "category", "amount", "amount_min", "amount_max", "note"}.issubset(first_line.keys())
    # LLM calls summary shape
    llm = body["llm_calls"]
    assert {"call_count", "total_cost", "by_task"}.issubset(llm.keys())
    assert isinstance(llm["call_count"], int)
    assert isinstance(llm["total_cost"], float)


def _persist_version_no_backtest(store: Store, spec, *, name: str) -> str:  # noqa: ANN001
    """A Version that has NEVER been backtested — the LEFT JOIN in /leaderboard
    yields NULL for every metric column. This is the exact shape that crashed
    the web build (`undefined.toFixed()`) before the engine coerced its output."""
    params = fit_params(spec)
    compiled = compile_spec(spec, params)
    sid = store.insert("strategies", {"name": name, "thesis": spec.rationale, "origin": "seed", "created_at": utcnow()})
    return store.insert(
        "strategy_versions",
        {
            "strategy_id": sid, "parent_id": None, "spec": spec.model_dump(mode="json"),
            "generated_code": compiled.code, "code_hash": compiled.code_hash, "params": params,
            "mutation_operator": None, "mutation_rationale": None, "origin": "seed",
            "status": "screening", "created_at": utcnow(),
            "killed_at": None, "kill_reason": None,
        },
    )


def test_leaderboard_never_emits_null_metrics_without_a_backtest(tmp_path, monkeypatch):
    # Contract coherence: LeaderboardRow promises non-null `number` for every metric.
    # A Version with no backtest (LEFT JOIN -> NULLs) must still serialize as real
    # numbers, NOT null — otherwise the typed web build crashes on `x.toFixed()`.
    client, store = _client(tmp_path, monkeypatch)

    spec = seed_momentum_spec(); spec.name = "Never-backtested momentum"
    _persist_version_no_backtest(store, spec, name=spec.name)

    body = client.get("/leaderboard").json()
    assert body["rows"], "the never-backtested Version should still appear on the board"

    numeric_fields = ("track_return_pct", "deflated_sharpe", "net_pct", "pbo")
    for row in body["rows"]:
        for field in numeric_fields:
            assert row[field] is not None, f"{field} is null — contract promises a number"
            assert isinstance(row[field], (int, float)), f"{field} is not numeric: {row[field]!r}"
            assert math.isfinite(row[field]), f"{field} is non-finite: {row[field]!r}"


def test_leaderboard_surfaces_advisory_maturity_signal(tmp_path, monkeypatch):
    # ADVISORY ONLY: the leaderboard exposes forward_age_days + live_ready per track, computed from the track's
    # FIRST `track_opened` event (its forward-test clock origin). A matured + net-positive track is recommended;
    # this NEVER gates — it's surfaced for the operator. Mirrors what feeds the web /forward-test page.
    from datetime import UTC, datetime, timedelta

    client, store = _client(tmp_path, monkeypatch)

    spec = seed_momentum_spec(); spec.name = "Matured momentum"
    vid = _persist_version(store, spec, passed=True)
    # The clock origin: a track_opened event 40 days ago (> FORWARD_TEST_MIN_DAYS). oos_return 0.04 -> net_pct > 0.
    store.append_event(
        actor="master", kind="track_opened", ref_type="strategy_version", ref_id=vid,
        payload={"proven_regimes": ["bull"]},
    )
    old_ts = (datetime.now(tz=UTC) - timedelta(days=40)).isoformat()
    with store.batch() as writer:
        writer.execute("UPDATE events SET ts = ? WHERE kind = 'track_opened' AND ref_id = ?", (old_ts, vid))

    rows = client.get("/leaderboard").json()["rows"]
    row = next(r for r in rows if r["version_id"] == vid)
    assert "forward_age_days" in row and "live_ready" in row, "advisory maturity fields must be on the contract"
    assert row["forward_age_days"] >= 30.0
    assert row["live_ready"] is True  # matured AND net-positive -> recommended (advisory)


def test_leaderboard_live_ready_false_without_a_funded_clock(tmp_path, monkeypatch):
    # No track_opened event => forward-test clock never started => age 0 => never live_ready, regardless of P&L.
    # Fail-safe: an unfunded/un-marked track is never recommended.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Unfunded momentum"
    vid = _persist_version(store, spec, passed=True)

    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["forward_age_days"] == 0.0
    assert row["live_ready"] is False


def test_leaderboard_metric_coercion_handles_nan_and_none():
    # Unit-level guard on the coercion helper itself: NULL, NaN, inf and junk all
    # collapse to the documented 0.0 sentinel (plain `x or 0` would let NaN through).
    from cosmu.api.app import _metric

    assert _metric(None) == 0.0
    assert _metric(float("nan")) == 0.0
    assert _metric(float("inf")) == 0.0
    assert _metric("not-a-number") == 0.0
    assert _metric("0.04") == 0.04  # sqlite stores some metrics as REAL-as-text
    assert _metric(1.5) == 1.5
    assert _metric(0.0) == 0.0
