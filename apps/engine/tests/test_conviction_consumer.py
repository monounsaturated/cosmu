# The AUTHORITY-CONVICTION CONSUMER (cosmu/conviction): a high-authority account's fresh, actionable, non-echo
# asset-call → a propose-only, capped conviction proposal (human-armed). These tests pin the contract the task
# requires: a high-authority actionable call → a CAPPED proposal; a low-authority account → NO proposal; the
# disconfirmer kills neutral/sarcastic/echo/stale calls; sizing scales with authority × EV but the hard max-loss
# cap ALWAYS binds; the lane is propose-only (NOTHING auto-arms); and the store/producer round-trip persists
# proposals without ever arming. Pure + offline + deterministic — no network, no LLM, no money path.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.conviction.authority_source import AccountAuthority, AssetCall, AuthorityStateSource
from cosmu.conviction.disconfirmer import disconfirm
from cosmu.conviction.lane import InMemoryConvictionLane, route_to_conviction_lane
from cosmu.conviction.models import (
    AuthorityEvidence,
    ConvictionCaps,
    ConvictionProposal,
    Direction,
    TopMover,
    make_proposal_id,
)
from cosmu.conviction.producer import recent_returns, refresh_conviction_proposals
from cosmu.conviction.run import propose_from_authority
from cosmu.conviction.sizing import conviction_weight, size_conviction
from cosmu.conviction.store import read_proposals, upsert_proposals
from cosmu.conviction.template import AuthorityConvictionTemplate
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, reset_conviction_proposals_cache
from cosmu.mind.authority import AuthorityState, ClaimContext
from cosmu.mind.claims import Claim
from cosmu.mind.outcomes import AuthorTrackRecord, ResolvedClaim

_NOW = datetime(2024, 2, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- builders


def _auth(
    handle: str = "@sniper",
    *,
    authority_score: float = 0.6,
    ev: float = 0.03,
    n_resolved: int = 30,
    mag: float = 0.08,
) -> AccountAuthority:
    return AccountAuthority(
        account=handle,
        authority_score=authority_score,
        skill=authority_score,
        ev_per_call=ev,
        brier_skill_score=authority_score,
        avg_hit_magnitude=mag,
        n_resolved=n_resolved,
        citation_authority=0.3,
        top_movers=(TopMover("BTC", "up", 0.12, _NOW - timedelta(days=10)),),
    )


def _call(
    handle: str = "@sniper",
    *,
    asset: str = "BTC",
    direction: str = "up",
    conviction: float = 0.8,
    age_h: float = 1.0,
    is_primary: bool = True,
    lead_lag: str = "evidence",
    quote: str = "BTC breaking out, continuation higher into next week",
) -> AssetCall:
    return AssetCall(
        account=handle,
        asset=asset,
        direction=direction,
        conviction=conviction,
        ts=_NOW - timedelta(hours=age_h),
        quote=quote,
        url="https://x.com/sniper/1",
        is_primary=is_primary,
        lead_lag=lead_lag,
    )


def _template(handle: str = "@sniper", caps: ConvictionCaps | None = None) -> AuthorityConvictionTemplate:
    return AuthorityConvictionTemplate(account=handle, caps=caps or ConvictionCaps())


# --------------------------------------------------------------------------- core contract: proposal or not


def test_high_authority_actionable_call_yields_a_capped_proposal():
    caps = ConvictionCaps()
    decision = _template().propose(authority=_auth(), call=_call(), now=_NOW)
    p = decision.proposal
    assert p is not None, decision.reasons
    # propose-only, never armed
    assert p.status == "proposed"
    # directional mapping
    assert p.direction == Direction.LONG
    assert p.asset == "BTC"
    # sized + capped
    assert Decimal("0") < p.size_usd <= caps.per_bet_usd
    # the HARD max-loss cap always binds
    assert p.max_loss_usd <= caps.max_loss_usd
    # the evidence the human reviews is carried through
    assert p.evidence.source_quote == _call().quote
    assert p.evidence.authority_score == _auth().authority_score
    assert p.evidence.top_movers and p.evidence.top_movers[0].entity == "BTC"
    # expiry is set from the call within the actionable window
    assert p.expiry > _NOW


def test_short_call_maps_to_short_direction():
    decision = _template().propose(
        authority=_auth(), call=_call(direction="down", quote="BTC rolling over, lower from here"), now=_NOW
    )
    assert decision.proposal is not None
    assert decision.proposal.direction == Direction.SHORT


def test_low_authority_account_yields_no_proposal():
    decision = _template().propose(authority=_auth(authority_score=0.05), call=_call(), now=_NOW)
    assert decision.proposal is None
    assert any("below_min_authority" in r for r in decision.reasons)


def test_neutral_flat_call_is_not_actionable():
    decision = _template().propose(
        authority=_auth(), call=_call(direction="flat", quote="BTC chopping, no idea here"), now=_NOW
    )
    assert decision.proposal is None
    assert "not_directional" in decision.reasons


def test_sarcasm_call_is_not_actionable():
    decision = _template().propose(
        authority=_auth(), call=_call(quote="oh sure BTC to 1m by friday /s"), now=_NOW
    )
    assert decision.proposal is None
    assert "sarcasm_or_disclaimer" in decision.reasons


def test_low_conviction_call_is_not_actionable():
    decision = _template().propose(authority=_auth(), call=_call(conviction=0.2), now=_NOW)
    assert decision.proposal is None
    assert any("low_conviction" in r for r in decision.reasons)


def test_echo_lead_lag_call_is_dropped():
    decision = _template().propose(authority=_auth(), call=_call(lead_lag="echo"), now=_NOW)
    assert decision.proposal is None
    assert "reacting_to_event" in decision.reasons


def test_non_primary_call_is_dropped_as_echo():
    decision = _template().propose(authority=_auth(), call=_call(is_primary=False), now=_NOW)
    assert decision.proposal is None
    assert "not_primary" in decision.reasons


def test_move_already_played_out_is_dropped_as_echo():
    # the asset already ran +9% in the call's direction since the call → chasing a move that's over
    decision = _template().propose(authority=_auth(), call=_call(), now=_NOW, recent_return=0.09)
    assert decision.proposal is None
    assert any("move_already_played_out" in r for r in decision.reasons)


def test_a_small_recent_move_does_not_block():
    decision = _template().propose(authority=_auth(), call=_call(), now=_NOW, recent_return=0.01)
    assert decision.proposal is not None


def test_stale_call_beyond_window_is_dropped():
    decision = _template().propose(authority=_auth(), call=_call(age_h=72.0), now=_NOW)
    assert decision.proposal is None
    assert any("stale_call" in r for r in decision.reasons)


def test_wrong_account_call_is_rejected():
    decision = _template(handle="@other").propose(authority=_auth("@sniper"), call=_call("@sniper"), now=_NOW)
    assert decision.proposal is None
    assert "wrong_account" in decision.reasons


# --------------------------------------------------------------------------- sizing: profit > hit-rate, hard caps


def test_size_scales_with_authority():
    caps = ConvictionCaps()
    hi, _ = size_conviction(_auth(authority_score=0.6), caps)
    lo, _ = size_conviction(_auth(authority_score=0.3), caps)
    assert hi > lo
    assert hi <= caps.per_bet_usd and lo <= caps.per_bet_usd


def test_size_scales_with_ev():
    caps = ConvictionCaps()
    big_ev, _ = size_conviction(_auth(ev=0.06), caps)
    small_ev, _ = size_conviction(_auth(ev=0.0), caps)
    assert big_ev > small_ev  # a few-but-huge (high-EV) caller sizes bigger at equal authority


def test_conviction_weight_is_zero_for_zero_authority():
    assert conviction_weight(_auth(authority_score=0.0)) == 0.0
    assert size_conviction(_auth(authority_score=0.0), ConvictionCaps()) == (Decimal("0"), Decimal("0"))


def test_max_loss_cap_always_binds_even_with_a_huge_per_bet_cap():
    caps = ConvictionCaps(per_bet_usd=Decimal("100000"), max_loss_usd=Decimal("15"))
    size, max_loss = size_conviction(_auth(authority_score=1.0, ev=1.0), caps)
    assert size > caps.max_loss_usd          # the bet can be large
    assert max_loss <= caps.max_loss_usd     # but the hard max-loss still binds


def test_size_never_exceeds_per_bet_cap():
    caps = ConvictionCaps(per_bet_usd=Decimal("10"))
    size, _ = size_conviction(_auth(authority_score=1.0, ev=1.0), caps)
    assert size <= caps.per_bet_usd


# --------------------------------------------------------------------------- disconfirmer in isolation


def test_disconfirmer_passes_a_clean_call():
    assert disconfirm(_call(), recent_return=0.0).passes


def test_disconfirmer_flags_flat_and_echo_together():
    res = disconfirm(_call(direction="flat", lead_lag="echo"), recent_return=None)
    assert not res.passes
    assert not res.actionable and res.echo


# --------------------------------------------------------------------------- the lane is PROPOSE-ONLY, never arms


def test_lane_accepts_a_proposed_proposal_and_never_arms():
    lane = InMemoryConvictionLane()
    decision = _template().propose(authority=_auth(), call=_call(), now=_NOW)
    route_to_conviction_lane(decision.proposal, lane)
    queue = lane.open_proposals()
    assert len(queue) == 1
    assert all(p.status == "proposed" for p in queue)
    # structurally there is NO way to arm/execute/fund from the lane
    assert not hasattr(lane, "arm")
    assert not hasattr(lane, "execute")
    assert not hasattr(lane, "fund")


def test_lane_refuses_a_non_proposed_status():
    lane = InMemoryConvictionLane()
    decision = _template().propose(authority=_auth(), call=_call(), now=_NOW)
    armed = ConvictionProposal(
        **{**decision.proposal.__dict__, "status": "armed"}  # type: ignore[arg-type]
    )
    try:
        lane.submit(armed)
        raise AssertionError("lane must refuse a non-proposed proposal")
    except ValueError as exc:
        assert "propose-only" in str(exc)


# --------------------------------------------------------------------------- orchestration over an AuthoritySource


def _state_source(*, sniper_skill: float = 0.6, spammer_skill: float = 0.02) -> AuthorityStateSource:
    """A hand-built AuthorityStateSource: a high-skill @sniper with a fresh BTC call, and a low-skill @spammer
    with one too. Built from the REAL shapes (AuthorTrackRecord, ClaimContext, ResolvedClaim) so the adapter
    mapping is exercised without the fiddly bar-construction that compute_authority's skill numerics need."""
    sniper_claim = Claim(
        handle="@sniper", platform="x", post_id="s1", entity="BTC", direction="up", horizon="1w",
        horizon_days=7, conviction=0.8, ts=_NOW - timedelta(hours=2), quote="BTC breakout, higher", url="u1",
    )
    spammer_claim = Claim(
        handle="@spammer", platform="x", post_id="p1", entity="ETH", direction="up", horizon="1w",
        horizon_days=7, conviction=0.9, ts=_NOW - timedelta(hours=2), quote="ETH up forever", url="u2",
    )
    track_records = {
        "@sniper": _track("@sniper", skill=sniper_skill, excess=0.4, mag=0.10),
        "@spammer": _track("@spammer", skill=spammer_skill, excess=0.0, mag=0.02),
    }
    state = AuthorityState(
        as_of=_NOW,
        author_authority={"@sniper": 0.5, "@spammer": 0.5},
        track_records=track_records,
        contexts=[
            ClaimContext(claim=sniper_claim, is_primary=True, lead_seconds=None, lead_lag="evidence"),
            ClaimContext(claim=spammer_claim, is_primary=True, lead_seconds=None, lead_lag="evidence"),
        ],
        primacy_rate={"@sniper": 1.0, "@spammer": 1.0},
        evidence_rate={"@sniper": 1.0, "@spammer": 1.0},
    )
    resolved = [
        ResolvedClaim(
            claim=sniper_claim, status="resolved", entry_ts=sniper_claim.ts, exit_ts=_NOW,
            entry_price=100.0, exit_price=112.0, realized_return=0.12, hit=True, base_rate=0.5, base_abs_move=0.03,
        )
    ]
    return AuthorityStateSource(state=state, resolved=resolved)


def _track(handle: str, *, skill: float, excess: float, mag: float) -> AuthorTrackRecord:
    return AuthorTrackRecord(
        handle=handle, n_claims=40, n_resolved=30, hit_rate=0.6, base_hit_rate=0.6 - excess,
        excess_hit_rate=excess, brier=0.1, brier_base=0.25, brier_skill_score=skill,
        calibration_error=0.05, avg_hit_magnitude=mag, magnitude_vs_base=mag / 0.03, skill=skill,
    )


def test_adapter_maps_track_record_to_account_authority():
    src = _state_source()
    a = src.account_authority("@sniper")
    assert a is not None
    assert a.authority_score == 0.6 and a.skill == 0.6
    # EV proxy = excess_hit_rate × avg_hit_magnitude
    assert abs(a.ev_per_call - 0.4 * 0.10) < 1e-9
    # top movers come from the resolved hits
    assert a.top_movers and a.top_movers[0].realized_return == 0.12
    assert src.account_authority("@unknown") is None


def test_adapter_fresh_calls_filters_by_account_and_recency():
    src = _state_source()
    calls = src.fresh_calls("@sniper", now=_NOW, max_age_hours=24.0)
    assert [c.asset for c in calls] == ["BTC"]
    # outside the window → nothing
    assert src.fresh_calls("@sniper", now=_NOW + timedelta(days=5), max_age_hours=24.0) == []


def test_orchestration_proposes_for_sniper_not_spammer():
    src = _state_source(sniper_skill=0.6, spammer_skill=0.02)
    lane = InMemoryConvictionLane()
    proposals = propose_from_authority(
        src, ["@sniper", "@spammer"], caps=ConvictionCaps(), now=_NOW, lane=lane
    )
    accounts = {p.account for p in proposals}
    assert accounts == {"@sniper"}  # the spammer (skill ~0) never clears the authority gate
    assert all(p.status == "proposed" for p in proposals)
    assert len(lane.open_proposals()) == 1


# --------------------------------------------------------------------------- persistence: round-trip, never armed


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/conviction.sqlite3", openrouter_api_key=None))


def _proposal(account: str = "@sniper", asset: str = "BTC") -> ConvictionProposal:
    evidence = AuthorityEvidence(
        account=account, authority_score=0.6, skill=0.6, ev_per_call=0.04, brier_skill_score=0.6,
        avg_hit_magnitude=0.1, n_resolved=30, citation_authority=0.3,
        top_movers=(TopMover("BTC", "up", 0.12, _NOW - timedelta(days=10)),),
        source_quote="BTC breakout", source_url="u1", is_primary=True, lead_lag="evidence",
    )
    return ConvictionProposal(
        proposal_id=make_proposal_id(account, asset, Direction.LONG, _NOW),
        account=account, asset=asset, direction=Direction.LONG, size_usd=Decimal("12.00"),
        max_loss_usd=Decimal("6.00"), expiry=_NOW + timedelta(hours=24), thesis="because authority",
        evidence=evidence, created_at=_NOW,
    )


def test_store_roundtrip_preserves_fields(tmp_path):
    store = _store(tmp_path)
    reset_conviction_proposals_cache()
    n = upsert_proposals(store, [_proposal()])
    assert n == 1
    rows = read_proposals(store, now=_NOW)
    assert len(rows) == 1
    p = rows[0]
    assert p.status == "proposed"
    assert p.size_usd == Decimal("12.00") and p.max_loss_usd == Decimal("6.00")
    assert p.direction == Direction.LONG
    assert p.evidence.source_quote == "BTC breakout"
    assert p.evidence.top_movers[0].realized_return == 0.12


def test_store_upsert_is_idempotent(tmp_path):
    store = _store(tmp_path)
    reset_conviction_proposals_cache()
    upsert_proposals(store, [_proposal()])
    upsert_proposals(store, [_proposal()])  # same deterministic id → updates, no duplicate
    assert len(read_proposals(store, now=_NOW)) == 1


def test_store_drops_expired_by_default(tmp_path):
    store = _store(tmp_path)
    reset_conviction_proposals_cache()
    upsert_proposals(store, [_proposal()])
    later = _NOW + timedelta(days=2)  # past the proposal's 24h expiry
    assert read_proposals(store, now=later) == []
    assert len(read_proposals(store, now=later, include_expired=True)) == 1


def test_store_defensive_empty_when_table_absent(tmp_path):
    store = _store(tmp_path)
    with store.batch() as writer:
        writer.execute("DROP TABLE IF EXISTS conviction_proposals")
    reset_conviction_proposals_cache()
    assert read_proposals(store, now=_NOW) == []
    assert upsert_proposals(store, [_proposal()]) == 0  # write no-ops too


def test_producer_persists_proposals_and_never_arms(tmp_path, monkeypatch):
    store = _store(tmp_path)
    reset_conviction_proposals_cache()
    src = _state_source()
    # The producer builds the source from claims+bars; pin it to our controlled source.
    monkeypatch.setattr(AuthorityStateSource, "build", classmethod(lambda cls, *a, **k: src))
    produced = refresh_conviction_proposals(
        store,
        claims=[src.resolved[0].claim],
        bars_by_entity={"BTC": []},
        accounts=["@sniper", "@spammer"],
        now=_NOW,
    )
    assert produced and {p.account for p in produced} == {"@sniper"}
    assert all(p.status == "proposed" for p in produced)
    read = read_proposals(store, now=_NOW)
    assert {p.proposal_id for p in read} == {p.proposal_id for p in produced}


def test_recent_returns_computes_signed_move():
    bars = [Bar(ts=_NOW - timedelta(days=8 - i), open=0, high=0, low=0, close=100 + i, volume=0) for i in range(9)]
    rr = recent_returns({"BTC": bars}, lookback_bars=7)
    assert "BTC" in rr and rr["BTC"] > 0  # rising series → positive recent return
