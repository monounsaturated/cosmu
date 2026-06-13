# The HARD live-eligibility gate (master/live_eligibility.live_eligibility_verdict): a strategy may be ARMED only
# when it has BOTH (a) >= PAPER_MIN_DAYS of net-positive FORWARD evidence AND (b) the current regime is one
# it proved in. This is the precondition that gates what CAN be armed (a human still makes the final launch click).
# These tests pin: a too-young track is NOT eligible; a matured net-positive one IS; underwater/out-of-regime fail
# safe; and the human `override` waives ONLY the paper precondition (never the regime gate), flagged
# `overridden`. Deterministic, LLM-free.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import PAPER_MIN_DAYS, Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.live_eligibility import (
    forward_evidence,
    live_eligibility_verdict,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/elig.sqlite3", openrouter_api_key=None))


def _bars(returns: list[float]) -> list[Bar]:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    price = 100.0
    out: list[Bar] = []
    for i, r in enumerate(returns):
        open_ = price
        price = max(0.01, price * (1 + r))
        out.append(
            Bar(
                ts=start + timedelta(days=i),
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(max(open_, price) * 1.01, 6))),
                low=Decimal(str(round(min(open_, price) * 0.99, 6))),
                close=Decimal(str(round(price, 6))),
                volume=Decimal("1000000"),
            )
        )
    return out


_UP = _bars([0.01] * 80)     # current regime = bull
_DOWN = _bars([-0.01] * 80)   # current regime = bear


def _seed_version(store: Store, vid: str) -> None:
    """Minimal strategies + strategy_versions rows so a tracks row (FK -> strategy_versions) can be opened."""
    sid = store.insert("strategies", {"name": f"s-{vid}", "thesis": "t", "origin": "seed", "created_at": utcnow()})
    store.insert(
        "strategy_versions",
        {
            "id": vid, "strategy_id": sid, "parent_id": None, "spec": "{}", "generated_code": "x",
            "code_hash": "h", "params": "{}", "mutation_operator": None, "mutation_rationale": None,
            "origin": "seed", "status": "paper", "created_at": utcnow(), "killed_at": None, "kill_reason": None,
        },
    )


def _open_track(store: Store, vid: str, *, age_days: float, net_pct: float, proven: list[str], now: datetime) -> None:
    """Open a paper track: a tracks row carrying the net-of-fee return + a track_opened event whose ts is
    the clock origin (backdated `age_days` before `now`) carrying the proven-regime passport."""
    _seed_version(store, vid)
    store.insert(
        "tracks",
        {
            "strategy_version_id": vid, "starting_capital": "100000",
            "equity": str(100000 * (1 + net_pct / 100)), "return_pct": str(net_pct), "updated_at": utcnow(),
        },
    )
    ts = (now - timedelta(days=age_days)).isoformat()
    with store.batch() as w:
        w.execute(
            "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) VALUES (?, 'master', 'track_opened', 'strategy_version', ?, ?)",
            (ts, vid, json.dumps({"proven_regimes": proven})),
        )


def test_too_young_strategy_is_not_eligible(tmp_path):
    # Net-positive AND in a proven regime, but the paper clock has barely started -> NOT armable.
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-young", age_days=2, net_pct=5.0, proven=["bull"], now=now)

    v = live_eligibility_verdict(store, "v-young", _UP, now=now)
    assert v.regime_eligible is True          # regime is fine
    assert v.forward_ready is False            # but it hasn't matured
    assert v.eligible is False                 # so it CANNOT be armed
    assert v.overridden is False
    assert "paper not proven" in v.reason


def test_matured_net_positive_strategy_is_eligible(tmp_path):
    # >= PAPER_MIN_DAYS of net-positive forward evidence + in a proven regime -> armable.
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-ok", age_days=PAPER_MIN_DAYS + 10, net_pct=4.0, proven=["bull"], now=now)

    v = live_eligibility_verdict(store, "v-ok", _UP, now=now)
    assert v.forward_ready is True
    assert v.regime_eligible is True
    assert v.eligible is True
    assert v.overridden is False
    assert v.paper_age_days >= PAPER_MIN_DAYS


def test_threshold_boundary_is_inclusive(tmp_path):
    # Exactly PAPER_MIN_DAYS old counts as matured (>=), so a net-positive track at the boundary is eligible.
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-edge", age_days=PAPER_MIN_DAYS, net_pct=0.5, proven=["bull"], now=now)

    assert live_eligibility_verdict(store, "v-edge", _UP, now=now).eligible is True


def test_matured_but_underwater_is_not_eligible(tmp_path):
    # Old enough, but net-of-fee NEGATIVE -> never armable (an underwater track is no evidence of edge).
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-loss", age_days=PAPER_MIN_DAYS + 10, net_pct=-1.5, proven=["bull"], now=now)

    v = live_eligibility_verdict(store, "v-loss", _UP, now=now)
    assert v.forward_ready is False
    assert v.eligible is False


def test_matured_out_of_regime_is_blocked(tmp_path):
    # Forward-proven, but the CURRENT regime (bear) is not one it proved in -> regime gate blocks regardless.
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-rg", age_days=PAPER_MIN_DAYS + 10, net_pct=4.0, proven=["bull"], now=now)

    v = live_eligibility_verdict(store, "v-rg", _DOWN, now=now)
    assert v.forward_ready is True
    assert v.regime_eligible is False
    assert v.eligible is False
    assert "not in proven set" in v.reason


def test_override_waives_paper_only(tmp_path):
    # The human escape hatch: override-launch an UNPROVEN strategy. It waives the paper precondition and is
    # flagged `overridden` (the caller logs the warning) — but it NEVER waives the regime gate.
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-young", age_days=1, net_pct=5.0, proven=["bull"], now=now)

    # In-regime + override -> eligible, and clearly marked as an override of an unproven strategy.
    ov = live_eligibility_verdict(store, "v-young", _UP, override=True, now=now)
    assert ov.forward_ready is False
    assert ov.eligible is True
    assert ov.overridden is True
    assert "OVERRIDE" in ov.reason

    # Out-of-regime + override -> still blocked (override never bypasses the regime gate).
    oob = live_eligibility_verdict(store, "v-young", _DOWN, override=True, now=now)
    assert oob.eligible is False
    assert oob.overridden is False


def test_unknown_version_fails_safe(tmp_path):
    # No track, no passport -> age 0, empty proven set -> never eligible (fail-safe), even with override.
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)

    v = live_eligibility_verdict(store, "ghost", _UP, now=now)
    assert v.forward_ready is False
    assert v.regime_eligible is False
    assert v.eligible is False
    assert live_eligibility_verdict(store, "ghost", _UP, override=True, now=now).eligible is False


def test_forward_evidence_reads_track_and_clock(tmp_path):
    # The forward evidence = (clock origin from the FIRST track_opened event, net return from the track row).
    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-e", age_days=12, net_pct=2.5, proven=["bull"], now=now)

    ev = forward_evidence(store, "v-e", now=now)
    assert round(ev.paper_age_days) == 12
    assert ev.net_return_pct == 2.5
    assert ev.min_days == PAPER_MIN_DAYS
