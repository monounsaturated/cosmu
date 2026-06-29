# The CONVICTION lane (master/conviction.py): the separate evaluator for kind='llm' (= conviction = moonshot)
# strategies that can't be backtested cleanly. These tests prove the three operator invariants:
#   1. a conviction strategy is ROUTED to the conviction path — never the quant Gate (promote_brut/promote_cohort);
#   2. it RESPECTS the hard max-loss cap (and the small-size / confidence / venue / execution guardrails);
#   3. it is NEVER auto-armed — the verdict's `armed` is always False and a human must arm.
# Plus first-class lifecycle (verdict persists, a track is born honest + observe-only) and realism (live venue,
# maker/taker, NOT paper-only Alpaca).

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.conviction import (
    ConvictionCaps,
    assert_quant,
    is_conviction,
    open_conviction_track,
    persist_conviction_verdict,
    propose_conviction,
    route_kind,
)
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.strategy.agent_author import open_agent_strategy
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec, ConvictionDecl
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
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/conviction.sqlite3"))


def _decl(**over) -> ConvictionDecl:
    """A valid, in-caps conviction declaration (live venue, maker, $20 stake ≤ $20 max-loss, 70% confidence)."""
    kw = dict(
        thesis="credible insider signal the market hasn't priced",
        confidence=0.7,
        disconfirmer="the cited filing is retracted or the catalyst date slips past expiry",
        max_loss_usd=Decimal("20"),
        size_usd=Decimal("20"),
        venue="ibkr",
        execution="maker",
        expiry=None,
    )
    kw.update(over)
    return ConvictionDecl(**kw)


def _agent(decl: ConvictionDecl | None = None) -> AgentSpec:
    return AgentSpec(
        name="conviction-bet",
        rationale="reasoned conviction bet on a catalyst",
        symbols=["AAPL"],
        venues=["ibkr"],
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2),
        conviction=decl,
    )


def _quant_spec(name: str = "mined", *, kind: str = "quant") -> StrategySpec:
    return StrategySpec(
        name=name,
        rationale="test",
        kind=kind,  # type: ignore[arg-type]
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"]),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=5),
        entry=[Condition(feature=FeatureRef(name="rsi"), op="lt", threshold=ParamRef(param="thr"))],
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "thr": ParamSpace(kind="float", lo=10, hi=40),
            "sl": ParamSpace(kind="float", lo=0.01, hi=0.1),
            "tp": ParamSpace(kind="float", lo=0.01, hi=0.2),
        },
    )


# ─────────────────────────────────────────────────────────────── routing: conviction ≠ quant Gate

def test_route_kind_discriminates_llm_from_quant():
    assert route_kind(_agent(_decl())) == "conviction"
    assert route_kind(_quant_spec(kind="quant")) == "quant"
    assert route_kind(_quant_spec(kind="llm")) == "conviction"  # a StrategySpec marked llm routes to conviction too
    assert is_conviction(_agent(_decl())) is True
    assert is_conviction(_quant_spec()) is False


def test_lane_router_refuses_llm_never_reaches_the_gate():
    # The choke point: a kind='llm' spec handed to the quant lane router must FAIL LOUDLY, never silently hit
    # promote_cohort/promote_brut (the bug the conviction lane exists to prevent).
    with pytest.raises(ValueError, match="conviction"):
        evaluate_by_lane(_quant_spec(kind="llm"), gates=GateSettings())


def test_assert_quant_guards_the_gate_boundary():
    assert_quant(_quant_spec(kind="quant"))  # no-op for a quant spec
    with pytest.raises(ValueError, match="conviction"):
        assert_quant(_agent(_decl()))
    with pytest.raises(ValueError, match="conviction"):
        assert_quant(_quant_spec(kind="llm"))


def test_propose_conviction_refuses_a_quant_spec():
    # The conviction path is for kind='llm' ONLY — a quant spec must be rejected (it belongs on the Gate).
    with pytest.raises(ValueError, match="kind='llm' only"):
        propose_conviction(_quant_spec(kind="quant"))  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────── guardrails

def test_eligible_bet_is_proposed_but_never_armed():
    v = propose_conviction(_agent(_decl()))
    assert v.eligible is True
    assert v.reasons == ["pass"]
    # THE invariant: propose-only. Eligible means a HUMAN may arm — code never does.
    assert v.armed is False
    assert v.requires_human is True
    # the declaration is echoed for the UI/audit
    assert v.thesis and v.disconfirmer and v.venue == "ibkr" and v.execution == "maker"
    assert v.max_loss_usd == Decimal("20") and v.size_usd == Decimal("20")


def test_max_loss_over_cap_is_blocked():
    caps = ConvictionCaps(max_loss_usd=Decimal("50"))
    v = propose_conviction(_agent(_decl(max_loss_usd=Decimal("100"), size_usd=Decimal("40"))), caps)
    assert v.eligible is False
    assert any(r.startswith("max_loss_over_cap") for r in v.reasons)
    assert v.armed is False  # blocked or not, never armed


def test_size_over_cap_is_blocked():
    caps = ConvictionCaps(max_size_usd=Decimal("50"))
    # max_loss raised so the only failing rail is the size cap (isolates the reason)
    v = propose_conviction(_agent(_decl(size_usd=Decimal("60"), max_loss_usd=Decimal("60"))), caps)
    assert v.eligible is False
    assert any(r.startswith("size_over_cap") for r in v.reasons)


def test_size_exceeding_declared_max_loss_is_blocked():
    # A cash bet can lose at most its stake — a stake > declared max-loss understates downside → reject.
    v = propose_conviction(_agent(_decl(size_usd=Decimal("30"), max_loss_usd=Decimal("20"))))
    assert v.eligible is False
    assert any(r.startswith("size_exceeds_max_loss") for r in v.reasons)


def test_low_confidence_is_blocked():
    caps = ConvictionCaps(min_confidence=Decimal("0.6"))
    v = propose_conviction(_agent(_decl(confidence=0.4)), caps)
    assert v.eligible is False
    assert any(r.startswith("confidence_below_min") for r in v.reasons)


def test_expired_conviction_is_blocked():
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    v = propose_conviction(_agent(_decl(expiry=past)))
    assert v.eligible is False
    assert "expired" in v.reasons


def test_no_conviction_declaration_is_observe_only_not_an_error():
    # A kind='llm' agent with NO ConvictionDecl is observe-only — not eligible, but never raises (the existing
    # observe-only agent path is unaffected).
    v = propose_conviction(_agent(decl=None))
    assert v.eligible is False
    assert v.reasons == ["no_conviction_declaration"]
    assert v.armed is False and v.requires_human is False


# ─────────────────────────────────────────────────────────────── realism: venue + execution

def test_paper_only_alpaca_venue_is_rejected():
    # Alpaca is data/paper-only (live_enabled=False) — it can never host a real-money conviction bet.
    v = propose_conviction(_agent(_decl(venue="alpaca")))
    assert v.eligible is False
    assert any(r.startswith("paper_only_venue") for r in v.reasons)


def test_unknown_venue_is_rejected():
    v = propose_conviction(_agent(_decl(venue="ftx")))
    assert v.eligible is False
    assert any(r.startswith("unknown_venue") for r in v.reasons)


@pytest.mark.parametrize("venue", ["ibkr", "kraken", "polymarket"])
def test_operator_named_live_venues_are_accepted(venue):
    # IBKR / Kraken / Polymarket — the live-capable conviction venues the operator named.
    v = propose_conviction(_agent(_decl(venue=venue)))
    assert v.eligible is True and v.venue == venue


def test_bad_execution_is_rejected():
    # ConvictionDecl's Literal blocks a bad execution at construction — the lane is defended at the model boundary.
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        _decl(execution="iceberg")


# ─────────────────────────────────────────────────────────────── first-class lifecycle: verdict + track

def test_verdict_persists_to_gate_verdicts_as_conviction(tmp_path):
    store = _store(tmp_path)
    spec = _agent(_decl())
    v = propose_conviction(spec)
    assert persist_conviction_verdict(store, spec, v, run_id="run-1") is True
    row = store.row("SELECT decision, data_source, payload FROM gate_verdicts LIMIT 1")
    assert row is not None
    assert row["decision"] == "PROPOSED"
    assert row["data_source"] == "conviction"
    payload = json.loads(row["payload"])
    assert payload["kind"] == "conviction"
    assert payload["armed"] is False
    assert payload["venue"] == "ibkr" and payload["execution"] == "maker"
    # and an audit event was written
    ev = store.row("SELECT kind FROM events WHERE kind = 'conviction_proposed' LIMIT 1")
    assert ev is not None


def test_blocked_verdict_persists_as_blocked(tmp_path):
    store = _store(tmp_path)
    spec = _agent(_decl(venue="alpaca"))
    v = propose_conviction(spec)
    persist_conviction_verdict(store, spec, v)
    row = store.row("SELECT decision FROM gate_verdicts LIMIT 1")
    assert row is not None and row["decision"] == "BLOCKED"


def test_conviction_track_is_born_honest_and_not_live(tmp_path):
    store = _store(tmp_path)
    # author the kind='llm' strategy first so the track references a real version
    version_id = open_agent_strategy(store, _agent(_decl()))
    v = propose_conviction(_agent(_decl()))
    track_id = open_conviction_track(store, version_id=version_id, verdict=v)
    assert track_id is not None
    track = store.row(
        "SELECT equity, return_pct, starting_capital, venue_id FROM tracks WHERE id = ?", (track_id,)
    )
    assert track is not None
    # born honest: equity = declared stake, ZERO forward P&L (never seeded from a backtest number)
    assert Decimal(str(track["equity"])) == Decimal("20.00")
    assert Decimal(str(track["return_pct"])) == Decimal("0.00")
    assert track["venue_id"] == "ibkr"
    # NEVER live — opening the observe track did not flip the version to live nor arm anything
    ver = store.row("SELECT status FROM strategy_versions WHERE id = ?", (version_id,))
    assert ver is not None and ver["status"] != "live"
    assert store.row("SELECT COUNT(*) AS n FROM events WHERE kind = 'live_armed'")["n"] == 0


def test_ineligible_bet_gets_no_track(tmp_path):
    store = _store(tmp_path)
    version_id = open_agent_strategy(store, _agent(_decl()))
    blocked = propose_conviction(_agent(_decl(venue="alpaca")))
    assert open_conviction_track(store, version_id=version_id, verdict=blocked) is None
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
