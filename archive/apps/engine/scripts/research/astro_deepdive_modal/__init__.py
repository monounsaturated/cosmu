# intent: package for the APPROVED astro full deep-dive Modal harness (the most exhaustive, definitive
# astro pass — full universe × full astro parameter space, with Deflated-Sharpe at the TRUE trial count).
# RESEARCH-ONLY and ISOLATED in the 'astro_deepdive' R2 prefix: it NEVER touches gate.py / the scheduler /
# the trial-ledger / the money path. See docs/research/astro_final_deepdive_PLAN.md for the pre-registered
# design + honest (near-certain null) expected outcome + cost.
#
# Public surface (re-exported for convenience):
#   - CostTracker          : container-hour budget watchdog (ALERT + STOP at 0.8×budget; Slack-or-print)
#   - DeepDiveConfig       : the run knobs (download_spec, n_configs, n_perm, fee_bps, modal_budget_usd)
#   - run_astro_deepdive_modal(config) : the 5-phase orchestrator (PHASE0 validate … PHASE4 deflate)

from __future__ import annotations

from .cost_tracker import CostTracker

__all__ = ["CostTracker"]
