# The STANDING TRIPWIRES on the authority lane (the template's leakage guards). Two disconfirmers, both offline +
# deterministic, no LLM:
#   1. SNIPER vs SPAMMER — the price-anchored skill must REWARD beating the base rate, not being loud. A voice
#      that calls the move early AND is right scores high; a spammer who only reproduces the dominant drift scores
#      ~0. If this ever collapses (spammer ≈ sniper), the metric is rewarding volume, not skill.
#   2. TIME-REVERSAL / LEAD-LAG SYMMETRY (the astro lesson) — an ECHO (a claim that merely FOLLOWED the news) looks
#      like foresight under a time-reversed event timeline. The forward-vs-reversed asymmetry is the tripwire: a
#      genuine foresight call is evidence forward and NOT under reversal; a pure echo flips. Keep these GREEN.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.mind.authority import Event, classify_lead_lag, compute_authority
from cosmu.mind.claims import Claim, horizon_to_days

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(closes: list[float]) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(Bar(ts=_T0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal(0)))
    return out


def _claim(handle, direction, *, ts, entity="BTC", horizon="3d", conviction=0.8, pid="p") -> Claim:
    return Claim(handle=handle, platform="x", post_id=pid, entity=entity, direction=direction,
                 horizon=horizon, horizon_days=horizon_to_days(horizon), conviction=conviction, ts=ts)


# --------------------------------------------------------------------------- 1. sniper vs spammer


def test_skill_separates_a_sniper_from_a_spammer():
    # A tape with repeated sharp DOWN flushes (each segment: up, up, then a -15% drop, repeated). The SNIPER calls
    # each flush right, just before it happens (early + correct) → genuine excess over the base rate → real skill.
    # The SPAMMER fires "up" constantly → just reproduces the drift, beats nothing → ~0 skill. Skill is excess over
    # base, NOT raw hit-rate, so a loud account that is "often right" the easy way scores ~0.
    segment = [100, 101, 102, 85, 86, 87]  # two up days then a sharp flush
    closes: list[float] = []
    for k in range(6):
        closes += [v + k * 5 for v in segment]  # six flush cycles, gently drifting up
    closes += [closes[-1] + i for i in range(20)]
    bars = _bars(closes)
    market = {"BTC": bars}
    now = bars[-1].ts + timedelta(days=1)

    claims = []
    # SNIPER: a DOWN call just before each flush (index 2 of every 6-day segment).
    for i in range(2, len(segment) * 6, 6):
        claims.append(_claim("@sniper", "down", ts=bars[i].ts, pid=f"sn{i}"))
    # SPAMMER: fires "up" on most days (reproduces the dominant drift — loud, base-rate).
    for i in range(0, len(segment) * 6, 2):
        claims.append(_claim("@spammer", "up", ts=bars[i].ts, pid=f"sp{i}"))

    state = compute_authority(claims, bars_by_entity=market, as_of=now)
    sniper = state.track_records.get("@sniper")
    spammer = state.track_records.get("@spammer")
    assert sniper is not None and spammer is not None
    assert sniper.hit_rate == 1.0 and sniper.base_hit_rate < 0.5   # the sniper genuinely beats the base rate
    assert sniper.skill > 0.2 and spammer.skill < 0.05            # real skill vs ~0 — the metric rewards skill not noise
    assert state.author_authority["@sniper"] > state.author_authority["@spammer"]  # authority follows skill


# --------------------------------------------------------------------------- 2. time-reversal / lead-lag symmetry


def test_time_reversal_distinguishes_foresight_from_echo():
    # A foresight claim PRECEDES the event; an echo FOLLOWS it. Reverse the event timeline about the claim and the
    # labels must flip — that asymmetry is the disconfirmer.
    claim_ts = _T0 + timedelta(days=10)
    foresight = _claim("@first", "up", ts=claim_ts, pid="f")
    echo = _claim("@late", "up", ts=claim_ts, pid="e")

    event_after = [Event(ts=claim_ts + timedelta(days=2), entity="BTC")]   # event AFTER → foresight is evidence
    event_before = [Event(ts=claim_ts - timedelta(days=1), entity="BTC")]  # event BEFORE → echo reacted to it

    # Forward timeline: foresight = evidence, echo = echo.
    assert classify_lead_lag(foresight, event_after) == "evidence"
    assert classify_lead_lag(echo, event_before) == "echo"

    # TIME-REVERSAL tripwire: mirror each event timeline about the claim. A genuine foresight call is NO LONGER
    # evidence under reversal (its asymmetry survives); a pure echo becomes "evidence" under reversal (it had no
    # real foresight — only the time-ordering made it look bad). The flip is the standing alarm.
    def _mirror(events: list[Event]) -> list[Event]:
        return [Event(ts=claim_ts - (e.ts - claim_ts), entity=e.entity) for e in events]

    assert classify_lead_lag(foresight, _mirror(event_after)) == "echo"      # foresight flips → asymmetric (real)
    assert classify_lead_lag(echo, _mirror(event_before)) == "evidence"      # echo flips → its "skill" was artifact


def test_foresight_outweighs_echo_in_a_mixed_consensus():
    # Two equally-credible voices disagree: @up calls UP with FORESIGHT (an event lands just after — the voice led
    # it), @down calls DOWN as an ECHO (an event landed just before — the voice reacted to it). The credibility-
    # weighted consensus must tilt toward the FORESIGHT call, because the echo is down-weighted. Without the wired
    # event timeline both would read 'none' (equal weight) and the consensus would be a flat 0 — so this is the
    # live consequence of the event-timeline wiring.
    from cosmu.mind.authority import authority_weighted_signal

    market = {"BTC": _bars([100 + i for i in range(70)])}
    now = _T0 + timedelta(days=60)
    up_foresight = _claim("@up", "up", ts=_T0 + timedelta(days=35), pid="u")
    down_echo = _claim("@down", "down", ts=_T0 + timedelta(days=50), pid="d")
    events = [
        Event(ts=_T0 + timedelta(days=37), entity="BTC"),  # 2d AFTER @up's claim → @up led it (evidence)
        Event(ts=_T0 + timedelta(days=49), entity="BTC"),  # 1d BEFORE @down's claim → @down reacted (echo)
    ]
    state = compute_authority([up_foresight, down_echo], bars_by_entity=market, events=events, as_of=now)
    lead_lag = {ctx.claim.handle: ctx.lead_lag for ctx in state.contexts}
    assert lead_lag == {"@up": "evidence", "@down": "echo"}
    # Equal authority (no citations), so only the lead-lag weight differs → the foresight UP call dominates.
    sig = authority_weighted_signal(state, "BTC", as_of=now)
    assert sig is not None and sig > 0  # tilts UP: the down ECHO is discounted vs the up FORESIGHT
