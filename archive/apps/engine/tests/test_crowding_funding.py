# Fix 1: the (already-built) cross-cell crowding detector is WIRED into capital allocation. AFTER the per-combo
# gate (which is untouched), the funder clusters fundable cells by realized-return correlation and persists a
# per-cell tracks.exposure_factor that vol-scales DOWN the redundant members of a cluster — so the book can't
# fund N near-identical cells at full exposure. The gate verdict per cell is unchanged; only how much CAPITAL a
# redundant cluster member deploys changes. Generous paper intact: every cell still paper-trades.

from __future__ import annotations

import math
import random

from test_close_loop import _FixtureBars, _persist_survivor, _store

from cosmu.master.crowding import MIN_EXPOSURE, cluster_exposure_factors
from cosmu.orchestrator.loop import _apply_crowding_caps, fund_tracks_from_survivors
from cosmu.portfolio.rotation import Track

# ── the PURE crowding→exposure helper ─────────────────────────────────────────


def _corr_stream(base: list[float], jitter: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [x + rng.gauss(0, jitter) for x in base]


def test_helper_caps_redundant_member_keeps_best_and_decorrelated():
    rng = random.Random(7)
    base = [rng.gauss(0, 0.01) for _ in range(60)]
    a = _corr_stream(base, 0.0003, 1)          # ~identical to base
    b = _corr_stream(base, 0.0003, 2)          # ~identical to base (clusters with a)
    c = [rng.gauss(0, 0.01) for _ in range(60)]  # independent
    factors = cluster_exposure_factors({"a": a, "b": b, "c": c}, {"a": 2.0, "b": 1.0, "c": 1.5})
    assert factors["c"] == 1.0                  # decorrelated cell → full exposure
    assert factors["a"] == 1.0                  # higher rolling_dsr → cluster's kept representative
    assert factors["b"] < 1.0                   # redundant member vol-scaled down
    assert factors["b"] >= MIN_EXPOSURE


def test_helper_is_honest_no_op_below_two_cells_or_no_history():
    assert cluster_exposure_factors({"only": [0.01] * 60}) == {"only": 1.0}          # < 2 cells
    assert cluster_exposure_factors({"a": [], "b": []}) == {"a": 1.0, "b": 1.0}      # no overlap → no cluster


def test_helper_share_is_one_over_cluster_size():
    base = [math.sin(i / 3.0) * 0.01 for i in range(60)]
    streams = {k: _corr_stream(base, 0.0001, i) for i, k in enumerate(["a", "b", "c"])}
    f = cluster_exposure_factors(streams, {"a": 3.0, "b": 2.0, "c": 1.0})
    assert f["a"] == 1.0
    # 3-member cluster → the two non-best members each deploy ~1/3 (clamped above MIN_EXPOSURE).
    assert abs(f["b"] - max(MIN_EXPOSURE, 1 / 3)) < 1e-9
    assert abs(f["c"] - max(MIN_EXPOSURE, 1 / 3)) < 1e-9


# ── funder integration: streams come from cell-keyed scope='track' snapshots ───


def _seed_cell_stream(store, version_id: str, symbol: str, venue: str, equity: list[float]) -> None:
    """Write a cell-keyed scope='track' equity trajectory (ref_id = version:symbol:venue) — the SAME series the
    crowding overlay reads via drift.track_return_series."""
    ref = f"{version_id}:{symbol}:{venue}"
    for i, eq in enumerate(equity):
        store.insert(
            "portfolio_snapshots",
            {"scope": "track", "ref_id": ref, "ts": f"2024-02-{i + 1:02d}T00:00:00Z",
             "equity": str(eq), "cash": str(eq), "positions_value": "0", "pnl": "0", "drawdown": "0"},
        )


def test_funder_caps_correlated_crypto_cells_not_the_gate(tmp_path):
    store = _store(tmp_path)
    # Two SEPARATE versions, each a single crypto cell on Binance — near-identical equity paths (a crowd).
    vid_a = _persist_survivor(store, name="MomoA", asset_classes=["crypto"], venues=["binance"], pass_symbols=["BTCUSDT"])
    vid_b = _persist_survivor(store, name="MomoB", asset_classes=["crypto"], venues=["binance"], pass_symbols=["ETHUSDT"])

    rng = random.Random(3)
    # A steadily-compounding (healthy, non-decaying) but NEAR-IDENTICAL pair: same shape so they cluster, while
    # the upward drift keeps the anticipatory drift monitor from defunding either (the crowding cap, not drift,
    # is under test here).
    base_ret = [0.004 + rng.gauss(0, 0.006) for _ in range(60)]
    def _equity(returns: list[float]) -> list[float]:
        eq, v = [], 10000.0
        for r in returns:
            v *= (1 + r)
            eq.append(v)
        return eq
    a_ret = base_ret
    b_ret = [r + rng.gauss(0, 0.0002) for r in base_ret]  # ~identical → clusters with A
    _seed_cell_stream(store, vid_a, "BTCUSDT", "binance", _equity(a_ret))
    _seed_cell_stream(store, vid_b, "ETHUSDT", "binance", _equity(b_ret))

    funding = fund_tracks_from_survivors(store, market_data=_FixtureBars())
    # The crowding cap fired regardless of the funding/drift decision (it runs over ALL fundable cells before the
    # register loop): exactly one redundant cluster member was vol-scaled down. GATE UNTOUCHED — both cells were
    # counted as survivors (the per-combo verdict is unchanged); the cap only changes how much capital deploys.
    assert funding.survivors == 2
    assert funding.crowding_capped == 1                    # exactly one redundant member vol-scaled down

    factors = {
        (r["strategy_version_id"], r["symbol"]): r["exposure_factor"]
        for r in store.rows("SELECT strategy_version_id, symbol, exposure_factor FROM tracks")
    }
    capped = [v for v in factors.values() if v is not None and float(v) < 1.0]
    full = [v for v in factors.values() if v is None or float(v) >= 1.0]
    assert len(capped) == 1 and len(full) == 1  # one capped, one (the best rep) at full exposure


def test_funder_no_cap_for_decorrelated_cells(tmp_path):
    store = _store(tmp_path)
    vid_a = _persist_survivor(store, name="IndepA", asset_classes=["crypto"], venues=["binance"], pass_symbols=["BTCUSDT"])
    vid_b = _persist_survivor(store, name="IndepB", asset_classes=["crypto"], venues=["binance"], pass_symbols=["ETHUSDT"])

    def _equity(seed: int) -> list[float]:
        r = random.Random(seed)
        eq, v = [], 10000.0
        for _ in range(60):
            v *= (1 + r.gauss(0.001, 0.012))
            eq.append(v)
        return eq
    _seed_cell_stream(store, vid_a, "BTCUSDT", "binance", _equity(1))
    _seed_cell_stream(store, vid_b, "ETHUSDT", "binance", _equity(999))  # independent path

    funding = fund_tracks_from_survivors(store, market_data=_FixtureBars())
    assert funding.crowding_capped == 0  # decorrelated → no cap (honest no-op)
    for r in store.rows("SELECT exposure_factor FROM tracks"):
        assert r["exposure_factor"] is None or float(r["exposure_factor"]) == 1.0


def test_apply_crowding_caps_is_no_op_with_single_cell(tmp_path):
    store = _store(tmp_path)
    vid = _persist_survivor(
        store, name="Solo", asset_classes=["crypto"], venues=["binance"], pass_symbols=["BTCUSDT"]
    )
    cell = (vid, Track(id=f"{vid}:BTCUSDT:binance", rolling_dsr=1.0), "BTCUSDT", "binance")
    assert _apply_crowding_caps(store, [cell]) == 0  # < 2 cells → hard no-op
