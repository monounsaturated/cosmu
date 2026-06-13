# Deterministic offline tests for the PERP-MOMENTUM-NEUTRAL DEPLOY LANE — the real-but-underpowered lead routed to the
# deployment bar (positive-OOS net of REAL perp fees + funding + beats the cash hurdle), NOT the 0.95 in-sample Gate.
# Proves:
#   (1) perp_market_neutral.validate() returns the taa.validate()-style deploy dict on a real cross-sectional trend
#       fixture and clears the deployment bar (the headline ask: does it clear on the test fixture);
#   (2) thin / no data -> NOT deployable (honest abstention, never a fabricated pass);
#   (3) the deploy bar is HONEST: a no-edge (random-walk-ish flat) cross-section does NOT clear it;
#   (4) the current (long, short) signal is PIT, dollar-balanced, and non-overlapping;
#   (5) the arm registers the SAME control-plane rows the finder writes (strategy/version/backtest/track/event),
#       routes via lane_router on lane="deploy", seeds the track equity from the REAL validated net stream, is
#       idempotent (never double-opens / never resets the clock), and aborts cleanly when not deployable;
#   (6) the arm holds NO real catalog positions (it is a return-stream track) and names a short-capable LIVE venue.
# NO network, NO live keys — the conftest socket guard fails any accidental real socket.

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.knowledge.store import Store
from cosmu.research import perp_market_neutral as pmn
from cosmu.research import perp_market_neutral_arm as arm


# --------------------------------------------------------------------------- deterministic offline fixtures


def _bars(closes: list[float], *, start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2023, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, c in enumerate(closes):
        d = Decimal(str(round(c, 6)))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


def _trending_market(n: int = 320, n_sym: int = 10) -> dict[str, list[Bar]]:
    """A deterministic cross-section with DISTINCT, persistent trends (some up, some down) so a real cross-sectional
    momentum edge exists for the L/S-neutral book to harvest. Byte-reproducible (no randomness)."""
    market: dict[str, list[Bar]] = {}
    for j in range(n_sym):
        rate = 1.0 + (j - n_sym / 2) * 0.0015
        market[f"SYM{j}USDT"] = _bars([100.0 * (rate ** i) for i in range(n)])
    return market


def _flat_market(n: int = 320, n_sym: int = 10) -> dict[str, list[Bar]]:
    """A deterministic NO-EDGE cross-section: every symbol oscillates around a flat level with a sign that flips each
    period, so trailing momentum has no persistence — the honest disconfirmer for the deploy bar."""
    market: dict[str, list[Bar]] = {}
    for j in range(n_sym):
        closes = [100.0 * (1.0 + (0.01 if (i + j) % 2 == 0 else -0.01)) for i in range(n)]
        market[f"SYM{j}USDT"] = _bars(closes)
    return market


class _SyntheticFunding:
    """Deterministic funding provider, rate monotone in symbol index (one settlement per daily bar)."""

    def __init__(self, market: dict[str, list[Bar]]) -> None:
        self._by: dict[str, list[AltDataPoint]] = {}
        for j, (sym, bars) in enumerate(sorted(market.items())):
            rate = 0.0001 * (j - len(market) / 2)
            self._by[sym] = [AltDataPoint(ts=b.ts, available_at=b.ts, value=rate) for b in bars]

    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        if metric != "funding_rate":
            return []
        return self._by.get(symbol, [])[-limit:]


def _store(name: str = "perpmn-deploy") -> Store:
    tmp = tempfile.mkdtemp(prefix=f"cosmu-{name}-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))


# --------------------------------------------------------------------------- (1) validate() deploy contract


def test_validate_returns_deploy_dict_and_clears_bar_on_trending_fixture():
    market = _trending_market(n=320, n_sym=10)
    funding = _SyntheticFunding(market)
    v = pmn.validate(market, funding, timeframe="1d", rebalance=pmn.DEPLOY_REBALANCE)
    # the taa.validate()-style contract
    for key in ("deployable", "current_signal", "full", "in_sample", "holdout", "holdout_dsr", "window",
                "n_periods", "n_symbols", "venue_note", "result"):
        assert key in v, f"deploy dict missing {key}"
    assert isinstance(v["full"], pmn.PerpPerfStats)
    assert v["n_periods"] >= pmn.DEPLOY_MIN_PERIODS
    # the finer rebalance gives MORE non-overlapping periods than the 7-day cohort grid (the whole point)
    assert v["n_periods"] > 16
    # the headline ask: a real cross-sectional momentum edge clears the deployment bar on the fixture
    assert v["deployable"] is True
    assert v["holdout_positive"] and v["beats_cash"] and v["robust"]


def test_validate_loads_real_data_when_not_injected(monkeypatch):
    """validate() with no injected market/funding pulls from the cache/store seam (load_perp_market + _funding_provider)
    — patched here to the deterministic fixture so the test stays offline + deterministic."""
    market = _trending_market(n=300, n_sym=8)
    funding = _SyntheticFunding(market)
    monkeypatch.setattr(pmn, "load_perp_market", lambda: market)
    monkeypatch.setattr(pmn, "_funding_provider", lambda: funding)
    v = pmn.validate()
    assert v["deployable"] is True
    assert v["n_symbols"] == 8


# --------------------------------------------------------------------------- (2) honest abstention on thin/no data


def test_validate_abstains_on_thin_cross_section():
    market = _trending_market(n=320, n_sym=pmn.MIN_NAMES - 1)  # below MIN_NAMES
    v = pmn.validate(market, _SyntheticFunding(market))
    assert v["deployable"] is False
    assert "full" not in v  # short-circuited before computing stats


def test_validate_abstains_on_no_data():
    v = pmn.validate({}, _SyntheticFunding({}))
    assert v["deployable"] is False


def test_validate_abstains_on_too_few_periods():
    # enough symbols but too short a history for DEPLOY_MIN_PERIODS invested rebalances at the finer grid
    market = _trending_market(n=40, n_sym=8)
    v = pmn.validate(market, _SyntheticFunding(market))
    assert v["deployable"] is False
    assert v["reason"].startswith("too few invested rebalances")


# --------------------------------------------------------------------------- (3) the deploy bar is honest


def test_no_edge_cross_section_does_not_clear_deploy_bar():
    market = _flat_market(n=320, n_sym=10)
    v = pmn.validate(market, _SyntheticFunding(market))
    # a no-persistence cross-section must NOT clear the deployment bar (honesty disconfirmer)
    assert v["deployable"] is False


# --------------------------------------------------------------------------- (4) current signal is PIT + balanced


def test_current_signal_is_balanced_and_non_overlapping():
    market = _trending_market(n=320, n_sym=12)
    v = pmn.validate(market, _SyntheticFunding(market))
    cs = v["current_signal"]
    longs, shorts = cs["long"], cs["short"]
    assert longs and shorts
    assert len(longs) == len(shorts)  # dollar-balanced legs (equal name count per leg)
    assert set(longs).isdisjoint(set(shorts))  # a name is never both long and short
    # determinism: same fixture -> same current book
    v2 = pmn.validate(market, _SyntheticFunding(market))
    assert v2["current_signal"] == cs


# --------------------------------------------------------------------------- (5) the arm: control-plane + idempotency


def _arm_with(monkeypatch, store, *, deployable: bool, n: int = 80):
    """Patch pmn.validate to a deterministic deploy verdict so the arm test never touches the cache/network."""
    res = pmn.StratResult(net=[0.002] * n, gross=[0.0025] * n, turnover=[0.5] * n,
                          times=[datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)])
    full = pmn.PerpPerfStats(n, 0.18, 1.9, 0.06, 0.58, 0.5)
    ins = pmn.PerpPerfStats(int(n * 0.8), 0.14, 1.8, 0.05, 0.57, 0.5)
    out = pmn.PerpPerfStats(int(n * 0.2), 0.04, 1.2, 0.03, 0.56, 0.5)
    v = {
        "deployable": deployable, "holdout_positive": deployable, "beats_cash": deployable, "robust": deployable,
        "current_signal": {"long": ["SYM9USDT", "SYM8USDT"], "short": ["SYM0USDT", "SYM1USDT"]},
        "full": full, "in_sample": ins, "holdout": out, "holdout_dsr": 0.28 if deployable else -0.1,
        "window": ("2023-01-01", "2023-09-01"), "n_periods": n, "n_symbols": 10,
        "fee_per_side": pmn.PERP_FEE_PER_SIDE,
        "venue_note": "market-neutral SIM track; LIVE needs a short-capable perp venue (Kraken Futures / IBKR / Hyperliquid)",
        "result": res, "reason": "" if deployable else "not deployable",
    }
    monkeypatch.setattr(pmn, "validate", lambda *a, **k: v)
    return v


def test_arm_registers_control_plane_rows_and_seeds_track(monkeypatch):
    store = _store("arm")
    _arm_with(monkeypatch, store, deployable=True, n=80)
    result = arm.arm(store)
    assert result["armed"] is True
    vid = result["version_id"]

    # SAME rows the finder writes
    assert store.row("SELECT 1 FROM strategies WHERE name=?", (arm.STRATEGY_NAME,)) is not None
    sv = store.row("SELECT status, origin, spec FROM strategy_versions WHERE id=?", (vid,))
    assert sv["status"] == "paper" and sv["origin"] == "documented"
    assert store.row("SELECT 1 FROM backtests WHERE strategy_version_id=? AND kind='screen'", (vid,)) is not None
    track = store.row("SELECT equity, return_pct FROM tracks WHERE strategy_version_id=?", (vid,))
    assert track is not None
    # the seeded equity is the compounded net stream on the track capital (>0% on a positive book)
    assert Decimal(str(track["return_pct"])) > 0
    # the per-track trajectory was seeded from the validated net stream
    snaps = store.rows("SELECT 1 FROM portfolio_snapshots WHERE scope='track' AND ref_id=?", (vid,))
    assert len(snaps) == 80
    # track_opened (forward-clock origin) exists, names the short-capable LIVE venue
    ev = store.row("SELECT payload FROM events WHERE kind='track_opened' AND ref_id=?", (vid,))
    assert ev is not None
    payload = ev["payload"] if isinstance(ev["payload"], dict) else __import__("json").loads(ev["payload"])
    assert "short-capable" in payload["live_requires"].lower()


def test_arm_lane_is_deploy(monkeypatch):
    store = _store("arm-lane")
    _arm_with(monkeypatch, store, deployable=True, n=80)
    result = arm.arm(store)
    spec = store.row("SELECT spec FROM strategy_versions WHERE id=?", (result["version_id"],))["spec"]
    spec = spec if isinstance(spec, dict) else __import__("json").loads(spec)
    assert spec["lane"] == "deploy", "the perp book must route through the deploy lane, not the 0.95 gate"
    assert arm._routing_spec().lane == "deploy"
    assert spec["universe"]["venues"] == ["kraken_futures"]  # a short-capable perp venue


def test_arm_holds_no_real_catalog_positions(monkeypatch):
    """The book is a RETURN-STREAM track — it must not open fabricated per-leg catalog positions (most PERP_UNIVERSE
    symbols are not catalog instruments and the book is market-neutral, so there is no single directional hold)."""
    store = _store("arm-nopos")
    _arm_with(monkeypatch, store, deployable=True, n=80)
    vid = arm.arm(store)["version_id"]
    positions = store.rows("SELECT 1 FROM positions WHERE strategy_version_id=?", (vid,))
    assert positions == []


def test_arm_is_idempotent(monkeypatch):
    store = _store("arm-idem")
    _arm_with(monkeypatch, store, deployable=True, n=80)
    r1 = arm.arm(store)
    r2 = arm.arm(store)
    assert r1["version_id"] == r2["version_id"]  # reuses the version (clock not reset)
    assert store.row("SELECT COUNT(*) c FROM strategies WHERE name=?", (arm.STRATEGY_NAME,))["c"] == 1
    assert store.row("SELECT COUNT(*) c FROM tracks WHERE strategy_version_id=?", (r1["version_id"],))["c"] == 1
    n_opened = store.row("SELECT COUNT(*) c FROM events WHERE kind='track_opened' AND ref_id=?",
                         (r1["version_id"],))["c"]
    assert n_opened == 1
    # the trajectory is REWRITTEN (not duplicated) on re-arm — still exactly the net-stream length
    snaps = store.rows("SELECT 1 FROM portfolio_snapshots WHERE scope='track' AND ref_id=?", (r1["version_id"],))
    assert len(snaps) == 80


def test_arm_aborts_when_not_deployable(monkeypatch):
    store = _store("arm-abort")
    _arm_with(monkeypatch, store, deployable=False, n=80)
    result = arm.arm(store)
    assert result["armed"] is False
    assert store.row("SELECT COUNT(*) c FROM strategies WHERE name=?", (arm.STRATEGY_NAME,))["c"] == 0
    assert store.row("SELECT COUNT(*) c FROM tracks", ())["c"] == 0


def test_arm_mark_advances_trajectory(monkeypatch):
    store = _store("arm-mark")
    _arm_with(monkeypatch, store, deployable=True, n=80)
    arm.arm(store)
    # the mark re-validates (here: a longer freshly-validated stream) and advances the per-track trajectory
    _arm_with(monkeypatch, store, deployable=True, n=95)
    out = arm.mark(store)
    assert out["marked"] is True
    snaps = store.rows("SELECT 1 FROM portfolio_snapshots WHERE scope='track' AND ref_id=?", (out["version_id"],))
    assert len(snaps) == 95  # rewritten to the freshly-validated stream length, not duplicated
