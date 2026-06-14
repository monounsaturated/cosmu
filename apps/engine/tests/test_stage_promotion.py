# STAGE SEMANTICS — "Paper" must mean a strategy has REAL forward evidence (>= PAPER_PROMOTE_MIN_DAYS of marked
# forward time), never backtest-only. A forward-test entrant is born "screened" (badge: Backtest); the paper clock
# (orchestrator.mark_tracks) promotes it to "paper" once it survives a real forward day, and a one-shot boot
# reclassification (orchestrator.reclassify_unforwarded_paper) fixes legacy rows stamped "paper" at creation. Both
# are BADGE-ONLY relabels — the live/money gate reads track_opened, not status — and fully offline + deterministic.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.config.settings import PAPER_PROMOTE_MIN_DAYS, Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.master.portfolio import Portfolio
from cosmu.orchestrator.loop import PricingRouter, mark_tracks, reclassify_unforwarded_paper
from cosmu.spine.venue import default_catalog


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


def _setup_track(store: Store, *, status: str, age_days: float, return_pct: str = "5.00", open_pos: bool = True) -> str:
    """A funded standalone track at a chosen lifecycle status, whose paper clock (track_opened) started `age_days`
    ago. Returns the version_id. Mirrors exactly what the funder leaves behind: a tracks row + an open SPY@ibkr
    position + a track_opened event (the paper-clock origin forward_evidence reads)."""
    sid = store.insert("strategies", {"name": "TAA fleet", "thesis": "x", "origin": "documented",
                                      "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()})
    vid = store.insert(
        "strategy_versions",
        {"strategy_id": sid, "parent_id": None, "spec": {}, "generated_code": "", "code_hash": f"h-{status}-{age_days}",
         "params": {}, "mutation_operator": None, "mutation_rationale": "x", "origin": "documented",
         "status": status, "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat(),
         "killed_at": None, "kill_reason": None},
    )
    store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "10000", "equity": "10000.00",
                            "return_pct": return_pct, "updated_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()})
    if open_pos:
        pf = Portfolio(store, bankroll=store.settings.sim_bankroll)
        pf.apply_fill(instrument_id="spy-ibkr", symbol="SPY", venue="ibkr", side=1,
                      qty=Decimal("25"), price=Decimal("400"), fee=Decimal("0"), strategy_version_id=vid)
    origin_ts = (dt.datetime.now(dt.UTC) - dt.timedelta(days=age_days)).isoformat()
    store.rows(
        "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) VALUES (?, 'master', 'track_opened', 'strategy_version', ?, ?)",
        (origin_ts, vid, "{}"),
    )
    return vid


def _status(store: Store, vid: str) -> str:
    return store.row("SELECT status FROM strategy_versions WHERE id = ?", (vid,))["status"]


def _mark(store: Store) -> None:
    mark_tracks(store, router=PricingRouter(default_catalog(), crypto=_FakeProvider({}), equity=_FakeProvider({"SPY": 440.0})))


def test_screened_promotes_to_paper_after_a_forward_day(tmp_path):
    """The crux: a "screened" (Backtest) entrant whose paper clock has run >= PAPER_PROMOTE_MIN_DAYS is promoted to
    "paper" by the clock — and a status_promoted event records the honest transition."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="screened", age_days=PAPER_PROMOTE_MIN_DAYS + 1.0)
    assert _status(store, vid) == "screened"
    _mark(store)
    assert _status(store, vid) == "paper"
    ev = store.row("SELECT payload FROM events WHERE kind = 'status_promoted' AND ref_id = ?", (vid,))
    assert ev is not None  # the transition is audited, not silent


def test_screened_stays_backtest_within_first_forward_day(tmp_path):
    """A "screened" entrant marked on the SAME day it opened (age < threshold) has NO real forward evidence yet, so
    it stays "screened" (Backtest) — the same-day re-mark of the seed must never manufacture a "Paper" badge."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="screened", age_days=0.0)
    _mark(store)
    assert _status(store, vid) == "screened"
    assert store.row("SELECT 1 FROM events WHERE kind = 'status_promoted' AND ref_id = ?", (vid,)) is None


def test_reclassify_demotes_unforwarded_legacy_paper(tmp_path):
    """A legacy row stamped "paper" at creation, before any forward day, is demoted back to "screened" (Backtest) so
    the badge stops claiming forward evidence it doesn't have."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="paper", age_days=0.0, open_pos=False)
    n = reclassify_unforwarded_paper(store)
    assert n == 1
    assert _status(store, vid) == "screened"
    assert store.row("SELECT 1 FROM events WHERE kind = 'status_demoted' AND ref_id = ?", (vid,)) is not None


def test_reclassify_keeps_genuinely_forwarded_paper(tmp_path):
    """A "paper" row that HAS accrued a real forward day is left alone — reclassification only fixes the mislabeled,
    never demotes a strategy with genuine forward evidence."""
    store = _store(tmp_path)
    vid = _setup_track(store, status="paper", age_days=PAPER_PROMOTE_MIN_DAYS + 5.0, open_pos=False)
    n = reclassify_unforwarded_paper(store)
    assert n == 0
    assert _status(store, vid) == "paper"
