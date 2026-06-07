# Regression test for the Faber GTAA phantom -20% mark (2026-06-07).
#
# Faber GTAA is a 5-sleeve 10m-SMA portfolio: each sleeve holds its ETF when above its 10-month SMA, else it holds
# short-Treasury (CASH=SHY). The arm previously opened positions ONLY for the invested (above-SMA) sleeves, so a
# partially-invested track (e.g. 4 of 5 sleeves) deployed only 4/5 of capital while the mark divided by the FULL track
# size -> a fabricated -1/5 (~-20%) loss. The fix deploys the uninvested sleeves into SHY so the full capital is
# represented and the mark is honest. This test pins that behavior.
#
# Offline-safe: mocks gtaa.validate (no market data / no network) and _last_equity_close (fixed prices).

from __future__ import annotations

from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research import equity_faber_gtaa as gtaa
from cosmu.research import equity_faber_gtaa_arm as arm_mod


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/faber.sqlite3"))


def _fake_v(invested: list[str]) -> dict:
    full = gtaa.PerfStats(200, 0.5, 0.06, 0.10, 1.1, 0.11, 0.6)
    oos = gtaa.PerfStats(100, 0.2, 0.05, 0.10, 1.0, 0.10, 0.6)
    return {
        "deployable": True,
        "current_invested": invested,
        "current_signals": {s: (s in invested) for s in gtaa.SLEEVES},
        "full": full,
        "oos": oos,
        "window": [(2010, 1), (2020, 1)],
        "flips": 12,
    }


def _positions(store: Store, version_id: str) -> dict[str, Decimal]:
    rows = store.rows(
        "SELECT symbol, qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0",
        (version_id,),
    )
    return {r["symbol"]: Decimal(str(r["qty"])) for r in rows}


@pytest.mark.parametrize("invested", [
    ["SPY", "EFA", "AGG", "GLD"],          # 1 sleeve (IEF) in cash -> was the live -20% case
    ["SPY", "EFA"],                          # 3 sleeves in cash
    [],                                      # fully defensive: all 5 in cash
    ["SPY", "EFA", "AGG", "GLD", "IEF"],     # fully invested: no cash sleeve
])
def test_faber_arm_deploys_full_capital_via_cash_sleeve(tmp_path, monkeypatch, invested):
    monkeypatch.setattr(gtaa, "validate", lambda **_: _fake_v(invested))
    monkeypatch.setattr(arm_mod, "_last_equity_close", lambda _sym: Decimal("100"))

    store = _store(tmp_path)
    result = arm_mod.arm(store)
    assert result["armed"] is True
    version_id = result["version_id"]

    pos = _positions(store, version_id)
    n_cash = len(gtaa.SLEEVES) - len(invested)

    # Every invested sleeve is held as its ETF; uninvested sleeves are consolidated into SHY (never IEF-as-cash etc).
    for sym in invested:
        assert sym in pos, f"invested sleeve {sym} not held"
    if n_cash > 0:
        assert gtaa.CASH in pos, "uninvested sleeves were not deployed into the SHY cash sleeve"
    else:
        assert gtaa.CASH not in pos, "fully-invested track should hold no SHY"

    # The crux: the FULL track capital is deployed (all 5 sleeves represented), so qty*price sums to ~TRACK_CAPITAL.
    deployed = sum(q * Decimal("100") for q in pos.values())
    assert abs(deployed - arm_mod.TRACK_CAPITAL) <= Decimal("1"), (
        f"deployed {deployed} != track capital {arm_mod.TRACK_CAPITAL} (phantom partial-deployment)"
    )

    # And the marked return is honest (~0% at t0, never the -20% phantom).
    arm_mod.mark(store)
    track = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (version_id,))
    ret = Decimal(str(track["return_pct"]))
    assert abs(ret) < Decimal("1.0"), f"phantom mark: return_pct={ret} (expected ~0)"
