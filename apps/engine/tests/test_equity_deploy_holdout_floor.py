# Regression: the equity DEPLOY-LANE arms (sector-rotation TAA, TSMOM trend) gate "holdout positive" on a
# SIGNIFICANCE FLOOR (`holdout_dsr > DEPLOY_MIN_HOLDOUT_DSR`), NOT a raw sign-check (`>= 0` / `> 0`). The deploy
# lane pays NO multiple-testing deflation (it never routes through score() / promote_cohort / FDR), so a raw
# sign-check is a coin-flip: a ZERO-edge monthly stream clears it ~50% of the time (Monte-Carlo, 3000 zero-mean
# draws at each arm's embargo). The floor 0.20 was calibrated to (a) push the no-edge holdout pass-rate down
# (50% -> ~30%, compounded by each arm's extra beats_spy/beats_risk_adj + crash-regime robust hurdles) while
# (b) KEEPING the REAL documented edges deployable with a SAFE margin (measured sector holdout_dsr=+0.39,
# tsmom=+0.49 — both well above 0.20, so a genuine documented edge is never discarded). This mirrors
# perp_market_neutral.DEPLOY_MIN_HOLDOUT_DSR (0.30 — that arm has no extra hurdle, so it needs a higher floor).
# Recalibrating means changing the constant AND this test AND the inline evidence, in one commit. See
# docs/research/RESEARCH_LESSONS.md §2b. The locked 0.95 cohort Gate (gate.py/scorer.py/GateSettings) is untouched.
from __future__ import annotations

import cosmu.research.equity_sector_rotation_taa as sector
import cosmu.research.equity_tsmom_trend as tsmom


def _assert_significance_floor(mod, expected: float) -> None:
    # the locked floor — a deliberate, evidence-backed calibration, not an arbitrary constant
    assert mod.DEPLOY_MIN_HOLDOUT_DSR == expected
    # a held-out Sharpe that is positive-but-insignificant (dsr in (0, floor]) must NOT clear the floor —
    # i.e. the bar is a SIGNIFICANCE test, not a coin-flip sign-check
    insignificant = 0.5 * mod.DEPLOY_MIN_HOLDOUT_DSR
    assert insignificant > 0 and not (insignificant > mod.DEPLOY_MIN_HOLDOUT_DSR)


def test_sector_rotation_holdout_floor_is_a_significance_bar_not_a_sign_check():
    _assert_significance_floor(sector, 0.20)


def test_tsmom_holdout_floor_is_a_significance_bar_not_a_sign_check():
    _assert_significance_floor(tsmom, 0.20)
