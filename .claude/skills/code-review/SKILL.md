---
name: code-review
description: Pre-merge quality gate — review the PR diff for trading/correctness traps, magic numbers, synthetic-data leaks, dead code, and security, then report PASS/FAIL with blocking vs advisory issues. Use before merging a branch.
---

# code-review

Catch the things that break this machine before they land. Read the diff with Cosmu's invariants in mind (see `AGENTS.md` — Non-negotiables).

## Steps
1. **Read the diff:** `git diff main...HEAD`.
2. **Check for traps:**
   - **Look-ahead / survivorship bias** — point-in-time joins only; the graveyard stays.
   - **Magic numbers** not lifted into `param_space`.
   - **Synthetic-data leak** — `edge_market` fixtures must never reach the app or prod path (CI/tests only).
   - **Dead imports / unused code**; **missing tests** for new behavior.
   - **Security** — staged secrets, injection, unsafe shell/SQL.
   - **LLM in the money path** — the gate/scoring/funding path must stay deterministic.
   - **Noise-vs-pattern (strategy/gate/research diffs)** — run the `docs/research/RESEARCH_LESSONS.md` §3 checklist as explicit PASS/FAIL when the diff touches a strategy/gate/research path:
     - *Mechanism stated?* the `rationale` is a real disconfirmable WHY, not just non-empty (non-emptiness is machine-checked by `validate_spec` — confirm it FIRED and is substantive).
     - *Net-of-fees > 0?* the edge survives real per-venue fees + slippage (machine-priced — confirm cost columns are populated, not zeroed).
     - *Proper null?* cyclic/seasonal features disconfirmed with a phase/label shuffle, not fake-random dates.
     - *Deflated at the TRUE trial count?* neither an inflated grid count (over-deflation) nor a raw-count leak.
     - *Train→OOS rank consistent?* a **negative** `rank_consistency` on the verdict is a curve-fit smell — block a survivor that ships with it.
     - *§4 PIT law* — a revising/backfilled source is ingested live-forward (`available_at` = fetch time), never trusted from backfill.
3. **Verify** `pnpm verify` passes (naming + contracts + tests + typecheck + build).
4. **Contracts:** any `@cosmu/contracts-ts` diff is intentional (real OpenAPI change, not just `ValidationError` shape noise).
5. **Check** `next-env.d.ts` is **not** modified.
6. **Report:** PASS/FAIL with specific issues. **Blocking** = must fix before merge. **Advisory** = nice to fix.

## Verify
- Verdict is explicit PASS or FAIL; each issue is tagged blocking or advisory and cites a file:line.
- `pnpm verify` result is stated (green/red).
