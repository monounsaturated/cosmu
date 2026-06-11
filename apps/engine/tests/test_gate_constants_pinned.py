# THE GATE'S CALIBRATION IS PINNED. These constants ARE the machine's honesty: the 0.95 deflated-Sharpe
# probability bar, the BH-FDR level, the trade-count/drawdown/fold/PBO floors, and the 30-day paper
# maturity. They were locked by calibration evidence (synthetic-noise refusal + real-data behavior), and an
# agent "helpfully" relaxing one (0.95 → 0.5) must FAIL verify loudly instead of shipping a silently weaker
# gate. If you are changing a value here, you are recalibrating the machine: bring the evidence, change the
# constant and this test in the SAME commit, and say so in the commit message.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import PAPER_MIN_DAYS, GateSettings


def test_gate_bar_is_the_locked_calibration():
    g = GateSettings()
    assert g.min_deflated_sharpe_prob == Decimal("0.95")  # PSR vs the trial-inflated benchmark — THE bar
    assert g.fdr_q == Decimal("0.10")                     # Benjamini-Hochberg FDR across each cohort
    assert g.min_trades == 30
    assert g.max_drawdown_pct == Decimal("0.25")
    assert g.min_folds_positive_pct == Decimal("0.60")
    assert g.max_pbo == Decimal("0.50")
    assert g.holdout_min_deflated_sharpe == Decimal("0")
    assert g.require_beat_buy_and_hold is True            # a bull-regime long must beat just HOLDING


def test_paper_maturity_floor_is_pinned():
    # The advisory live-readiness floor: ≥30 calendar days of net-positive REAL forward evidence.
    assert PAPER_MIN_DAYS == 30
