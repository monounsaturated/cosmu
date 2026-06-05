# Offline tests for Phase 2 deterministic outcome resolution (cosmu.mind.outcomes). NO LLM, no network: canned
# OHLC bars + canned claims. Asserts: point-in-time entry/exit, hit/miss classification, base-rate measurement,
# pending vs no_data, de-dupe, per-author Brier/calibration, and the key invariant — a SPAMMER who only reproduces
# the base rate scores ~0 while a calibrated sniper scores high (influence ≠ authority).

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.mind.claims import Claim, horizon_to_days
from cosmu.mind.outcomes import (
    resolve_claim,
    resolve_claims,
    score_author,
    score_authors,
)

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(closes: list[float], *, start: datetime = _T0, step_days: int = 1) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(Bar(ts=start + timedelta(days=i * step_days), open=d, high=d, low=d, close=d, volume=Decimal(0)))
    return out


def _claim(direction: str, horizon: str, *, handle="@a", entity="BTC", ts: datetime = _T0, conviction=0.8, pid="p") -> Claim:
    return Claim(
        handle=handle, platform="x", post_id=pid, entity=entity, direction=direction,
        horizon=horizon, horizon_days=horizon_to_days(horizon), conviction=conviction, ts=ts,
    )


def test_up_claim_hits_when_price_rises_over_horizon():
    bars = _bars([100, 101, 102, 110, 111])  # +10% by day 3
    claim = _claim("up", "3d", ts=_T0)
    r = resolve_claim(claim, bars, now=_T0 + timedelta(days=10))
    assert r.status == "resolved"
    assert r.entry_price == 100.0 and r.exit_price == 110.0
    assert abs(r.realized_return - 0.10) < 1e-9
    assert r.hit is True


def test_up_claim_misses_when_price_falls():
    bars = _bars([100, 99, 98, 90, 89])
    r = resolve_claim(_claim("up", "3d"), bars, now=_T0 + timedelta(days=10))
    assert r.status == "resolved" and r.hit is False


def test_flat_band_classifies_small_moves_as_flat():
    bars = _bars([100, 100.2, 100.3, 100.4])  # +0.4% < 1% band → flat
    assert resolve_claim(_claim("flat", "3d"), bars, now=_T0 + timedelta(days=10)).hit is True
    assert resolve_claim(_claim("up", "3d"), bars, now=_T0 + timedelta(days=10)).hit is False


def test_entry_is_point_in_time_last_bar_at_or_before_claim():
    bars = _bars([100, 200, 300, 400])  # daily
    # claim made on day 1 (close 200) — entry must be 200 (knowable then), never the day-0 or a future bar.
    r = resolve_claim(_claim("up", "1d", ts=_T0 + timedelta(days=1)), bars, now=_T0 + timedelta(days=10))
    assert r.entry_price == 200.0 and r.exit_price == 300.0


def test_pending_when_horizon_extends_past_now():
    bars = _bars([100, 101, 102])  # only 3 days of data
    # a 3d-horizon claim on the last bar can't resolve — exit lands past what we hold → pending, NOT a miss.
    r = resolve_claim(_claim("up", "1m", ts=_T0), bars, now=_T0 + timedelta(days=2))
    assert r.status == "pending" and r.hit is None


def test_no_data_when_no_bar_before_claim():
    bars = _bars([100, 101], start=_T0 + timedelta(days=5))
    r = resolve_claim(_claim("up", "1d", ts=_T0), bars, now=_T0 + timedelta(days=30))
    assert r.status == "no_data"


def test_resolve_claims_uses_per_entity_bars_and_flags_missing():
    bars = {"BTC": _bars([100, 110, 120])}
    claims = [_claim("up", "1d", entity="BTC"), _claim("up", "1d", entity="ETH")]
    out = resolve_claims(claims, bars, now=_T0 + timedelta(days=10))
    statuses = {r.claim.entity: r.status for r in out}
    assert statuses["BTC"] == "resolved"
    assert statuses["ETH"] == "no_data"  # named, never silently dropped


def test_dedupe_collapses_identical_repeated_claims():
    bars = {"BTC": _bars([100, 110, 120])}
    dupes = [_claim("up", "1d", ts=_T0, pid=f"p{i}") for i in range(50)]  # same bet, 50x (post_id differs)
    out = resolve_claims(dupes, bars, now=_T0 + timedelta(days=10))
    assert len(out) == 1  # raw volume cannot inflate the record


def _rising_market(n: int = 120) -> list[Bar]:
    # A steadily-rising tape: 'up' base rate is high. A spammer shouting 'up' will hit ~base rate → no skill.
    return _bars([100 * (1.01 ** i) for i in range(n)])


def test_spammer_at_base_rate_scores_near_zero_but_sniper_scores_high():
    market = _rising_market(120)
    bars = {"BTC": market}
    now = market[-1].ts + timedelta(days=1)

    # SPAMMER: fires 'up' on 60 distinct days in a rising market — almost always "right", but only at the base
    # rate. No excess skill → Brier Skill Score ~ 0 → skill ~ 0.
    spam = [_claim("up", "3d", handle="@spammer", ts=market[i].ts, conviction=0.9, pid=f"s{i}") for i in range(60)]
    # SNIPER: a handful of well-timed DOWN calls right before the only pullbacks we engineer below.
    sniper_market = _bars(
        [100, 101, 102, 90, 91, 92, 103, 104, 80, 81, 82, 105] + [105 + i for i in range(40)]
    )
    bars2 = {"BTC": sniper_market}
    now2 = sniper_market[-1].ts + timedelta(days=1)
    sniper = [
        _claim("down", "3d", handle="@sniper", ts=sniper_market[2].ts, conviction=0.9, pid="d1"),  # 102 -> 90
        _claim("down", "3d", handle="@sniper", ts=sniper_market[7].ts, conviction=0.9, pid="d2"),  # 104 -> 80
    ]

    spam_rec = score_authors(resolve_claims(spam, bars, now=now))["@spammer"]
    sniper_resolved = resolve_claims(sniper, bars2, now=now2)
    sniper_rec = score_author("@sniper", sniper_resolved)

    # The spammer is loud and often "right" in absolute terms, but earns ~no skill (base-rate only).
    assert spam_rec.hit_rate > 0.5            # loud + often correct in absolute terms
    assert spam_rec.skill < 0.1               # ...but ~no authority (influence != authority)
    # The sniper beats the base rate (called moves the market did NOT usually make) → real skill.
    assert sniper_rec.hit_rate == 1.0
    assert sniper_rec.brier_skill_score > 0
    assert sniper_rec.skill > spam_rec.skill


def test_empty_author_record_is_honest_zero():
    rec = score_author("@nobody", [])
    assert rec.n_resolved == 0 and rec.skill == 0.0 and rec.brier == 0.0


def test_calibration_error_zero_when_confidence_matches_realized():
    # Two calls, forecast prob 0.95 (conviction 0.9), both hit → realized 1.0; |0.95 - 1.0| small, well-calibrated.
    bars = {"BTC": _bars([100, 110, 120, 130])}
    claims = [
        _claim("up", "1d", ts=_T0, conviction=0.9, pid="a"),
        _claim("up", "1d", ts=_T0 + timedelta(days=1), conviction=0.9, pid="b"),
    ]
    rec = score_author("@a", resolve_claims(claims, bars, now=_T0 + timedelta(days=10)))
    assert rec.calibration_error <= 0.06  # 0.95 vs realized 1.0
