# The flywheel wired into the loop: authoring CONSULTS long-term memory (a dead structure is down-weighted, a
# winner pattern is leaned into) — LLM still only proposes, the Gate still disposes. Plus the API contract
# shapes for GET /skills and GET /memory/insights (and the cost-transparency GET /costs the web consumes).

from __future__ import annotations

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
    assert set(body.keys()) == {"total_usd", "by_category", "opex_vs_alpha", "per_strategy"}
    assert isinstance(body["by_category"], list)
    assert isinstance(body["per_strategy"], list)
