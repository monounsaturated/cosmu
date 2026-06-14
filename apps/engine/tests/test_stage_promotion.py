# STAGE SEMANTICS — "Paper" must mean a strategy has actually STARTED TRADING on paper: >= 1 REAL paper fill in
# the executions log (the same signal the detail sheet reads — "no fills yet" / "needs fills for a curve"). A
# forward-test entrant is born "screened" (badge: Backtest); the paper clock (orchestrator.mark_tracks) promotes
# it to "paper" on its FIRST real fill, and a one-shot boot reclassification (reclassify_unforwarded_paper) demotes
# any "paper" row that has no fills (e.g. a documented arm that only holds a static allocation — apply_fill writes
# positions, never executions). Both are BADGE-ONLY relabels — the live/money gate reads track_opened, not status.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio
from cosmu.orchestrator.loop import PricingRouter, mark_tracks, reclassify_unforwarded_paper
from cosmu.spine.venue import default_catalog

_TS = dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/stage.sqlite3"))


class _FakeProvider:
    """One fixed close per symbol; an unknown symbol returns no bars (offline) so the clock skips it."""

    def __init__(self, closes: dict[str, float]) -> None:
        self._closes = closes
        self.asked: list[str] = []

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        self.asked.append(symbol)
        if symbol not in self._closes:
            return []
        c = Decimal(str(self._closes[symbol]))
        return [Bar(ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), open=c, high=c, low=c, close=c, volume=Decimal("0"))]


def _add_paper_fill(store: Store, vid: str) -> None:
    """Record ONE real paper fill in the executions log — what makes a version 'has started trading on paper'."""
    rid = store.insert(
        "runs",
        {"strategy_version_id": vid, "mode": "paper", "venue_id": "ibkr", "seed": 1, "started_at": _TS, "status": "completed"},
    )
    store.insert(
        "executions",
        {"run_id": rid, "strategy_version_id": vid, "instrument_id": "spy-ibkr", "venue_id": "ibkr", "side": "buy",
         "qty": "25", "price": "400", "fee": "0", "slippage": "0", "order_type": "market", "is_paper": 1,
         "ts": _TS, "fill_log": "{}"},
    )


def _setup_track(store: Store, *, status: str, with_fill: bool, open_pos: bool = True) -> str:
    """A funded standalone track at a chosen lifecycle status. `with_fill` records a real paper execution (so the
    version 'has started trading'); without it the track only HOLDS an allocation (positions, no fills) — exactly
    the documented-arm case. Returns the version_id."""
    sid = store.insert("strategies", {"name": "TAA fleet", "thesis": "x", "origin": "documented", "created_at": _TS})
    vid = store.insert(
        "strategy_versions",
        {"strategy_id": sid, "parent_id": None, "spec": {}, "generated_code": "", "code_hash": f"h-{status}-{with_fill}",
         "params": {}, "mutation_operator": None, "mutation_rationale": "x", "origin": "documented",
         "status": status, "created_at": _TS, "killed_at": None, "kill_reason": None},
    )
    store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "10000", "equity": "10000.00",
                            "return_pct": "5.00", "updated_at": _TS})
    if open_pos:
        pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
        pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=1,
                      qty=Decimal("25"), price=Decimal("400"), fee=Decimal("0"), strategy_version_id=vid)
    if with_fill:
        _add_paper_fill(store, vid)
    return vid


def _status(store: Store, vid: str) -> str:
    return store.row("SELECT status FROM strategy_versions WHERE id = ?", (vid,))["status"]


def _mark(store: Store) -> None:
    mark_tracks(store, router=PricingRouter(default_catalog(), crypto=_FakeProvider({}), equity=_FakeProvider({"SPY": 440.0})))


def test_screened_promotes_to_paper_on_first_real_fill(tmp_path):
    """The crux: a "screened" (Backtest) entrant that has recorded its FIRST real paper fill is promoted to "paper"
    by the clock — and a status_promoted event records the honest transition."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="screened", with_fill=True)
    assert _status(store, vid) == "screened"
    _mark(store)
    assert _status(store, vid) == "paper"
    assert store.row("SELECT 1 FROM events WHERE kind = 'status_promoted' AND ref_id = ?", (vid,)) is not None


def test_screened_stays_backtest_with_no_fills(tmp_path):
    """A "screened" entrant that only HOLDS an allocation (positions, but zero executions — the documented-arm case)
    has not started trading, so it stays "screened" (Backtest). The mark of a held position must never manufacture
    a "Paper" badge."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="screened", with_fill=False)
    _mark(store)
    assert _status(store, vid) == "screened"
    assert store.row("SELECT 1 FROM events WHERE kind = 'status_promoted' AND ref_id = ?", (vid,)) is None


def test_reclassify_demotes_paper_with_no_fills(tmp_path):
    """A row stamped/promoted to "paper" that never actually traded (no executions) is demoted back to "screened"
    (Backtest) so the badge stops claiming a paper track it doesn't have."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="paper", with_fill=False, open_pos=False)
    assert reclassify_unforwarded_paper(store) == 1
    assert _status(store, vid) == "screened"
    assert store.row("SELECT 1 FROM events WHERE kind = 'status_demoted' AND ref_id = ?", (vid,)) is not None


def test_reclassify_keeps_paper_that_has_traded(tmp_path):
    """A "paper" row that HAS a real paper fill is left alone — reclassification only fixes the mislabeled, never
    demotes a strategy that has genuinely started trading."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="paper", with_fill=True, open_pos=False)
    assert reclassify_unforwarded_paper(store) == 0
    assert _status(store, vid) == "paper"
