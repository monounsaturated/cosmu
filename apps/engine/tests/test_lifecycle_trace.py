# The ADDITIVE lifecycle trace (master/lifecycle + api/routers/readiness): emit_lifecycle_event appends the
# right event kind onto the existing append-only events ledger (and refuses an unknown kind), and the read-only
# readiness endpoint COMPOSES the three existing verdicts (live_eligibility + paper_maturity + current_regime)
# plus the version's ordered audit trace into one view. Offline + deterministic: a temp SQLite store + in-process
# reference bars, no network. These pin that the audit is write-only (never gates/arms) and the read surface can
# never disagree with the live-arming gate (it reuses the same verdict function).

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.config.settings import PAPER_MIN_DAYS, Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lifecycle import (
    LIFECYCLE_KINDS,
    LIFECYCLE_ORDER,
    emit_lifecycle_event,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/lifecycle.sqlite3", openrouter_api_key=None))


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


_UP = _bars([0.01] * 80)  # current regime = bull


def _seed_version(store: Store, vid: str) -> str:
    sid = store.insert("strategies", {"name": f"s-{vid}", "thesis": "t", "origin": "seed", "created_at": utcnow()})
    store.insert(
        "strategy_versions",
        {
            "id": vid, "strategy_id": sid, "parent_id": None, "spec": "{}", "generated_code": "x",
            "code_hash": "h", "params": "{}", "mutation_operator": None, "mutation_rationale": None,
            "origin": "seed", "status": "paper", "created_at": utcnow(), "killed_at": None, "kill_reason": None,
        },
    )
    return sid


def _open_track(store: Store, vid: str, *, age_days: float, net_pct: float, proven: list[str], now: datetime, fills: int = 1) -> None:
    _seed_version(store, vid)
    store.insert(
        "tracks",
        {
            "strategy_version_id": vid, "starting_capital": "100000",
            "equity": str(100000 * (1 + net_pct / 100)), "return_pct": str(net_pct), "updated_at": utcnow(),
        },
    )
    # Forward marked-equity trajectory so the live-arming SIGNIFICANCE gate sees real evidence (the readiness view
    # composes live_eligibility, which now requires a significantly-positive forward Sharpe + real fills).
    from conftest import seed_track_snapshots
    seed_track_snapshots(store, vid, obs=min(int(age_days), 30), now=now)
    origin = now - timedelta(days=age_days)
    ts = origin.isoformat()
    with store.batch() as w:
        w.execute(
            "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) VALUES (?, 'master', 'track_opened', 'strategy_version', ?, ?)",
            (ts, vid, json.dumps({"proven_regimes": proven})),
        )
        # Real forward fills (is_paper=1, after the origin) — live-eligibility requires the track actually traded
        # forward, not just aged + net-positive. Default 1; pass 0 for a never-traded track.
        if fills > 0:
            w.execute(
                "INSERT INTO runs(id, strategy_version_id, mode, venue_id, seed, started_at, status) VALUES (?, ?, 'sandbox', 'binance', 1, ?, 'completed')",
                (f"run-{vid}", vid, ts),
            )
            for i in range(fills):
                w.execute(
                    "INSERT INTO executions(id, run_id, strategy_version_id, instrument_id, venue_id, side, qty, price, fee, slippage, order_type, is_paper, ts, fill_log) "
                    "VALUES (?, ?, ?, 'binance:BTCUSDT', 'binance', 'buy', '1', '100', '0.1', '0', 'market', 1, ?, '{}')",
                    (f"ex-{vid}-{i}", f"run-{vid}", vid, (origin + timedelta(hours=i + 1)).isoformat()),
                )


# --- emit_lifecycle_event ------------------------------------------------------------------------------------


def test_emit_appends_the_right_event_kind(tmp_path):
    store = _store(tmp_path)
    emit_lifecycle_event(store, "v1", "paper_started", {"lane": "exploit"})

    row = store.row("SELECT actor, kind, ref_type, ref_id, payload FROM events WHERE ref_id = 'v1'")
    assert row is not None
    assert row["kind"] == "paper_started"
    assert row["ref_type"] == "strategy_version"
    assert row["actor"] == "master"
    assert json.loads(row["payload"]) == {"lane": "exploit"}


def test_emit_defaults_payload_to_empty(tmp_path):
    store = _store(tmp_path)
    emit_lifecycle_event(store, "v2", "live_armed")
    row = store.row("SELECT payload FROM events WHERE ref_id = 'v2'")
    assert json.loads(row["payload"]) == {}


def test_emit_rejects_unknown_kind(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="unknown lifecycle kind"):
        emit_lifecycle_event(store, "v3", "not_a_real_stage")
    # nothing was written — the closed vocabulary held
    assert store.row("SELECT 1 FROM events WHERE ref_id = 'v3'") is None


def test_every_lifecycle_kind_is_emittable(tmp_path):
    store = _store(tmp_path)
    for kind in LIFECYCLE_KINDS:
        emit_lifecycle_event(store, f"v-{kind}", kind)
        assert store.row("SELECT 1 FROM events WHERE ref_id = ? AND kind = ?", (f"v-{kind}", kind)) is not None
    assert set(LIFECYCLE_KINDS) == set(LIFECYCLE_ORDER)


# --- readiness composition -----------------------------------------------------------------------------------


def test_readiness_composes_the_three_verdicts(tmp_path, monkeypatch):
    # A matured, net-positive, in-proven-regime version → eligible; the readiness view must compose
    # live_eligibility + paper_maturity + current_regime AND surface the lifecycle trace.
    from cosmu.api.routers import readiness as r

    now = datetime(2026, 6, 4, tzinfo=UTC)
    store = _store(tmp_path)
    _open_track(store, "v-ready", age_days=PAPER_MIN_DAYS + 10, net_pct=4.0, proven=["bull"], now=now)
    # Record some lifecycle marks (out of order on purpose; the read must order by stage, not recency).
    emit_lifecycle_event(store, "v-ready", "paper_started", {"lane": "exploit"})
    emit_lifecycle_event(store, "v-ready", "screened_passed", {"lane": "exploit"})
    emit_lifecycle_event(store, "v-ready", "live_armed", {"venue_id": "binance"})

    monkeypatch.setattr(r, "store", store)
    monkeypatch.setattr(r, "_version_reference_bars", lambda _vid: _UP)

    out = r.readiness_detail("v-ready")
    assert out.version_id == "v-ready"
    # composed verdicts agree with the live-arming gate
    assert out.eligible is True
    assert out.live_eligibility.eligible is True
    assert out.live_eligibility.regime_eligible is True
    assert out.live_eligibility.forward_ready is True
    assert out.live_eligibility.proven_regimes == ["bull"]
    assert out.paper_maturity.live_ready is True
    assert out.paper_maturity.min_days == PAPER_MIN_DAYS
    assert out.current_regime.label == "bull"
    # the audit trace is present, ordered by ingest, and the latest STAGE is reported by LIFECYCLE_ORDER
    assert {m.kind for m in out.trace} == {"paper_started", "screened_passed", "live_armed"}
    assert out.stage == "live_armed"


def test_readiness_fails_safe_for_unknown_version(tmp_path, monkeypatch):
    # No track, no marks → the underlying verdicts fail safe (not eligible) and the trace is empty.
    from cosmu.api.routers import readiness as r

    store = _store(tmp_path)
    monkeypatch.setattr(r, "store", store)
    monkeypatch.setattr(r, "_version_reference_bars", lambda _vid: _UP)

    out = r.readiness_detail("ghost")
    assert out.eligible is False
    assert out.live_eligibility.forward_ready is False
    assert out.stage is None
    assert out.trace == []
