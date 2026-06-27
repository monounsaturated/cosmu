# Offline, deterministic tests for the R3 INDEPENDENT REPLICATION COHORT (cosmu.research.replication_cohort) — no
# cache, no network. Two layers:
#   (1) the quorum/drift/exclusion LOGIC, driven by a hand-built FrozenSurvivor whose `replay` returns crafted
#       CellRun objects (full control over which held-out cells replicate); and
#   (2) the equity-TAA (Faber GTAA) ADAPTER, driven by synthetic MonthlySeries injected via the `loader` hook, so
#       the frozen single-asset timing rule is exercised end-to-end without the equities cache.
# We assert the gate is ADDITIVE (it never changes a GateSettings threshold) and FAILS CLOSED (drift / too-few obs).

from __future__ import annotations

import math

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.promotion import params_hash
from cosmu.research import equity_faber_gtaa as gtaa
from cosmu.research import replication_cohort as rc

# The pinned params_hash of the FROZEN Faber survivor ({sma_months:10, fee_bps_per_side:1.0}). If this changes, the
# frozen spec was altered — a deliberate review event, never a silent drift.
FABER_PARAMS_HASH = "7f5abd994340d2ace25cba5716ccb68e1c338f0cd600d188bd9901a03d275042"


# --------------------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------------------


def _cell(*, n=60, net=0.5, net_sr=2.0, net_dd=0.10, bh_sr=0.6, bh_dd=0.50) -> rc.CellRun:
    """A crafted CellRun. Defaults REPLICATE (enough obs, net-positive, beats B&H on both Sharpe and drawdown)."""
    return rc.CellRun(n_obs=n, net_return=net, net_sharpe=net_sr, net_max_dd=net_dd,
                      buy_and_hold_return=0.4, buy_and_hold_sharpe=bh_sr, buy_and_hold_max_dd=bh_dd)


def _survivor(mapping: dict[str, rc.CellRun | None], *, discovery=("SPY", "EFA")) -> rc.FrozenSurvivor:
    """A FrozenSurvivor whose replay returns the crafted CellRun for each held-out symbol (or None)."""
    return rc.FrozenSurvivor(
        id="t", label="test survivor", params={"sma_months": 10.0, "fee_bps_per_side": 1.0},
        discovery_universe=discovery, replay=lambda s: mapping.get(s), venue="equity",
    )


def _series(symbol: str, closes: list[float], start: tuple[int, int] = (2004, 1)) -> gtaa.MonthlySeries:
    months: list[tuple[int, int]] = []
    close: dict[tuple[int, int], float] = {}
    y, m = start
    for c in closes:
        months.append((y, m))
        close[(y, m)] = float(c)
        total = y * 12 + (m - 1) + 1
        y, m = total // 12, total % 12 + 1
    return gtaa.MonthlySeries(symbol, months, close)


def _crash_closes() -> list[float]:
    """40 months up 2% -> 8 months crash -10% -> 36 months recover 2%. A trend-timer sits OUT the crash, so its
    drawdown is materially below buy-and-hold's — the documented Faber edge, on a held-out symbol."""
    c = [100.0]
    for _ in range(40):
        c.append(c[-1] * 1.02)
    for _ in range(8):
        c.append(c[-1] * 0.90)
    for _ in range(36):
        c.append(c[-1] * 1.02)
    return c


def _flat_closes(n: int, rate: float = 0.002) -> list[float]:
    c = [100.0]
    for _ in range(n - 1):
        c.append(c[-1] * (1 + rate))
    return c


def _chop_closes(n: int) -> list[float]:
    """A choppy, slightly-down series — trend-timing whipsaws here (pays fees, mistimes), so the cell does NOT
    replicate (net-negative). This is a held-out symbol where the edge legitimately fails to travel."""
    c = [100.0]
    for i in range(n - 1):
        c.append(c[-1] * (1 + 0.07 * math.sin(i * 1.7) - 0.004))
    return c


def _loader(mapping: dict[str, gtaa.MonthlySeries]):
    def load(symbol: str) -> gtaa.MonthlySeries:
        if symbol in mapping:
            return mapping[symbol]
        raise FileNotFoundError(symbol)
    return load


# --------------------------------------------------------------------------------------------------------------
# (1) quorum / drift / exclusion logic
# --------------------------------------------------------------------------------------------------------------


def test_quorum_met_is_credible():
    survivor = _survivor({"QQQ": _cell(), "IWM": _cell(), "EEM": _cell(net=-0.1)})  # 2 replicate, 1 net-negative
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM", "EEM"], quorum=2)
    assert rep.verdict == "REPLICATED"
    assert rep.credible is True
    assert rep.n_replicated == 2
    assert rep.n_cells == 3
    assert rep.params_hash == params_hash(survivor.params)


def test_quorum_not_met_is_not_credible():
    survivor = _survivor({"QQQ": _cell(), "IWM": _cell(net=-0.1), "EEM": _cell(net=-0.2)})  # only 1 replicates
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM", "EEM"], quorum=2)
    assert rep.verdict == "NOT-REPLICATED"
    assert rep.credible is False
    assert rep.n_replicated == 1


def test_fewer_cells_than_quorum_is_insufficient_data():
    # Two of three held-out symbols have no data -> only 1 cell runs, below the quorum of 2 -> cannot judge.
    survivor = _survivor({"QQQ": _cell(), "IWM": None, "EEM": None})
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM", "EEM"], quorum=2)
    assert rep.verdict == "INSUFFICIENT-DATA"
    assert rep.credible is False
    assert rep.n_cells == 1
    assert any("no held-out data" in n for n in rep.notes)


def test_params_hash_drift_fails_closed():
    survivor = _survivor({"QQQ": _cell(), "IWM": _cell()})
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM"], quorum=2, expected_params_hash="deadbeef")
    assert rep.verdict == "DRIFT"
    assert rep.credible is False
    assert rep.n_cells == 0  # nothing is judged once drift is detected — fail-closed
    assert rep.cells == []


def test_matching_params_hash_proceeds():
    survivor = _survivor({"QQQ": _cell(), "IWM": _cell()})
    expected = params_hash(survivor.params)
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM"], quorum=2, expected_params_hash=expected)
    assert rep.verdict == "REPLICATED"


def test_held_out_overlapping_discovery_is_excluded():
    # SPY is in the discovery universe — it must be dropped from the held-out set (it is not held out), and its
    # replay must never be consulted.
    called: list[str] = []

    def replay(sym: str) -> rc.CellRun | None:
        called.append(sym)
        return _cell()

    survivor = rc.FrozenSurvivor(id="t", label="t", params={"sma_months": 10.0, "fee_bps_per_side": 1.0},
                                 discovery_universe=("SPY", "EFA"), replay=replay, venue="equity")
    rep = rc.run_replication_cohort(survivor, ["SPY", "QQQ", "IWM"], quorum=2)
    assert "SPY" not in rep.held_out
    assert "SPY" not in called  # the excluded discovery symbol is never replayed
    assert set(rep.held_out) == {"QQQ", "IWM"}
    assert any("overlap the discovery universe" in n for n in rep.notes)


# --------------------------------------------------------------------------------------------------------------
# (2) the per-cell replication predicate (the LOCKED additional bar)
# --------------------------------------------------------------------------------------------------------------


def test_cell_predicate_net_negative_never_replicates():
    replicated, _, _ = rc.cell_replicates(_cell(net=-0.01, net_sr=5.0, net_dd=0.0))
    assert replicated is False  # net-negative kills it regardless of Sharpe/DD


def test_cell_predicate_too_short_does_not_vote():
    replicated, _, _ = rc.cell_replicates(_cell(n=rc.MIN_CELL_OBS - 1, net=1.0, net_sr=5.0, net_dd=0.01))
    assert replicated is False  # too few obs -> cannot vote (fail-closed)


def test_cell_predicate_dd_beat_only():
    # Lower Sharpe than B&H but a materially lower drawdown -> still replicates (Faber's documented edge).
    replicated, sharpe_beat, dd_beat = rc.cell_replicates(
        _cell(net=0.2, net_sr=0.30, net_dd=0.10, bh_sr=0.60, bh_dd=0.50)
    )
    assert sharpe_beat is False
    assert dd_beat is True
    assert replicated is True


def test_cell_predicate_sharpe_beat_only():
    # Higher Sharpe than B&H but NOT a materially lower drawdown -> still replicates.
    replicated, sharpe_beat, dd_beat = rc.cell_replicates(
        _cell(net=0.2, net_sr=0.90, net_dd=0.48, bh_sr=0.60, bh_dd=0.50)
    )
    assert sharpe_beat is True
    assert dd_beat is False
    assert replicated is True


def test_too_short_cell_runs_but_does_not_replicate():
    # A short series produces a cell that runs (so it counts toward n_cells) but cannot replicate and is noted.
    survivor = _survivor({"QQQ": _cell(n=rc.MIN_CELL_OBS - 5, net=1.0, net_sr=9.0, net_dd=0.0),
                          "IWM": _cell(), "EEM": _cell()})
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM", "EEM"], quorum=2)
    qqq = next(c for c in rep.cells if c.symbol == "QQQ")
    assert qqq.replicated is False
    assert "cannot vote" in qqq.note


# --------------------------------------------------------------------------------------------------------------
# (3) the equity-TAA (Faber GTAA) frozen adapter
# --------------------------------------------------------------------------------------------------------------


def test_faber_survivor_params_hash_is_pinned():
    s = rc.faber_gtaa_survivor()
    assert s.params == {"sma_months": 10.0, "fee_bps_per_side": 1.0}
    assert params_hash(s.params) == FABER_PARAMS_HASH
    # discovery universe is Faber's canonical sleeves + the cash proxy (held-out must be disjoint from this)
    assert set(s.discovery_universe) == {"SPY", "EFA", "AGG", "GLD", "IEF", "SHY"}


def test_faber_frozen_constants_unchanged():
    # The adapter reuses equity_faber_gtaa's OWN frozen primitives — if these LOCKED constants move, the params
    # hash above moves too (a deliberate review event). This pins "no refit" at the source.
    assert gtaa.SMA_MONTHS == 10
    assert gtaa.IBKR_ETF_BPS_PER_SIDE == 1.0
    assert gtaa.CASH == "SHY"


def test_faber_replay_crash_symbol_replicates():
    cash = _series("SHY", _flat_closes(90))
    asset = _series("QQQ", _crash_closes())
    run = rc._gtaa_replay("QQQ", load=_loader({"QQQ": asset, "SHY": cash}))
    assert run is not None
    assert run.n_obs >= rc.MIN_CELL_OBS
    # the timer sits out the crash -> materially lower drawdown than buy-and-hold the crashing symbol
    assert run.net_max_dd < run.buy_and_hold_max_dd * rc.MATERIAL_DD_REDUCTION
    replicated, _, dd_beat = rc.cell_replicates(run)
    assert dd_beat is True
    assert replicated is True


def test_faber_adapter_end_to_end_quorum():
    cash = _series("SHY", _flat_closes(90))
    held = {"QQQ": _series("QQQ", _crash_closes()), "IWM": _series("IWM", _crash_closes()),
            "EEM": _series("EEM", _chop_closes(90)), "SHY": cash}
    survivor = rc.faber_gtaa_survivor(loader=_loader(held))
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM", "EEM"], quorum=2)
    assert rep.verdict == "REPLICATED"      # QQQ + IWM replicate (crash protection), EEM does not (choppy)
    assert rep.n_replicated == 2
    by = {c.symbol: c for c in rep.cells}
    assert by["QQQ"].replicated and by["IWM"].replicated
    assert not by["EEM"].replicated


def test_faber_adapter_missing_data_is_insufficient():
    # Only the cash proxy loads; every held-out symbol is missing -> honest INSUFFICIENT-DATA, never fabricated.
    survivor = rc.faber_gtaa_survivor(loader=_loader({"SHY": _series("SHY", _flat_closes(90))}))
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM"], quorum=2)
    assert rep.verdict == "INSUFFICIENT-DATA"
    assert rep.n_cells == 0


def test_run_is_deterministic():
    cash = _series("SHY", _flat_closes(90))
    held = {"QQQ": _series("QQQ", _crash_closes()), "IWM": _series("IWM", _crash_closes()), "SHY": cash}
    survivor = rc.faber_gtaa_survivor(loader=_loader(held))
    a = rc.run_replication_cohort(survivor, ["QQQ", "IWM"], quorum=2)
    b = rc.run_replication_cohort(survivor, ["QQQ", "IWM"], quorum=2)
    assert a.verdict == b.verdict
    assert [(c.symbol, c.net_return, c.net_max_dd, c.replicated) for c in a.cells] == \
           [(c.symbol, c.net_return, c.net_max_dd, c.replicated) for c in b.cells]


# --------------------------------------------------------------------------------------------------------------
# (4) durable persistence — operationalize the lane (best-effort, offline-safe)
# --------------------------------------------------------------------------------------------------------------


def test_persist_writes_replication_verdict(tmp_path):
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/r3.sqlite3", openrouter_api_key=None))
    survivor = _survivor({"QQQ": _cell(), "IWM": _cell()})
    rep = rc.run_replication_cohort(survivor, ["QQQ", "IWM"], quorum=2)
    assert rc.persist_replication_verdict(store, rep) is True
    row = store.row("SELECT decision, data_source, payload FROM gate_verdicts ORDER BY ts DESC LIMIT 1")
    assert row is not None
    assert row["decision"] == "REPLICATED"      # the R3 verdict, never the funding 'PASS' -> cannot masquerade
    assert row["data_source"] == "replication"
    import json
    payload = json.loads(row["payload"])
    assert payload["kind"] == "replication"
    assert payload["method"] == rc.METHOD_REPLICATION_COHORT
    assert payload["credible"] is True
    assert payload["n_replicated"] == 2
