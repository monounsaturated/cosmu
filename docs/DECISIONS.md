# COSMU — Decisions & Verdicts (append-only log)

The single durable trace of *what we concluded and why*. **Append-only** — never edit past entries; to
reverse one, add a new entry with `Supersedes:`. One entry = one decision or verdict. Reverse-chronological.
Memory = working set · this = reasoning history · the one live plan (HANDOFF_NEXT.md) = what's next.

> Format: **Date · Title** — Decision. *Why* (2–3 lines). *Evidence* (file/run/commit). *Status* (live | superseded by …).

---

**2026-06-06 · FIRST honest edge verdict (T6) — FAIL on liquid majors · signal REAL · harness BLESSED** — No member survived `promote_cohort` BH-FDR (q=0.10) on the 30-symbol liquid universe (2023-09→2026-06). btc-social risk-on overlay: deflated Sharpe **0.849** (<0.95 floor), PBO 0.014 (not overfit), **net +0.178 after fees** — but fails buy-and-hold AND the purged/embargoed OOS holdout (doesn't generalize). **All 3 disconfirmers PASS** (beats flat baseline 0.381, beats equal-turnover BTC-price regime 0.570, dwell-matched placebo 0.606 doesn't reproduce) → the tilt carries **real information, sub-threshold edge.** Low-turnover confirmed (10.6 flips/yr). Polymarket: 0 trades — floor band [0.45,0.70] mis-calibrated to odds that live ~0.28 (NOT a wiring bug; 400 points joined). *Trust-audit: trustworthy=YES* (routed through BH-FDR, never the leaky cross-asset path; real bars + production Postgres, no synthetic). **Read: "no gate-clearing edge in MAJORS," NOT "no edge"/"stop."** *Why it matters:* the harness is honest end-to-end and the Gate rejected an interesting-but-weak signal — the moat working. *Next:* pivot the SAME family to smaller-cap/niche + recalibrate the pm floor. *Evidence:* run `wlxvmwyf9`, branch `engine/honest-rerun-harness`, 950 tests green. *Status: live.*

**2026-06-06 · State-of-COSMU audit** — Core is coherent; the mess is doc/process sprawl + two code seams + re-planning, not the engine. *Why:* 5-dimension read-only audit — 905 tests/0 skips, intent headers on 166/177 modules, UI uses progressive disclosure (not a dump). Real hazards = dual simulators, half-migrated data layer, BTC/ETH-only prod ingest. *Evidence:* `docs/reports/state-of-cosmu-2026-06-06.md`. *Status: live.*

**2026-06-06 · Dual-simulator hazard** — `research/gate.py::_simulate` (5bps flat, no impact, fixed stops) disagrees with `data/backtest.py::run_strategy_backtest` (5bps+50bps impact, purged splits) → the Gate can bless what the live loop can't trade. **Unify before trusting any verdict.** *Evidence:* audit above. *Status: OPEN (priority #2).*

**2026-06-06 · Feature-wiring + honesty-leak gaps** — Only ~6/40 features are COMPUTED in the backtest (most authored specs trade 0 times); the UI EdgeGate card runs on SYNTHETIC data. Verdicts can be silently empty or fake. *Status: OPEN (priority #3-4).*

**2026-06-06 · Polymarket arm is viable** — `fetch polymarket_clob` landed 388 daily rows over ~1yr (pm_implied_prob / pm_prob_velocity). Re-run can include it as a BH-FDR family member. *Status: live.*

**2026-06-06 · "Spot-only wall" is SUSPECT** — The 2026-06-05 "powered FAILs → spot-only falsified" conclusion ran on a BROKEN harness (empty bars, fake netflow, bad funding). Re-run on the honest harness before treating spot-only as a wall. *Supersedes: 2026-06-05 spot-only-wall-confirmed.* *Status: live.*

**2026-06-06 · Honest harness landed** — Killed fake tier-0 `exchange_netflow`, fixed funding accrual + FRED first-release vintage, added registry⊆routable guard, finder forward-test clock, usable-web route reconciliation. *Evidence:* PRs #130/#131/#132, main `3522c00`; full suite 942 green (`02ccf6a` hermetic-test fix). *Status: live.*

**2026-06-06 · Compute placement standard (LOCKED)** — Build/test → local worktree; heavy >10min compute + long services → Modal (live, secret synced); always-on/cron → Railway; orchestration/ultracode → the local session (surgical). *Evidence:* `memory/compute_placement.md`. *Status: live.*

**2026-06-06 · GitHub Actions PR-CI disabled** — No branch protection ⇒ PR CI never gated merges; it was pure cost. Verify in agent sandboxes + local. Manual `workflow_dispatch` kept. *Evidence:* `ff4b03c`, `.github/workflows/verify.yml`. *Status: live.*
