# Two-leg delta-neutral track (DERIVATIVES_PLAN P0.3, §6): pair a long-spot leg with a short-perp leg, mark BOTH
# legs on real closes, accrue perp funding into the marked value — and prove the single-leg SPOT path is
# byte-identical when no short leg exists. Fully offline + deterministic: no network, only seeded positions/marks.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.neutral import accrue_funding, neutral_tracks
from cosmu.master.portfolio import Portfolio


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/neutral.sqlite3"))


def _open(pf: Portfolio, *, vid: str, instrument_id: str, symbol: str, side: int, qty: Decimal, price: Decimal) -> None:
    pf.apply_fill(
        instrument_id=instrument_id, symbol=symbol, venue="sim", side=side, qty=qty, price=price,
        fee=Decimal("0"), strategy_version_id=vid,
    )


# ---------- pairing: a neutral track = one long leg + one short leg under one version ------------------------


def test_single_leg_spot_track_is_not_a_neutral_pair(tmp_path):
    """A plain long-spot track (one long leg, no short leg) must NOT be detected as neutral — the single-leg
    spot path still owns it, untouched."""
    pf = Portfolio(_store(tmp_path))
    _open(pf, vid="sv-spot", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    tracks = neutral_tracks(pf.store, pf.positions())
    assert tracks == []


def test_long_spot_short_perp_pairs_into_a_neutral_track(tmp_path):
    """A long-spot leg + a short-perp leg under one version_id pair into a single neutral track; the long is the
    spot leg, the short is the perp (funding-bearing) leg."""
    pf = Portfolio(_store(tmp_path))
    _open(pf, vid="sv-neutral", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv-neutral", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    tracks = neutral_tracks(pf.store, pf.positions())
    assert len(tracks) == 1
    track = tracks[0]
    assert track.spot.qty > 0 and not track.spot.is_perp
    assert track.perp.qty < 0 and track.perp.is_perp
    assert track.funding_accrued == Decimal("0")


# ---------- two-leg marking: the direction cancels, leaving basis (+ funding) -------------------------------


def test_both_legs_marked_and_direction_cancels(tmp_path):
    """With both legs at the same price and a parallel move, the price P&L of the long spot and short perp cancel
    (delta-neutral by construction) — net_unrealized ≈ 0 before funding."""
    pf = Portfolio(_store(tmp_path))
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    track = neutral_tracks(pf.store, pf.positions())[0]
    # Both legs move +10 in lockstep: long gains +10, short loses -10 → net 0 (the hedge worked).
    marks = {"btc-usdt-binance": Decimal("110"), "btc-perp-okx": Decimal("110")}
    assert track.net_unrealized(marks) == Decimal("0")
    assert track.marked_value(marks) == Decimal("0")


def test_basis_move_shows_in_net_unrealized(tmp_path):
    """When the spot and perp legs move by DIFFERENT amounts (a basis change), the residual shows as net P&L —
    proving BOTH legs are genuinely marked, not just the spot."""
    pf = Portfolio(_store(tmp_path))
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    track = neutral_tracks(pf.store, pf.positions())[0]
    # spot +10, perp +6 → long +10, short -6 → +4 basis P&L
    marks = {"btc-usdt-binance": Decimal("110"), "btc-perp-okx": Decimal("106")}
    assert track.net_unrealized(marks) == Decimal("4")


# ---------- funding accrues with the carry sign -------------------------------------------------------------


def test_short_perp_receives_positive_funding(tmp_path):
    """The thesis sign: a SHORT perp RECEIVES funding when the rate is positive (carry income). Funding is
    journaled and read back as the cumulative total — no schema change."""
    store = _store(tmp_path)
    pf = Portfolio(store)
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    track = neutral_tracks(store, pf.positions())[0]
    total = accrue_funding(store, track, funding_rate=Decimal("0.01"), perp_mark=Decimal("100"))
    # short qty=-1, rate=+0.01, notional = 1*100 = 100 → flow = -(-1)*0.01*100 = +1 (received)
    assert total == Decimal("1.00000000")
    # read back the cumulative from the journal (the existing events.payload column)
    refreshed = neutral_tracks(store, pf.positions())[0]
    assert refreshed.funding_accrued == Decimal("1.00000000")


def test_negative_funding_is_a_cost_to_the_short(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store)
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    track = neutral_tracks(store, pf.positions())[0]
    total = accrue_funding(store, track, funding_rate=Decimal("-0.01"), perp_mark=Decimal("100"))
    assert total == Decimal("-1.00000000")  # negative rate: the short PAYS


def test_funding_accumulates_across_periods(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store)
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    accrue_funding(store, neutral_tracks(store, pf.positions())[0], funding_rate=Decimal("0.01"), perp_mark=Decimal("100"))
    accrue_funding(store, neutral_tracks(store, pf.positions())[0], funding_rate=Decimal("0.01"), perp_mark=Decimal("100"))
    assert neutral_tracks(store, pf.positions())[0].funding_accrued == Decimal("2.00000000")


def test_zero_funding_is_a_no_op(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store)
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    track = neutral_tracks(store, pf.positions())[0]
    assert accrue_funding(store, track, funding_rate=Decimal("0"), perp_mark=Decimal("100")) == Decimal("0")
    assert store.row("SELECT id FROM events WHERE kind = 'neutral_funding_accrued'") is None


# ---------- portfolio integration: funding flows into equity, spot path unchanged ---------------------------


def test_mark_to_market_without_funding_is_unchanged(tmp_path):
    """Calling mark_to_market WITHOUT funding_by_track (every spot caller) is byte-identical to before — the
    single-leg spot path is untouched."""
    pf = Portfolio(_store(tmp_path))
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=1, qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id="sv")
    base = pf.mark_to_market({"btc-usdt-binance": Decimal("110")})
    with_empty = pf.mark_to_market({"btc-usdt-binance": Decimal("110")}, funding_by_track={})
    assert base["equity"] == with_empty["equity"]


def test_funding_lifts_equity_on_a_neutral_track(tmp_path):
    """A neutral track at zero basis P&L but with positive accrued funding lifts equity by exactly the funding —
    the carry IS the edge the price marks can't show."""
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=Decimal("100000"))
    _open(pf, vid="sv", instrument_id="btc-usdt-binance", symbol="BTCUSDT", side=1, qty=Decimal("1"), price=Decimal("100"))
    _open(pf, vid="sv", instrument_id="btc-perp-okx", symbol="BTC-USDT-SWAP", side=-1, qty=Decimal("1"), price=Decimal("100"))
    marks = {"btc-usdt-binance": Decimal("110"), "btc-perp-okx": Decimal("110")}  # parallel move → 0 basis P&L
    no_funding = pf.mark_to_market(marks)
    with_funding = pf.mark_to_market(marks, funding_by_track={"sv": Decimal("5")})
    assert with_funding["equity"] - no_funding["equity"] == Decimal("5")
