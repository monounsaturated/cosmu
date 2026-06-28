# intent: pin the WAVE-0 inbox-seed novelty gate (roadmap #8) — the dominant authoring door (`.json` inbox specs
# → scan_inbox → FarmLoop extra_seeds wave-0) was the ONE intake path NEVER novelty-checked, so near-duplicate
# seeds each ate an independent slot in the Gate's BH-FDR multiple-testing budget. The fix novelty-checks each
# non-seed wave-0 candidate with a HUMAN-vs-AGENT policy split: an AGENT near-dup is HARD-SKIPPED (no FDR flood),
# a HUMAN near-dup is KEPT but flagged with an `inbox_near_dup` event, a genuinely-novel seed passes unchanged.
# Two layers: (1) UNIT-test the pure wave-0 verdict (the policy split, no compute) and (2) an INTEGRATION test
# that runs the REAL run_cohort over a small offline fixture market so the event wiring is proven end-to-end.

from __future__ import annotations

import json

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.loop import Candidate, FarmLoop
from cosmu.knowledge.store import Store
from cosmu.lab.inbox import _authored_by
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/inbox_novelty.sqlite3", openrouter_api_key=None))


def _spec(features: list[str], *, name: str, bar_size: str = "1d", max_hold_days: int = 14) -> StrategySpec:
    """A minimal valid spec. STRUCTURAL novelty (structural_distance) reads ONLY the entry-feature set + bar_size,
    so two specs with the same feature set are NEAR-DUPLICATES (distance 0). We vary `max_hold_days` to give a
    near-dup a DIFFERENT combo_hash (which includes the hold window) — this isolates the structural NOVELTY gate
    from the exact-combo `_is_duplicate` dedup, exactly the case the inbox-lint near-dup clusters represent
    (structurally close but not byte-identical hypotheses)."""
    entry = [Condition(feature=FeatureRef(name=f), op="gt", threshold=ParamRef(param=f"th_{f}")) for f in features]
    ps = {f"th_{f}": ParamSpace(kind="float", lo=0.0, hi=1.0) for f in features}
    ps["sl"] = ParamSpace(kind="float", lo=0.01, hi=0.1)
    ps["tp"] = ParamSpace(kind="float", lo=0.01, hi=0.2)
    return StrategySpec(
        name=name,
        rationale="test seed",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"]),
        horizon=Horizon(bar_size=bar_size, min_hold_days=1, max_hold_days=max_hold_days),
        entry=entry,
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space=ps,
    )


def _cand(spec: StrategySpec, authored_by: str = "human") -> Candidate:
    return Candidate(spec=spec, origin="chat", lane="chat", operator="chat_author", authored_by=authored_by)


def _near_dup_events(store: Store) -> list[dict]:
    rows = store.rows("SELECT payload FROM events WHERE kind = 'inbox_near_dup' ORDER BY id ASC")
    out: list[dict] = []
    for r in rows:
        p = r["payload"]
        out.append(json.loads(p) if isinstance(p, str) else p)
    return out


# --------------------------------------------------------------------------- (1) the pure wave-0 verdict (policy)


def test_verdict_agent_near_dup_is_skip(tmp_path):
    """ACCEPTANCE: an AGENT-authored near-duplicate is SKIPPED at wave-0 (hard-dedupe protects the FDR budget)."""
    loop = FarmLoop(settings=_store(tmp_path).settings, store=_store(tmp_path))
    base = _spec(["rsi", "adx"], name="base")
    clone = _spec(["rsi", "adx"], name="clone", max_hold_days=10)  # near-dup (same structure, diff combo_hash)
    assert loop._wave0_novelty_verdict(_cand(clone, "agent"), admitted=[base]) == "skip"


def test_verdict_human_near_dup_is_flag(tmp_path):
    """ACCEPTANCE: a HUMAN-authored near-duplicate is KEPT but FLAGGED ('flag') — intentional work is never dropped."""
    loop = FarmLoop(settings=_store(tmp_path).settings, store=_store(tmp_path))
    base = _spec(["rsi", "adx"], name="base")
    clone = _spec(["rsi", "adx"], name="clone", max_hold_days=10)
    assert loop._wave0_novelty_verdict(_cand(clone, "human"), admitted=[base]) == "flag"


def test_verdict_novel_seed_is_ok(tmp_path):
    """ACCEPTANCE: a genuinely-novel seed (disjoint structure) passes unchanged ('ok') for any provenance."""
    loop = FarmLoop(settings=_store(tmp_path).settings, store=_store(tmp_path))
    base = _spec(["rsi", "adx"], name="base")
    novel = _spec(["bb_z", "vol_realized"], name="novel")  # disjoint feature set ⇒ distinct hypothesis
    assert loop._wave0_novelty_verdict(_cand(novel, "agent"), admitted=[base]) == "ok"
    assert loop._wave0_novelty_verdict(_cand(novel, "human"), admitted=[base]) == "ok"


def test_verdict_seed_lane_never_checked(tmp_path):
    """The curated seed-population baseline is never inter-novelty-checked (matches the _is_duplicate seed exemption)."""
    loop = FarmLoop(settings=_store(tmp_path).settings, store=_store(tmp_path))
    base = _spec(["rsi", "adx"], name="base")
    twin = _spec(["rsi", "adx"], name="twin", max_hold_days=10)
    seed_cand = Candidate(spec=twin, origin="seed", lane="seed")
    assert loop._wave0_novelty_verdict(seed_cand, admitted=[base]) == "ok"


def test_verdict_first_seed_is_ok_empty_admitted(tmp_path):
    """The first authoring-door seed (nothing admitted yet) always passes — there is nothing to be a dup of."""
    loop = FarmLoop(settings=_store(tmp_path).settings, store=_store(tmp_path))
    first = _spec(["rsi", "adx"], name="first")
    assert loop._wave0_novelty_verdict(_cand(first, "agent"), admitted=[]) == "ok"


# --------------------------------------------------------------------------- (2) end-to-end through run_cohort


class _FixtureBars:
    """Small offline market (2 catalog symbols × edge-bearing bars) so the real screen runs fast in CI — no network."""

    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def test_run_cohort_agent_near_dup_dropped_human_kept(tmp_path):
    """END-TO-END through the REAL run_cohort + screen + persist: of two near-duplicate authoring-door seeds, the
    AGENT-provenance batch drops the clone (counted duplicate, never generated) while the HUMAN-provenance batch
    keeps both and emits an `inbox_near_dup` flag — proving the event wiring fires through the real path."""
    base = _spec(["rsi", "adx"], name="ed-base")
    clone = _spec(["rsi", "adx"], name="ed-clone", max_hold_days=10)

    # AGENT batch → the clone is hard-skipped (one of the two seeds never becomes a generated version).
    store_a = _store(tmp_path / "a")
    (tmp_path / "a").mkdir(exist_ok=True)
    loop_a = FarmLoop(settings=store_a.settings, store=store_a, market_data=_FixtureBars())
    summary_a = loop_a.run_cohort(
        cohort_size=2, explore_pct=0.0,
        extra_seeds=[base, clone], extra_seeds_authored_by=["agent", "agent"],
    )
    skipped = [e for e in _near_dup_events(store_a) if e["action"] == "skipped"]
    assert any(e["name"] == "ed-clone" and e["authored_by"] == "agent" for e in skipped)
    assert summary_a.duplicates >= 1
    assert summary_a.lanes["chat"] == 1  # only ONE authoring-door seed survived to the screen (the base)

    # HUMAN batch → both kept, the clone flagged (intentional authorship respected).
    store_h = _store(tmp_path / "h")
    (tmp_path / "h").mkdir(exist_ok=True)
    loop_h = FarmLoop(settings=store_h.settings, store=store_h, market_data=_FixtureBars())
    summary_h = loop_h.run_cohort(
        cohort_size=2, explore_pct=0.0,
        extra_seeds=[base, clone], extra_seeds_authored_by=["human", "human"],
    )
    flagged = [e for e in _near_dup_events(store_h) if e["action"] == "kept_flagged"]
    assert any(e["name"] == "ed-clone" and e["authored_by"] == "human" for e in flagged)
    assert summary_h.duplicates == 0
    assert summary_h.lanes["chat"] == 2  # BOTH authoring-door seeds reached the screen


def test_run_cohort_novel_seeds_no_flag(tmp_path):
    """Two genuinely-distinct authoring-door seeds both pass with NO near-dup event — existing behaviour preserved."""
    store = _store(tmp_path)
    a = _spec(["rsi", "adx"], name="distinct-a")
    b = _spec(["bb_z", "vol_realized"], name="distinct-b")
    loop = FarmLoop(settings=store.settings, store=store, market_data=_FixtureBars())
    summary = loop.run_cohort(
        cohort_size=2, explore_pct=0.0,
        extra_seeds=[a, b], extra_seeds_authored_by=["agent", "agent"],
    )
    assert _near_dup_events(store) == []
    assert summary.duplicates == 0
    assert summary.lanes["chat"] == 2


# --------------------------------------------------------------------------- (3) provenance resolver


def test_authored_by_resolves_agent_from_event_ledger(tmp_path):
    """The inbox provenance resolver reads the AUTHORING events: an agent-authored file (strategize_authored,
    actor='agent') resolves to 'agent'; an unknown hash defaults to 'human' (never silently droppable)."""
    store = _store(tmp_path)
    store.append_event(
        actor="agent", kind="strategize_authored", ref_type="strategy_spec",
        payload={"content_hash": "deadbeefagent", "name": "x"},
    )
    store.append_event(
        actor="human", kind="inbox_queued", ref_type="strategy_spec",
        payload={"content_hash": "cafehuman", "name": "y"},
    )
    assert _authored_by(store, "deadbeefagent") == "agent"
    assert _authored_by(store, "cafehuman") == "human"
    assert _authored_by(store, "no-such-hash") == "human"  # unknown ⇒ conservative default
