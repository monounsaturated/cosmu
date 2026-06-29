# Capital-path gap fixes — cell-scoped arming + surfaced lot_size rejection (2026-06-28)

Follow-up to the end-to-end live-arming dry-run (PR #467, `docs/reports/live-arming-dryrun-2026-06-28.md`), which
proved the capital path fires but surfaced **two silent gaps**. Both are fixed here. This is a **DRAFT** money-path-
adjacent change — **DO NOT MERGE yet**; it is an autonomous-run POC and must be reviewed carefully.

The FAIL-SAFE invariant is preserved throughout: a change may make a *legitimately-proven* cell armable, but **never**
makes an unproven cell armable, never over-deploys, never moves real money, and never weakens the human-arming
interlock (`confirm=True` still required; toggle + keys + gate + caps + no-kill-switch interlocks untouched).

---

## GAP 1 (HIGH, was fail-safe) — arming eligibility is now CELL-scoped (BRUT triple armable)

**Problem.** `live_launch` called `live_eligibility_verdict(store, version_id, reference)` with **no symbol/venue**, so
it read the **version-only** forward evidence. But the forward-evidence readers are CELL-scoped (BRUT
`version:symbol:venue`), and post-migration (`tracks_has_cell_columns=True`) the cell readers have **no** version-only
fallback. Once `tracks` is genuinely re-keyed per triple, a cell proven ONLY under its BRUT key would read ELIGIBLE
cell-scoped but be **UNARMABLE** through `live_launch`. (It fails safe — blocks — but breaks legitimate arming.)

**Fix** (`cosmu/api/routers/live.py`, `live_launch`):
1. Thread `request.symbol` / `request.venue_id` into `live_eligibility_verdict(...)` and `paper_clock_origin(...)`
   so the arming path evaluates the **same** BRUT cell key the per-combo model proves. This is the new capability:
   a cell proven only under its own cell key is now armable.
2. **Safe version-scope fallback** (the "only where still correct" half). The funder TODAY still writes forward
   evidence version-only (`master/zero_capital.open_zero_capital_track`: `track_opened ref_id=version`, a `tracks`
   row with no symbol/venue) while the live `tracks` table already carries the BRUT columns. So a cell-scoped read of
   a currently-funded cell finds nothing and would block a legitimately-proven arm. To bridge until the funder is
   re-keyed, **if** the cell-scoped verdict is not eligible, fall back to the version-scoped verdict — **but only when
   `attribution_confirmed`** (the version's one funded `positions` cell IS the requested `symbol@venue`, proven from
   the existing attribution guard). That makes the version-only evidence provably THIS cell's evidence.

**Why it cannot over-arm (fail-safe analysis):**
- The fallback requires a real funded position **matching the request**. No funded cell → attribution unconfirmed →
  fallback disabled → the cell-scoped block stands. (Pinned by
  `test_gap1_failsafe_version_only_proof_without_funded_position_is_blocked`, verified load-bearing by removing the
  `attribution_confirmed` guard → the test fails (over-arms), restoring it → passes.)
- The version-scoped verdict is the **exact** gate that arms in prod today, so the fallback is at most today's
  behaviour — never weaker.
- The attribution guard already refuses a `symbol`/`venue` that mismatches the funded cell, so we only ever evaluate
  the cell whose proof we are about to risk money on.
- Regime gate + the 5 execution interlocks + `confirm=True` still apply to whichever verdict arms.
- Net: this **widens which PROVEN cells can arm, never which UNPROVEN cells can.**

**Also updated:** `tests/test_live_api.py::_seed_survivor` now registers the flat funded position the real funder
always writes (`Portfolio.register_track`), so the test reflects prod and exercises the attribution-confirmed
fallback. (Without it the cell-scoped read finds nothing and correctly fail-safe-blocks — i.e. the seed was simply
under-specified relative to prod.)

---

## GAP 2 (MEDIUM, was silent) — a lot_size rejection on a high-priced ETF is now LOUD + audited

**Problem.** With `sim_track_capital = $1000`, an arm on a high-priced ETF (e.g. SPY ~$550) sizes to **< 1 whole
share**; the gauntlet rejects it (`lot_size`), so the arm opens **no position** — and the executor reported
`opened=0` while the rejection was buried in a generic `order_rejected` event among routine sim rejects. A confirmed
arm produced nothing, silently.

**Fix** (`cosmu/orchestrator/paper_step.py`):
- `StepReport` gains `rejected: int` and `rejections: list[dict]` (additive, defaulted — no consumer breaks). A
  rejected ENTRY is no longer silently dropped: it is **counted and recorded** in the tick report.
- A **live-armed** entry that the gauntlet rejected now emits a distinct, loud `arm_opened_nothing` audit event
  (symbol, venue, issues, qty, price) so the operator knows a CONFIRMED ARM opened nothing and exactly why
  (`lot_size`, `combo_wallet_spent`, etc.) — separate from routine sim rejects. The order path's own
  `order_rejected` row is still written too (defence in depth).
- The `paper_stepped` summary event now carries `rejected`.

This is the REQUIRED minimum from the brief: **no silent no-op — the failure is loud + audited.** (Alpaca fractional
shares were considered as the "better fix" but deliberately NOT enabled here: it changes real execution sizing on the
money path and belongs in its own reviewed change. The loud-rejection fix is the safe, surgical one.)

**Design note.** The surfacing lives in the executor (where the rejection actually happens, with the real mark and
real sizing) rather than as a duplicate arm-time pre-check in `live_launch`. That keeps a single source of truth for
sizing and avoids a parallel sizing path that could drift from the executor.

---

## Tests (acceptance) — `apps/engine/tests/test_capital_path_gaps.py` (8 tests, reuse `conftest.seed_track_snapshots`)

GAP 1:
- `test_gap1_cell_keyed_only_proof_is_eligible_cell_scoped` — cell-scoped verdict ELIGIBLE on cell-key-only proof;
  the version-only read sees nothing (proves the proof is cell-keyed).
- `test_gap1_cell_keyed_only_proof_is_armable_via_live_launch` — **THE FIX**: such a cell now arms (status='live',
  promotion frozen). Verified load-bearing (reverting the symbol/venue threading → armed=False, "no proven regime").
- `test_gap1_failsafe_unproven_cell_is_still_blocked` — no forward evidence under either key → blocked.
- `test_gap1_legacy_version_only_proof_arms_via_attribution_confirmed_fallback` — legacy version-only proof + a
  matching funded position still arms (prod-shape bridge).
- `test_gap1_failsafe_version_only_proof_without_funded_position_is_blocked` — version-only proof but **no** matching
  funded position → fallback disabled → blocked. (Verified load-bearing.)
- `test_gap1_failsafe_confirm_interlock_still_required` — `confirm=False` never arms.

GAP 2:
- `test_gap2_high_priced_etf_lot_size_reject_is_surfaced_not_silent` — a ~$1200 ETF at $1000/track: `opened=0`,
  nothing held, nothing routed, BUT `report.rejected==1` + `report.rejections` populated + a loud `arm_opened_nothing`
  event with `lot_size`. (Verified load-bearing.)
- `test_gap2_low_priced_etf_opens_cleanly_no_false_rejection` — control: a ~$82 ETF opens cleanly, no false alarm.

**Run:** `cd apps/engine && python3 -m pytest tests/test_capital_path_gaps.py tests/test_live_api.py -q`
(27 passed; the full affected suite — live/eligibility/lifecycle/capital/executor — is also green.)

---

## Honest limitations

- The version-scope **fallback is a temporary bridge** for the legacy funder, not the end state. The clean fix is to
  re-key the funder (`open_zero_capital_track`) to write forward evidence under the BRUT cell key (and the `tracks`
  row with `symbol`/`venue_id`); once done, the fallback can be removed and arming is purely cell-scoped. That is a
  larger, separate change.
- GAP 2 surfaces the rejection but does **not** fix sizing — a high-priced ETF at the current $1000 per-track capital
  still opens nothing; the operator is now loudly told so. Enabling fractional shares (Alpaca) or raising per-cell
  capital for equity arms is the follow-up that would actually let such a cell trade.
- All tests are hermetic SIM/testnet (throwaway sqlite, `_env_file=None`, in-process stub adapter, conftest network
  guard). No real venue, key, or DB was touched. This is a DRAFT PR — not merged.
