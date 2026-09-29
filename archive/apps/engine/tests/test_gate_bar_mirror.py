# DRIFT GUARD (deep review, 2026-06-12): the gate's pass bar is intentionally written down TWICE — the frozen
# pre-registered dict in research/gate.py (changing it is itself a new trial) and the typed GateSettings
# defaults the FarmLoop/finder score against — under RENAMED keys (max_cscv_pbo vs max_pbo, must_beat_buy_and_hold
# vs require_beat_buy_and_hold, max_drawdown vs max_drawdown_pct), which defeats grep. A calibration change
# applied to one path would silently diverge the other; this test is the alarm that fires instead.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import GateSettings
from cosmu.research.gate import PREREGISTERED_BAR


def test_preregistered_bar_mirrors_gate_settings_defaults():
    s = GateSettings()
    assert PREREGISTERED_BAR["min_trades"] == s.min_trades
    assert Decimal(str(PREREGISTERED_BAR["min_deflated_sharpe_prob"])) == s.min_deflated_sharpe_prob
    assert Decimal(str(PREREGISTERED_BAR["max_cscv_pbo"])) == s.max_pbo
    assert Decimal(str(PREREGISTERED_BAR["max_drawdown"])) == s.max_drawdown_pct
    assert PREREGISTERED_BAR["must_beat_buy_and_hold"] == s.require_beat_buy_and_hold
