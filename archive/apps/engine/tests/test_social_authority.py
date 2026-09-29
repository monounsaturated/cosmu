# Offline tests for Phase 3 social authority (cosmu.mind.authority). NO LLM, no network: canned claims + bars +
# posts + events. Asserts: primacy (who-first), lead-lag (evidence vs echo), personalized PageRank anchored to the
# deterministic track record (influence != authority), the per-entity authority-weighted signal, point-in-time
# history with no look-ahead, the registered feature(s), and a profile-source GO on the backfilled PIT series.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.feature_registry import AUTHORITY_TRANSFORM_VERSION, feature_names, features_for
from cosmu.data.altdata import AltDataStore
from cosmu.data.market import Bar
from cosmu.ingest.profile_source import profile_source
from cosmu.mind.authority import (
    AUTHORITY_VERSION,
    AuthorityProvider,
    Event,
    authority_weighted_signal,
    build_citation_edges,
    classify_lead_lag,
    compute_authority,
    personalized_pagerank,
    signal_history,
)
from cosmu.mind.claims import Claim, VoicePost, horizon_to_days

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(closes: list[float], *, start: datetime = _T0, step_days: int = 1) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(Bar(ts=start + timedelta(days=i * step_days), open=d, high=d, low=d, close=d, volume=Decimal(0)))
    return out


def _claim(handle, direction, *, entity="BTC", horizon="3d", ts=_T0, conviction=0.8, pid="p") -> Claim:
    return Claim(
        handle=handle, platform="x", post_id=pid, entity=entity, direction=direction,
        horizon=horizon, horizon_days=horizon_to_days(horizon), conviction=conviction, ts=ts,
    )


# --------------------------------------------------------------------------- primacy + lead-lag


def test_primacy_marks_first_caller_and_echoes():
    claims = [
        _claim("@first", "up", ts=_T0, pid="a"),
        _claim("@echo", "up", ts=_T0 + timedelta(days=1), pid="b"),     # within 7d window → echo
        _claim("@late", "up", ts=_T0 + timedelta(days=20), pid="c"),    # beyond window → new primary
    ]
    state = compute_authority(claims, bars_by_entity={"BTC": _bars([100] * 30)}, as_of=_T0 + timedelta(days=40))
    flags = {ctx.claim.handle: ctx.is_primary for ctx in state.contexts}
    assert flags["@first"] is True and flags["@echo"] is False and flags["@late"] is True


def test_lead_lag_evidence_vs_echo():
    c = _claim("@vox", "up", ts=_T0)
    after = [Event(ts=_T0 + timedelta(days=2), entity="BTC")]   # event AFTER claim → claim led it → evidence
    before = [Event(ts=_T0 - timedelta(days=1), entity="BTC")]  # event BEFORE claim → claim echoed it
    assert classify_lead_lag(c, after) == "evidence"
    assert classify_lead_lag(c, before) == "echo"
    assert classify_lead_lag(c, [Event(ts=_T0 + timedelta(days=99), entity="BTC")]) == "none"
    assert classify_lead_lag(c, [Event(ts=_T0 + timedelta(days=2), entity="ETH")]) == "none"  # other entity


# --------------------------------------------------------------------------- citation graph + PageRank


def test_build_citation_edges_resolves_refs_to_handles():
    posts = [
        VoicePost(handle="@a", platform="x", post_id="1", text="", ts=_T0),
        VoicePost(handle="@b", platform="x", post_id="2", text="", ts=_T0, refs=("1",)),   # b cites a
        VoicePost(handle="@a", platform="x", post_id="3", text="", ts=_T0, refs=("3",)),   # self-cite dropped
    ]
    assert build_citation_edges(posts) == [("@b", "@a")]


def test_pagerank_anchored_to_skill_influence_is_not_authority():
    # @loud is cited heavily by zero-skill noise accounts; @quiet has high personalization (proven skill) and no
    # citations. Authority must favour @quiet — being loud (well-cited by noise) is not authority.
    nodes = ["@quiet", "@loud", "@n1", "@n2", "@n3"]
    edges = [("@n1", "@loud"), ("@n2", "@loud"), ("@n3", "@loud")]  # @loud is influential (3 inbound)
    skill = {"@quiet": 1.0, "@loud": 0.0, "@n1": 0.0, "@n2": 0.0, "@n3": 0.0}
    pr = personalized_pagerank(nodes, edges, skill)
    assert pr["@quiet"] > pr["@loud"]            # authority (skill-anchored) beats raw influence
    assert abs(sum(pr.values()) - 1.0) < 1e-9    # a proper distribution


def test_pagerank_uniform_when_no_skill_anywhere():
    pr = personalized_pagerank(["@a", "@b"], [], {})
    assert abs(pr["@a"] - 0.5) < 1e-9 and abs(pr["@b"] - 0.5) < 1e-9


# --------------------------------------------------------------------------- authority-weighted signal


def test_signal_weights_by_authority_and_direction():
    # A skilled voice (built via a beating-base-rate track record) calls UP; a zero-skill voice calls DOWN. The
    # signal should lean positive (the credible voice dominates).
    market = _bars([100, 101, 102, 90, 91, 92, 103, 104, 80, 81, 82] + [83 + i for i in range(30)])
    bars = {"BTC": market}
    now = market[-1].ts + timedelta(days=1)
    claims = [
        # skilled: two down-calls that beat the base rate, earning skill → authority
        _claim("@skilled", "down", ts=market[2].ts, pid="s1"),
        _claim("@skilled", "down", ts=market[7].ts, pid="s2"),
        # then the skilled voice calls DOWN recently, a noise account calls UP recently
        _claim("@skilled", "down", ts=market[-2].ts, conviction=0.9, pid="s3"),
        _claim("@noise", "up", ts=market[-2].ts, conviction=0.9, pid="n1"),
    ]
    state = compute_authority(claims, bars_by_entity=bars, as_of=now)
    sig = authority_weighted_signal(state, "BTC", as_of=now)
    assert sig is not None and sig < 0  # the credible (skilled) DOWN call dominates the noise UP call


def test_signal_abstains_when_no_active_claim():
    state = compute_authority([], bars_by_entity={}, as_of=_T0)
    assert authority_weighted_signal(state, "BTC", as_of=_T0) is None


# --------------------------------------------------------------------------- point-in-time history + provider


def test_history_is_point_in_time_no_lookahead():
    market = _bars([100 + i for i in range(120)])
    claims = [_claim("@a", "up", ts=_T0 + timedelta(days=i), conviction=0.7, pid=f"p{i}") for i in range(90)]
    hist = signal_history(
        claims, bars_by_entity={"BTC": market}, entity="BTC",
        start=_T0, end=_T0 + timedelta(days=100),
    )
    assert len(hist) > 60
    for pt in hist:
        assert pt.available_at == pt.ts          # availability == observation, never earlier
        assert pt.available_at >= pt.ts          # no look-ahead


def test_provider_honest_degradation_without_claims():
    prov = AuthorityProvider(claims=[], bars_by_entity={}, now=_T0)
    assert prov.fetch_series("BTC", "authority_weighted_claim_signal", limit=1) == []


def test_provider_emits_point_for_known_metrics():
    market = _bars([100 + i for i in range(60)])
    claims = [_claim("@a", "up", ts=_T0 + timedelta(days=i), pid=f"p{i}") for i in range(40)]
    now = _T0 + timedelta(days=55)
    prov = AuthorityProvider(claims=claims, bars_by_entity={"BTC": market}, now=now)
    pts = prov.fetch_series("BTC", "authority_weighted_claim_signal", limit=1)
    assert len(pts) == 1 and pts[0].available_at == now
    assert prov.fetch_series("BTC", "unknown_metric", limit=1) == []


# --------------------------------------------------------------------------- registered feature + profile-source GO


def test_features_registered_tier1():
    names = feature_names()
    assert "authority_weighted_claim_signal" in names
    assert "author_authority" in names
    feats = {f.name: f for f in features_for(["crypto"])}
    sig = feats["authority_weighted_claim_signal"]
    assert sig.tier == "tier1"                                   # must earn its place OOS
    assert sig.transform_version == AUTHORITY_TRANSFORM_VERSION
    assert AUTHORITY_VERSION == AUTHORITY_TRANSFORM_VERSION      # the pin matches the code's version
    assert "must earn" in sig.prior.lower()


def test_profile_source_go_on_backfilled_pit_history(tmp_path):
    # Backfill a deep, dense, fresh PIT series for the new source, then run the data-trust audit → it must be GO.
    market = _bars([100 + (i % 7) for i in range(200)])          # mild chop so the signal varies
    # ~daily claims for 120 days so every daily snapshot has an active claim (a dense, gapless series).
    claims = []
    for i in range(120):
        d = "up" if i % 3 else "down"
        claims.append(_claim("@a", d, ts=_T0 + timedelta(days=i), conviction=0.7, pid=f"a{i}"))
        claims.append(_claim("@b", "up", ts=_T0 + timedelta(days=i), conviction=0.6, pid=f"b{i}"))
    end = _T0 + timedelta(days=119)
    hist = signal_history(claims, bars_by_entity={"BTC": market}, entity="BTC", start=_T0, end=end)
    assert len(hist) >= 60

    store = AltDataStore(tmp_path / "alt")
    store.append("social_authority", "BTC", "authority_weighted_claim_signal", hist)

    # `now` just after the last point so the freshest reading is not stale. availability == observation, so there
    # is no declared release lag to check (the PIT-lag check is informational here).
    now = end + timedelta(hours=1)
    profile = profile_source(store, "social_authority", "BTC", "authority_weighted_claim_signal", now=now)
    assert profile.verdict == "GO", profile.to_text()
    assert profile.coverage.lookahead_violations == 0
