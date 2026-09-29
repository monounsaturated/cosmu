# The funder seed-collapse ROOT fix (master/portfolio.mark_to_market) + the canonical seed-hygiene helpers
# (master/track_equity) + the decision-path consumers that must ignore the collapse (drift auto-defund,
# live-eligibility significance). Root cause: the FUNDER re-marks an already-HELD track with a marks-dict that
# carries only the freshly-funded cells, so the held legs fall back to cost basis → unrealized 0 → equity ==
# starting_capital (the SEED) to the cent. This is a stale re-mark, not a fresh price, so the writer must SKIP it and
# the return/Sharpe readers must DROP it. Offline: temp sqlite Store, no network.

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.drift import track_return_series
from cosmu.master.live_eligibility import forward_daily_returns
from cosmu.master.portfolio import Portfolio
from cosmu.master.track_equity import (
    is_seed_equity,
    latest_real_equity,
    real_track_rows,
    track_starting_capital,
)

_INSTR = "btc-usdt-binance"
_SYM = "BTCUSDT"
_VEN = "binance"


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/seed.sqlite3"))


def _mk_version(store: Store, vid: str, starting_capital: float) -> None:
    store.rows(
        "INSERT INTO strategies (id, name, thesis, origin, created_at) VALUES (?, ?, ?, ?, ?)",
        ("s1", "seed-test", "t", "test", utcnow()),
    )
    store.rows(
        "INSERT INTO strategy_versions "
        "(id, strategy_id, spec, generated_code, code_hash, params, origin, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vid, "s1", "{}", "", "h", "{}", "test", "paper", utcnow()),
    )
    store.insert(
        "tracks",
        {
            "strategy_version_id": vid, "symbol": _SYM, "venue_id": _VEN,
            "starting_capital": str(starting_capital), "equity": str(starting_capital),
            "return_pct": "0.00", "updated_at": utcnow(),
        },
    )


def _track_equities(store: Store, ref: str) -> list[float]:
    return [
        float(r["equity"])
        for r in store.rows(
            "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts ASC", (ref,)
        )
    ]


def _insert_series(store: Store, ref: str, equities: list[float], day0: str = "2026-06-01") -> None:
    d0 = date.fromisoformat(day0)
    for i, eq in enumerate(equities):
        store.insert(
            "portfolio_snapshots",
            {
                "scope": "track", "ref_id": ref, "ts": (d0 + timedelta(days=i)).isoformat() + "T00:00:00+00:00",
                "equity": str(eq), "cash": "0.00", "positions_value": str(eq), "pnl": "0.00", "drawdown": "0.0000",
            },
        )


# ---------------------------------------------------------------------------
# ROOT: the writer no longer emits a seed-collapse per-track snapshot
# ---------------------------------------------------------------------------

def test_funder_remark_of_held_cell_writes_no_seed_collapse(tmp_path):
    store = _store(tmp_path)
    _mk_version(store, "v1", 1000.0)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id=_INSTR, symbol=_SYM, venue="sim", side=1,
                  qty=Decimal("0.02"), price=Decimal("50000"), fee=Decimal("0"), strategy_version_id="v1")
    # Paper clock: a REAL mark writes a real per-track snapshot (1000 + (55000-50000)*0.02 = 1100).
    pf.mark_to_market({_INSTR: Decimal("55000")})
    assert _track_equities(store, "v1") == [1100.0]
    # Funder re-mark of the ALREADY-HELD cell (its instrument is NOT in the marks dict) must NOT append a
    # cost-basis collapse to the $1,000 seed — the ROOT fix skips the write, leaving the last real mark as latest.
    pf.mark_to_market({})
    equities = _track_equities(store, "v1")
    assert equities == [1100.0]
    assert all(not is_seed_equity(e, 1000.0) for e in equities)


def test_flat_registered_cell_still_records_day0_seed(tmp_path):
    # A freshly-registered FLAT cell (qty=0, no open leg) is NOT a collapse — it records its honest day-0 seed.
    store = _store(tmp_path)
    _mk_version(store, "v1", 1000.0)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.register_track(instrument_id=_INSTR, symbol=_SYM, venue="sim", strategy_version_id="v1")
    pf.mark_to_market({_INSTR: Decimal("50000")})
    assert _track_equities(store, "v1") == [1000.0]  # day-0 truth kept (leading seed), not skipped


def test_held_cell_with_a_real_mark_still_writes(tmp_path):
    # Sanity: a held cell that DOES get a real mark this tick writes normally (the fix only skips mark-less ticks).
    store = _store(tmp_path)
    _mk_version(store, "v1", 1000.0)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id=_INSTR, symbol=_SYM, venue="sim", side=1,
                  qty=Decimal("0.02"), price=Decimal("50000"), fee=Decimal("0"), strategy_version_id="v1")
    pf.mark_to_market({_INSTR: Decimal("50000")})   # flat P&L, but a REAL mark → written at the seed (entry)
    pf.mark_to_market({_INSTR: Decimal("60000")})   # +200 → 1200
    assert _track_equities(store, "v1") == [1000.0, 1200.0]


# ---------------------------------------------------------------------------
# HELPERS: master/track_equity
# ---------------------------------------------------------------------------

def test_seed_hygiene_helpers():
    assert is_seed_equity(1000.00, 1000.0)
    assert not is_seed_equity(1000.02, 1000.0)
    assert is_seed_equity(5.0, None) is False
    rows = [{"equity": e} for e in ["1000.02", "1024.75", "1000.00", "1024.75", "1000.00"]]
    assert [r["equity"] for r in real_track_rows(rows, 1000.0)] == ["1000.02", "1024.75", "1024.75"]
    assert latest_real_equity(rows, 1000.0) == 1024.75
    # A LEADING run of seed rows is day-0 truth — kept, not dropped.
    lead = [{"equity": e} for e in ["1000.00", "1000.00", "1010.00"]]
    assert len(real_track_rows(lead, 1000.0)) == 3
    assert latest_real_equity(lead, 1000.0) == 1010.0
    # Never-marked track → its seed is the honest latest; empty → None.
    assert latest_real_equity([{"equity": "1000.00"}], 1000.0) == 1000.0
    assert latest_real_equity([], 1000.0) is None


def test_track_starting_capital_schema_aware(tmp_path):
    store = _store(tmp_path)
    _mk_version(store, "v1", 1000.0)
    assert track_starting_capital(store, f"v1:{_SYM}:{_VEN}") == 1000.0  # cell key
    assert track_starting_capital(store, "v1") == 1000.0                 # legacy version key
    assert track_starting_capital(store, "no-such-version") is None


# ---------------------------------------------------------------------------
# CONSUMERS: seed rows must not corrupt the return / Sharpe series
# ---------------------------------------------------------------------------

def test_drift_return_series_ignores_seed_collapse(tmp_path):
    store = _store(tmp_path)
    _mk_version(store, "v1", 1000.0)
    # entry 1000.02, mark 1024.75, funder collapse 1000.00, mark 1030.00
    _insert_series(store, "v1", [1000.02, 1024.75, 1000.00, 1030.00])
    rets = track_return_series(store, "v1")
    expected = [(1024.75 - 1000.02) / 1000.02, (1030.00 - 1024.75) / 1024.75]
    assert len(rets) == 2
    assert all(abs(a - b) < 1e-9 for a, b in zip(rets, expected, strict=True))


def test_forward_daily_returns_ignores_seed_collapse(tmp_path):
    store = _store(tmp_path)
    _mk_version(store, "v1", 1000.0)
    _insert_series(store, "v1", [1000.02, 1024.75, 1000.00, 1030.00])  # one mark per calendar day
    rets = forward_daily_returns(store, "v1")
    expected = [(1024.75 - 1000.02) / 1000.02, (1030.00 - 1024.75) / 1024.75]
    assert len(rets) == 2
    assert all(abs(a - b) < 1e-9 for a, b in zip(rets, expected, strict=True))
