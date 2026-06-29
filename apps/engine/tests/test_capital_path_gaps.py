# CAPITAL-PATH GAP FIXES (follow-up to the live-arming dry-run, PR #467) — the two acceptance tests that pin the
# two silent gaps the dry-run surfaced, both fixed here:
#
#   GAP 1 (cell-scoped arming eligibility): live_launch now threads the launched cell's symbol+venue into
#         live_eligibility_verdict / paper_clock_origin, so a cell proven ONLY under its BRUT cell key
#         (version:symbol:venue) — the key the per-combo model writes — is ARMABLE. The fail-safe is preserved:
#         an UNPROVEN cell (no forward evidence under EITHER key) is STILL blocked.
#
#   GAP 2 (lot_size silent no-op): a high-priced ETF at the $1000 per-track sizing rounds to < 1 whole share and
#         the gauntlet rejects it (lot_size). The executor now SURFACES this loudly: report.rejected / .rejections
#         are populated AND a live-armed reject emits an `arm_opened_nothing` audit event — never a silent no-op.
#
# SAFETY: throwaway sqlite Store (_env_file=None → no real keys), the only "live" adapter is an in-process STUB
# (mode='paper' → the 'testnet' book; no socket, no key, no real venue). The conftest network guard fails the
# test if any real socket opens. Reuses conftest.seed_track_snapshots (the shared forward-evidence seeder).

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from conftest import seed_track_snapshots

import cosmu.api.app as app_mod
import cosmu.master.execution as execmod
import cosmu.orchestrator.paper_step as ps
from cosmu.config.settings import (
    PAPER_MIN_DAYS,
    PAPER_MIN_FORWARD_OBS,
    LiveSettings,
    Settings,
)
from cosmu.core.interfaces import AssetClass, OrderId
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, tracks_has_cell_columns, utcnow
from cosmu.master.live_eligibility import live_eligibility_verdict
from cosmu.master.portfolio import Portfolio
from cosmu.orchestrator.loop import PricingRouter
from cosmu.orchestrator.paper_step import step_tracks
from cosmu.spine.venue import default_catalog

_VID = "v-gapfix-taa"
_SYMBOL = "SHY"          # GAP 1 cell: a low-priced TAA safe asset (~$82) so a $1000 track buys >= 1 whole share.
_VENUE = "alpaca"
_INSTRUMENT = "shy-alpaca"
_NOW = dt.datetime(2026, 6, 28, tzinfo=dt.UTC)
_BASE = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=80)


def _store(tmp_path) -> Store:
    """A hermetic throwaway store: _env_file=None → never inherits the dev box's real venue keys."""
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/gapfix.sqlite3",
            openrouter_api_key=None,
            live=LiveSettings(),
            _env_file=None,
        )
    )


def _bull_bars(price: float = 82.0) -> list[Bar]:
    """A deterministic, gently-rising synthetic close series anchored at `price` → current_regime reads 'bull'.
    Used as BOTH the eligibility regime reference AND the executor's price provider. A HIGH `price` is how the
    GAP-2 test forces the sized order below 1 whole share (a $1000 track / a ~$1200 ETF sizes to < 1 share)."""
    out: list[Bar] = []
    p = price
    for i in range(80):
        p *= 1.001
        out.append(
            Bar(
                ts=_BASE + dt.timedelta(days=i),
                open=Decimal(str(round(p, 4))),
                high=Decimal(str(round(p * 1.002, 4))),
                low=Decimal(str(round(p * 0.998, 4))),
                close=Decimal(str(round(p, 4))),
                volume=Decimal("1000000"),
            )
        )
    return out


_BULL = _bull_bars()


class _Bars:
    """A deterministic equity bar provider (no network) serving a synthetic bull series for ONE symbol."""

    def __init__(self, bars: list[Bar], symbol: str) -> None:
        self._bars = bars
        self._symbol = symbol

    def fetch_bars(self, symbol, timeframe, *, limit):  # noqa: ANN001, ANN201
        return self._bars[-limit:] if symbol == self._symbol else []


def _router(bars: list[Bar], symbol: str) -> PricingRouter:
    provider = _Bars(bars, symbol)
    return PricingRouter(default_catalog(), crypto=provider, equity=provider)


_EQUITY_SPEC = {
    "name": "GapFixTAA",
    "rationale": "synthetic matured equity TAA cell for the capital-path gap-fix acceptance tests",
    "lane": "gate",
    "universe": {"venues": ["alpaca"], "asset_classes": ["equity"], "min_instruments": 1},
    "horizon": {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 365},
    "entry": [{"feature": {"name": "ret_Nd", "lookback": 3}, "op": "gt", "threshold": {"param": "mom"}}],
    "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
    "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
    "param_space": {},
    "direction": 1,
}
_EQUITY_PARAMS = {"mom": -1.0, "sl": 0.05, "tp": 0.50}


def _seed_cell(
    store: Store,
    *,
    symbol: str = _SYMBOL,
    instrument: str = _INSTRUMENT,
    cell_keyed_only: bool = True,
    forward_proven: bool = True,
    fills: int = 2,
    proven: tuple[str, ...] = ("bull", "chop"),
) -> None:
    """Seed ONE synthetic matured equity cell.

    `cell_keyed_only=True` (the GAP-1 point): the forward evidence (track_opened passport + clock origin +
    scope='track' snapshots) is written ONLY under the BRUT cell key (version:symbol:venue) — NEVER the version-
    only key. This is exactly what the per-combo (BRUT) funder writes once tracks are re-keyed per triple. The fix
    makes such a cell armable; before it, the version-scoped arming path read 'no proven regime on record'.

    `forward_proven=False`: write NO forward evidence at all (no passport, no snapshots) — the UNPROVEN cell that
    must STILL be blocked (the fail-safe half of the acceptance test)."""
    sid = store.insert("strategies", {"name": "GapFixTAA", "thesis": "t", "origin": "finder", "created_at": utcnow()})
    store.insert(
        "strategy_versions",
        {
            "id": _VID, "strategy_id": sid, "parent_id": None,
            "spec": _EQUITY_SPEC, "generated_code": "# taa", "code_hash": "hash-gapfix-taa",
            "params": _EQUITY_PARAMS, "mutation_operator": None, "mutation_rationale": None,
            "origin": "finder", "status": "paper", "created_at": utcnow(),
            "killed_at": None, "kill_reason": None,
        },
    )
    store.insert(
        "tracks",
        {
            "strategy_version_id": _VID, "symbol": symbol, "venue_id": _VENUE,
            "starting_capital": "100000", "equity": "104000",
            "return_pct": "4.0", "updated_at": utcnow(),
        },
    )
    cell_ref = f"{_VID}:{symbol}:{_VENUE}"
    if forward_proven:
        obs = PAPER_MIN_FORWARD_OBS + 18
        # CELL KEY ONLY — the BRUT key the per-combo funder uses. NO version-only seed (that is the whole point).
        seed_track_snapshots(store, cell_ref, obs=obs, forward_sharpe=0.40, now=_NOW)
        if not cell_keyed_only:  # legacy/back-compat variant: also seed the version-only key (pre-fix behaviour)
            seed_track_snapshots(store, _VID, obs=obs, forward_sharpe=0.40, now=_NOW)
        origin = _NOW - dt.timedelta(days=PAPER_MIN_DAYS + 10)
        ts = origin.isoformat()
        passport = json.dumps({"proven_regimes": list(proven), "symbol": symbol, "venue_id": _VENUE})
        refs = (cell_ref,) if cell_keyed_only else (cell_ref, _VID)
        with store.batch() as w:
            for ref in refs:
                w.execute(
                    "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) "
                    "VALUES (?, 'master', 'track_opened', 'strategy_version', ?, ?)",
                    (ts, ref, passport),
                )
            w.execute(
                "INSERT INTO runs(id, strategy_version_id, mode, venue_id, seed, started_at, status) "
                "VALUES (?, ?, 'sandbox', ?, 1, ?, 'completed')",
                (f"run-{_VID}", _VID, _VENUE, ts),
            )
            for i in range(fills):
                w.execute(
                    "INSERT INTO executions(id, run_id, strategy_version_id, instrument_id, venue_id, side, qty, "
                    "price, fee, slippage, order_type, is_paper, ts, fill_log) "
                    "VALUES (?, ?, ?, ?, ?, 'buy', '1', '400', '0.1', '0', 'market', 1, ?, '{}')",
                    (f"ex-{_VID}-{i}", f"run-{_VID}", _VID, instrument, _VENUE,
                     (origin + dt.timedelta(hours=i + 1)).isoformat()),
                )
    bt_id = store.insert(
        "backtests",
        {"strategy_version_id": _VID, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5", "sortino": "1.5",
         "deflated_sharpe": "1.5", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 30, "pbo": "0.0",
         "trials_counted": 1, "regime_label": json.dumps({"bull": 0.05, "chop": 0.01}), "folds_positive": 5,
         "passed_gates": 1, "holdout_passed": 1, "created_at": utcnow()},
    )
    store.insert(
        "backtest_symbols",
        {"backtest_id": bt_id, "strategy_version_id": _VID, "symbol": symbol, "venue_id": _VENUE,
         "return_pct": "0.2", "sharpe": "1.5", "max_drawdown": "0.1", "trades": 30, "verdict": "pass",
         "created_at": utcnow()},
    )
    Portfolio(store, bankroll=store.settings.sim_bankroll).register_track(
        instrument_id=instrument, symbol=symbol, venue="sim", strategy_version_id=_VID
    )


class _StubSandboxAdapter:
    """An ACTIVE Alpaca-SANDBOX adapter (mode='paper' → 'testnet' book) — NO keys, NO network. Records orders so a
    test can prove an order genuinely reached the venue adapter. The ONLY 'live' adapter the executor can see."""

    asset_class = AssetClass.EQUITY

    def __init__(self) -> None:
        self.venue = _VENUE
        self.mode = "paper"
        self.submitted: list = []

    @property
    def active(self) -> bool:
        return True

    def submit(self, order):  # noqa: ANN001, ANN201
        self.submitted.append(order)
        return OrderId(venue=self.venue, client_order_id=order.client_order_id, venue_order_id="STUB-1")

    def cancel(self, order_id):  # noqa: ANN001  # pragma: no cover
        pass

    def positions(self):  # noqa: ANN201
        return []

    def fills(self, since):  # noqa: ANN001, ANN201
        return []


def _arm(store, monkeypatch, *, symbol: str = _SYMBOL, confirm: bool = True, bars=None):
    """Drive the REAL arming entry (api.routers.live.live_launch) against the throwaway store. _venue_connected is
    stubbed True (testnet keys present, none on disk); _version_reference_bars is stubbed to the deterministic
    series so the regime read needs no network."""
    from cosmu.api.models import LaunchActivateRequest
    from cosmu.api.routers import live as live_router

    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", store.settings)
    monkeypatch.setattr(live_router, "_venue_connected", lambda venue_id: True)
    monkeypatch.setattr(live_router, "_version_reference_bars", lambda vid: bars or _BULL)
    req = LaunchActivateRequest(
        version_id=_VID, venue_id=_VENUE, symbol=symbol, budget=100.0,
        per_strategy_cap=100.0, global_cap=1000.0, max_daily_loss=50.0, confirm=confirm,
    )
    return live_router.live_launch(req)


# ---------------------------------------------------------------------------------------------------------------
# GAP 1 — a cell proven ONLY under its BRUT cell key is ARMABLE via live_launch; an unproven cell is STILL blocked.
# ---------------------------------------------------------------------------------------------------------------

def test_gap1_cell_keyed_only_proof_is_eligible_cell_scoped(tmp_path):
    """Pre-condition for the arm: the eligibility verdict reads the cell key (version:symbol:venue) and returns
    ELIGIBLE on evidence written ONLY under that key. (Without the fix the arming path read the version-only key
    and saw nothing.)"""
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=True)
    assert tracks_has_cell_columns(store) is True  # the throwaway tracks table carries the BRUT columns

    v = live_eligibility_verdict(store, _VID, _BULL, now=_NOW, symbol=_SYMBOL, venue_id=_VENUE)
    assert v.eligible is True, v.reason
    assert v.regime_eligible is True and v.forward_ready is True, v.reason

    # The version-only read (what the OLD arming path used) sees NOTHING — proving the proof is cell-keyed only.
    v_version_only = live_eligibility_verdict(store, _VID, _BULL, now=_NOW)
    assert v_version_only.eligible is False
    assert "no proven regime on record" in v_version_only.reason


def test_gap1_cell_keyed_only_proof_is_armable_via_live_launch(tmp_path, monkeypatch):
    """THE FIX: live_launch threads symbol+venue into the eligibility readers, so a cell proven ONLY under its
    BRUT key arms (writes status='live', freezes the config). Before the fix this returned armed=False with
    'no proven regime on record'."""
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=True)

    resp = _arm(store, monkeypatch, confirm=True)

    assert resp.armed is True, resp.reason
    assert resp.readiness == "proven"
    assert resp.overridden is False  # earned by cell-scoped evidence, NOT a human override
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"] == "live"
    assert store.row("SELECT id FROM events WHERE kind = 'live_launched' AND ref_id = ?", (_VID,)) is not None
    from cosmu.master.promotion import promotion_record

    assert promotion_record(store, _VID) is not None


def test_gap1_failsafe_unproven_cell_is_still_blocked(tmp_path, monkeypatch):
    """FAIL-SAFE (the invariant): a cell with NO forward evidence under EITHER key must NOT arm. The cell-scoped
    readers have no version-only fallback post-migration, so absent evidence reads EMPTY → blocked. status stays
    'paper'; no live_launched event; no promotion record. The fix widens which PROVEN cells arm, NEVER which
    UNPROVEN cells arm."""
    store = _store(tmp_path)
    _seed_cell(store, forward_proven=False)  # gate-passed + BRUT 'pass' cell, but ZERO forward proof

    resp = _arm(store, monkeypatch, confirm=True)

    assert resp.armed is False
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"] == "paper"
    assert store.row("SELECT id FROM events WHERE kind = 'live_launched' AND ref_id = ?", (_VID,)) is None
    from cosmu.master.promotion import promotion_record

    assert promotion_record(store, _VID) is None


def test_gap1_legacy_version_only_proof_arms_via_attribution_confirmed_fallback(tmp_path, monkeypatch):
    """BACK-COMPAT BRIDGE: the funder TODAY still keys forward evidence version-only while the tracks table already
    carries the BRUT columns. live_launch's safe fallback re-reads version-scoped ONLY when the funded position
    CONFIRMS the requested cell — so a legacy version-only-keyed (but genuinely funded + proven) cell still arms,
    exactly as it does in prod today. The registered flat position (symbol@venue) is what confirms attribution."""
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=False)  # also seeds the version-only key (the legacy funder shape)
    # Remove the CELL-keyed evidence so ONLY the version-only proof remains → the cell-scoped verdict is NOT
    # eligible and arming must rely on the attribution-confirmed version-scope fallback.
    cell_ref = f"{_VID}:{_SYMBOL}:{_VENUE}"
    store.rows("DELETE FROM events WHERE kind = 'track_opened' AND ref_id = ?", (cell_ref,))
    store.rows("DELETE FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ?", (cell_ref,))

    resp = _arm(store, monkeypatch, confirm=True)

    assert resp.armed is True, resp.reason  # the fallback bridged the legacy version-only proof
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"] == "live"


def test_gap1_failsafe_version_only_proof_without_funded_position_is_blocked(tmp_path, monkeypatch):
    """FAIL-SAFE for the fallback: version-only forward proof with NO funded position matching the request must NOT
    arm. With no funded position the attribution is unconfirmed → the version-scope fallback is DISABLED → the
    cell-scoped read (empty) blocks. This is what stops version-only evidence from arming a cell whose proof was
    never attributed to it. (Proves the fallback can never over-arm without a confirmed funded cell.)"""
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=False)  # version-only proof present
    # Strip the CELL-keyed proof AND the funded position → attribution cannot be confirmed.
    cell_ref = f"{_VID}:{_SYMBOL}:{_VENUE}"
    store.rows("DELETE FROM events WHERE kind = 'track_opened' AND ref_id = ?", (cell_ref,))
    store.rows("DELETE FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ?", (cell_ref,))
    store.rows("DELETE FROM positions WHERE strategy_version_id = ?", (_VID,))  # no funded cell → no attribution

    resp = _arm(store, monkeypatch, confirm=True)

    assert resp.armed is False  # unconfirmed attribution → fallback disabled → blocked (fail-safe)
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"] == "paper"


def test_gap1_failsafe_confirm_interlock_still_required(tmp_path, monkeypatch):
    """The human-arming interlock is untouched: even a fully cell-proven cell does NOT arm without confirm=True."""
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=True)

    resp = _arm(store, monkeypatch, confirm=False)

    assert resp.armed is False
    assert "confirm" in (resp.reason or "").lower()
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", (_VID,))["status"] == "paper"


# ---------------------------------------------------------------------------------------------------------------
# GAP 2 — a high-priced ETF at a small budget produces a VISIBLE, audited rejection (no silent no-op arm).
# ---------------------------------------------------------------------------------------------------------------

def test_gap2_high_priced_etf_lot_size_reject_is_surfaced_not_silent(tmp_path, monkeypatch):
    """A $1000-per-track sizing on a ~$1200 ETF sizes to < 1 whole share → the gauntlet rejects (lot_size). The
    arm opens NO position, but it is NO LONGER silent: report.rejected/.rejections are populated AND a LOUD,
    audited `arm_opened_nothing` event is written for the live-armed cell, with the lot_size reason."""
    high_bars = _bull_bars(price=1200.0)  # a high-priced ETF the $1000 track can't buy a whole share of
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=True)
    _arm(store, monkeypatch, confirm=True, bars=high_bars)  # arm via the real entry on the high-priced series
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")  # toggle on (DB half of the switch)

    stub = _StubSandboxAdapter()
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {_VENUE: stub})
    monkeypatch.setattr(execmod, "_regime_returns", lambda store_, vid: {"bull": 0.05, "chop": 0.01})
    monkeypatch.setattr(execmod, "_reference_bars", lambda adapter, symbol: [float(b.close) for b in high_bars])

    report = step_tracks(store, router=_router(high_bars, _SYMBOL), now=_NOW)

    # No position opened — the entry was REJECTED, not booked. (The silent-no-op bug is exactly this with NO signal.)
    assert report.opened == 0, report
    pos = store.row(
        "SELECT COALESCE(SUM(CAST(qty AS REAL)), 0) AS q FROM positions WHERE strategy_version_id = ?", (_VID,)
    )
    assert float(pos["q"]) == 0.0  # nothing held
    assert len(stub.submitted) == 0  # nothing reached the venue

    # VISIBLE in the tick report (the fix): the rejection is counted + recorded, not silently dropped.
    assert report.rejected == 1, report
    assert len(report.rejections) == 1
    rej = report.rejections[0]
    assert rej["symbol"] == _SYMBOL and rej["venue_id"] == _VENUE and rej["routing"] == "live"
    assert "lot_size" in rej["issues"]

    # LOUD + AUDITED: a live-armed reject emits arm_opened_nothing so the operator knows the arm opened nothing + why.
    ev = store.row(
        "SELECT payload FROM events WHERE kind = 'arm_opened_nothing' AND ref_id = ?", (_VID,)
    )
    assert ev is not None, "a live-armed lot_size reject must emit a loud arm_opened_nothing event"
    payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
    assert payload["symbol"] == _SYMBOL and "lot_size" in payload["issues"]
    # The order path's own audit row is still present too (defence in depth).
    assert store.row("SELECT id FROM events WHERE kind = 'order_rejected' AND ref_id = ?", (_VID,)) is not None


def test_gap2_low_priced_etf_opens_cleanly_no_false_rejection(tmp_path, monkeypatch):
    """Control: a LOW-priced ETF (~$82 SHY) at the same $1000 track buys >= 1 whole share → the entry routes and
    opens, with NO rejection surfaced. The GAP-2 surfacing fires ONLY on a genuine reject, never spuriously."""
    store = _store(tmp_path)
    _seed_cell(store, cell_keyed_only=True)
    _arm(store, monkeypatch, confirm=True)
    store.rows("UPDATE live_toggle SET enabled = 1 WHERE id = 'global'")

    stub = _StubSandboxAdapter()
    monkeypatch.setattr(ps, "_resolve_live_adapters", lambda s: {_VENUE: stub})
    monkeypatch.setattr(execmod, "_regime_returns", lambda store_, vid: {"bull": 0.05, "chop": 0.01})
    monkeypatch.setattr(execmod, "_reference_bars", lambda adapter, symbol: [float(b.close) for b in _BULL])

    report = step_tracks(store, router=_router(_BULL, _SYMBOL), now=_NOW)

    assert report.opened == 1, report
    assert report.rejected == 0 and report.rejections == []
    assert store.row("SELECT id FROM events WHERE kind = 'arm_opened_nothing'") is None  # no false alarm
    assert len(stub.submitted) == 1  # the entry genuinely reached the sandbox adapter
