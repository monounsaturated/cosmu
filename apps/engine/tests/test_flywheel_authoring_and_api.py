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
            "status": "paper" if passed else "killed", "created_at": utcnow(),
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
    # ADVISORY ONLY: the leaderboard exposes paper_age_days + live_ready per track, computed from the track's
    # FIRST `track_opened` event (its paper clock origin). A matured + net-positive track is recommended;
    # this NEVER gates — it's surfaced for the operator. Mirrors what feeds the web /paper page.
    from datetime import UTC, datetime, timedelta

    client, store = _client(tmp_path, monkeypatch)

    spec = seed_momentum_spec(); spec.name = "Matured momentum"
    vid = _persist_version(store, spec, passed=True)
    # The clock origin: a track_opened event 40 days ago (> PAPER_MIN_DAYS). oos_return 0.04 -> net_pct > 0.
    store.append_event(
        actor="master", kind="track_opened", ref_type="strategy_version", ref_id=vid,
        payload={"proven_regimes": ["bull"]},
    )
    old_ts = (datetime.now(tz=UTC) - timedelta(days=40)).isoformat()
    with store.batch() as writer:
        writer.execute("UPDATE events SET ts = ? WHERE kind = 'track_opened' AND ref_id = ?", (old_ts, vid))

    rows = client.get("/leaderboard").json()["rows"]
    row = next(r for r in rows if r["version_id"] == vid)
    assert "paper_age_days" in row and "live_ready" in row, "advisory maturity fields must be on the contract"
    assert row["paper_age_days"] >= 30.0
    assert row["live_ready"] is True  # matured AND net-positive -> recommended (advisory)


def test_leaderboard_live_ready_false_without_a_funded_clock(tmp_path, monkeypatch):
    # No track_opened event => paper clock never started => age 0 => never live_ready, regardless of P&L.
    # Fail-safe: an unfunded/un-marked track is never recommended.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Unfunded momentum"
    vid = _persist_version(store, spec, passed=True)

    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["paper_age_days"] == 0.0
    assert row["live_ready"] is False


def _open_seeded_track(store: Store, vid: str) -> None:
    """Open a track the way the funder does: seed tracks.return_pct/equity with the BACKTEST number (oos 0.04 ->
    +4%) at funding time. NO marked snapshot yet => this is the day-0 state where the rosy backtest must NOT leak
    into paper_return_pct."""
    store.insert(
        "tracks",
        {
            "strategy_version_id": vid, "starting_capital": "100000", "equity": "104000.00",
            "return_pct": "4.00", "updated_at": utcnow(),
        },
    )


def _add_paper_fill(store: Store, vid: str) -> None:
    """Record ONE real paper fill in the executions log — what makes a version 'has started trading on paper'.
    The leaderboard now gates the marked money columns on this (the same signal the detail sheet's blotter
    reads), so a track must have genuinely traded — not merely been marked — for value/pnl to surface."""
    rid = store.insert(
        "runs",
        {"strategy_version_id": vid, "mode": "paper", "venue_id": "ibkr", "seed": 1, "started_at": utcnow(), "status": "completed"},
    )
    store.insert(
        "executions",
        {"run_id": rid, "strategy_version_id": vid, "instrument_id": "spy-ibkr", "venue_id": "ibkr", "side": "buy",
         "qty": "25", "price": "400", "fee": "0", "slippage": "0", "order_type": "market", "is_paper": 1,
         "ts": utcnow(), "fill_log": "{}"},
    )


def test_leaderboard_forward_return_is_null_without_a_track(tmp_path, monkeypatch):
    # No track row at all => no forward trajectory => paper_return_pct is honest null (not 0, not the backtest).
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "No-track momentum"
    vid = _persist_version(store, spec, passed=True)
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["paper_return_pct"] is None
    # the BACKTEST OOS is still surfaced (relabeled), distinct from the (absent) forward number
    assert math.isclose(row["track_return_pct"], 4.0, abs_tol=1e-6)


def test_leaderboard_forward_return_null_at_day0_never_the_backtest(tmp_path, monkeypatch):
    # The track is OPENED with the backtest number seeded into tracks.return_pct, but it has NOT been marked yet
    # (no scope='track' portfolio_snapshot). paper_return_pct MUST be null — the rosy +4% backtest can NEVER
    # leak in as a day-0 forward result.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Just-funded momentum"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["paper_return_pct"] is None, "day-0 forward must be null, never the seeded backtest number"


def test_leaderboard_forward_return_is_the_marked_trajectory(tmp_path, monkeypatch):
    # Once the mark clock writes a scope='track' snapshot, paper_return_pct is the REAL net-of-fee return:
    # (marked_equity / starting_capital - 1) * 100. A marked equity of 101_500 on 100k => +1.50% forward —
    # the marked number, NOT the +4% backtest.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Marked-up momentum"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)
    _add_paper_fill(store, vid)  # the track has genuinely traded on paper → marked money is surfaced
    store.insert(
        "portfolio_snapshots",
        {
            "scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "101500.00", "cash": "0",
            "positions_value": "101500.00", "pnl": "1500.00", "drawdown": "0",
        },
    )
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert math.isclose(row["paper_return_pct"], 1.5, abs_tol=1e-6)
    # backtest OOS stays distinct at +4%
    assert math.isclose(row["track_return_pct"], 4.0, abs_tol=1e-6)


def test_leaderboard_dedups_a_version_with_multiple_backtests(tmp_path, monkeypatch):
    # A Version with >1 backtest fans out the LEFT JOIN — the leaderboard must still show it ONCE (the
    # strongest backtest, since rows are ordered by deflated_sharpe DESC), not duplicate it / inflate counts.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Two-backtest version"
    vid = _persist_version(store, spec, passed=True)  # seeds backtest #1 (deflated_sharpe 0.6)
    store.insert(
        "backtests",
        {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.03", "sharpe": "1", "sortino": "1",
            "deflated_sharpe": "0.4", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.3",
            "trials_counted": 1, "regime_label": "mixed", "folds_positive": 3,
            "passed_gates": 1, "holdout_passed": 1, "created_at": utcnow(),
        },
    )
    rows = client.get("/leaderboard").json()["rows"]
    matches = [r for r in rows if r["version_id"] == vid]
    assert len(matches) == 1, "a multi-backtest Version must appear exactly once"


def test_leaderboard_v18_money_columns_null_at_day0(tmp_path, monkeypatch):
    # v18 adds value_usd / pnl_usd / pnl_pct. At day-0 (track opened, NOT marked) all three must be null —
    # an un-marked track shows "—", never a fabricated $0 / -100% / the seeded backtest equity.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Day-0 money cols"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)  # opened with backtest-seeded equity, but no scope='track' snapshot yet
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["value_usd"] is None and row["pnl_usd"] is None and row["pnl_pct"] is None


def test_leaderboard_v18_money_columns_from_marked_trajectory(tmp_path, monkeypatch):
    # Once marked, value_usd = marked equity, pnl_usd = value - starting_capital, and pnl_pct ALIASES the
    # forward paper_return_pct (so $ and % can never disagree). Marked 101_500 on 100k => $101,500 / +$1,500 / +1.5%.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Marked money cols"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)
    _add_paper_fill(store, vid)  # has traded on paper → marked money is surfaced
    store.insert(
        "portfolio_snapshots",
        {
            "scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "101500.00", "cash": "0",
            "positions_value": "101500.00", "pnl": "1500.00", "drawdown": "0",
        },
    )
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert math.isclose(row["value_usd"], 101500.0, abs_tol=1e-6)
    assert math.isclose(row["pnl_usd"], 1500.0, abs_tol=1e-6)
    assert math.isclose(row["pnl_pct"], row["paper_return_pct"], abs_tol=1e-9)  # pnl_pct is an alias, never recomputed
    # oos_window_days is a positive number or honest null — never negative/zero/NaN.
    assert row["oos_window_days"] is None or row["oos_window_days"] > 0


def test_leaderboard_marked_without_a_fill_is_honest_dash(tmp_path, monkeypatch):
    # HONESTY: a track that has a marked scope='track' snapshot but has NEVER recorded a real paper fill
    # (the documented-arm case: apply_fill writes positions, never executions) must read has_paper_fills=False
    # and surface NO marked money — value_usd/pnl_usd/pnl_pct/paper_return_pct all null — so the aggregate
    # tells the SAME story as the strategy's own sheet ("no fills yet"), never a fabricated value.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Marked but unfilled"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)
    store.insert(
        "portfolio_snapshots",
        {
            "scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "101500.00", "cash": "0",
            "positions_value": "101500.00", "pnl": "1500.00", "drawdown": "0",
        },
    )  # marked, but NO _add_paper_fill — the track never traded on paper
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["has_paper_fills"] is False
    assert row["value_usd"] is None and row["pnl_usd"] is None
    assert row["pnl_pct"] is None and row["paper_return_pct"] is None


def test_leaderboard_forward_return_shows_true_negative(tmp_path, monkeypatch):
    # HONESTY: a losing paper run shows its TRUE negative number — never the rosy backtest, never floored at 0.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Losing momentum"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)
    _add_paper_fill(store, vid)  # has traded on paper → its TRUE (negative) marked return is surfaced
    store.insert(
        "portfolio_snapshots",
        {
            "scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "97000.00", "cash": "0",
            "positions_value": "97000.00", "pnl": "-3000.00", "drawdown": "0.03",
        },
    )
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert math.isclose(row["paper_return_pct"], -3.0, abs_tol=1e-6)


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


def test_leaderboard_active_track_never_truncated_by_a_stronger_killed_one(tmp_path, monkeypatch):
    # REGRESSION: the board ranks ALL versions together and killed ones hugely outnumber the active. A funded
    # paper track must sort ABOVE a killed version even when the killed has a higher deflated_sharpe — else a
    # stronger graveyard entry pushes a live track off the board and the Paper hero (Σ allocated, status-filtered)
    # disagrees with "Invested" (Σ of the rows that survived the cut). Active-first ordering keeps every
    # non-killed Version on the board.
    client, store = _client(tmp_path, monkeypatch)

    paper_spec = seed_momentum_spec(); paper_spec.name = "Funded paper track"
    paper_vid = _persist_version(store, paper_spec, passed=True)  # status=paper, deflated_sharpe 0.6

    killed_spec = seed_meanrev_spec(); killed_spec.name = "Strong but killed"
    killed_vid = _persist_version(store, killed_spec, passed=False)  # status=killed, deflated_sharpe 0.6
    store.insert(  # a STRONGER backtest for the killed version → it would outrank the paper track on dSR alone
        "backtests",
        {
            "strategy_version_id": killed_vid, "kind": "screen", "oos_return": "0.05", "sharpe": "2", "sortino": "2",
            "deflated_sharpe": "2.5", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 50, "pbo": "0.1",
            "trials_counted": 1, "regime_label": "mixed", "folds_positive": 4,
            "passed_gates": 0, "holdout_passed": 1, "created_at": utcnow(),
        },
    )

    ids = [r["version_id"] for r in client.get("/leaderboard").json()["rows"]]
    assert paper_vid in ids and killed_vid in ids, "both versions must be on the board"
    assert ids.index(paper_vid) < ids.index(killed_vid), "an active track must rank above a stronger KILLED one"


def _add_cost(store: Store, vid: str, amount: str = "5.00") -> None:
    """One opex row attributed to a Version — what makes it appear in the /costs per-strategy table."""
    store.insert(
        "costs",
        {"ts": utcnow(), "vendor": "modal", "category": "compute", "amount": amount,
         "currency": "USD", "strategy_version_id": vid, "meta": "{}"},
    )


def test_costs_net_edge_is_marked_pnl_never_the_backtest_seed(tmp_path, monkeypatch):
    # REGRESSION: per-strategy "net edge" must be the REAL marked forward P&L (scope='track' snapshot −
    # starting_capital), NEVER tracks.equity (seeded with the rosy backtest at funding). A track seeded at a
    # +$4k backtest equity but marked FLAT reads net 0 — the backtest can never surface as realized edge.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Seeded-but-flat"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)  # tracks.equity SEEDED at 104000 on 100000 (the rosy +4% backtest)
    _add_paper_fill(store, vid)
    store.insert(  # the honest marked snapshot: FLAT at starting_capital (no real forward movement)
        "portfolio_snapshots",
        {"scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "100000.00", "cash": "0",
         "positions_value": "100000.00", "pnl": "0.00", "drawdown": "0"},
    )
    _add_cost(store, vid)
    row = next(r for r in client.get("/costs").json()["per_strategy"] if r["version_id"] == vid)
    assert row["net"] == 0.0, "net must be the FLAT marked P&L, never the +$4k backtest seed in tracks.equity"


def test_costs_net_edge_reflects_a_real_marked_gain(tmp_path, monkeypatch):
    # Once genuinely marked up, net edge IS that marked $ P&L (101_500 − 100_000 = +1_500).
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Marked-up cost edge"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)
    _add_paper_fill(store, vid)
    store.insert(
        "portfolio_snapshots",
        {"scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "101500.00", "cash": "0",
         "positions_value": "101500.00", "pnl": "1500.00", "drawdown": "0"},
    )
    _add_cost(store, vid)
    row = next(r for r in client.get("/costs").json()["per_strategy"] if r["version_id"] == vid)
    assert math.isclose(row["net"], 1500.0, abs_tol=1e-6)


def test_costs_net_edge_zero_for_funded_but_unfilled_track(tmp_path, monkeypatch):
    # The documented-arm case: a track funded + marked but with NO real paper fill has $0 realized edge — never
    # the seed, never a fabricated number. Mirrors the leaderboard's has_paper_fills honesty gate.
    client, store = _client(tmp_path, monkeypatch)
    spec = seed_momentum_spec(); spec.name = "Funded unfilled"
    vid = _persist_version(store, spec, passed=True)
    _open_seeded_track(store, vid)  # seeded +$4k, but NO _add_paper_fill
    store.insert(
        "portfolio_snapshots",
        {"scope": "track", "ref_id": vid, "ts": utcnow(), "equity": "104000.00", "cash": "0",
         "positions_value": "104000.00", "pnl": "4000.00", "drawdown": "0"},
    )
    _add_cost(store, vid)
    row = next(r for r in client.get("/costs").json()["per_strategy"] if r["version_id"] == vid)
    assert row["net"] == 0.0, "no real paper fill → $0 realized edge, never the seed/snapshot"
