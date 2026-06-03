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
3. **Verify** `pnpm verify` passes (naming + contracts + tests + typecheck + build).
4. **Contracts:** any `@cosmu/contracts-ts` diff is intentional (real OpenAPI change, not just `ValidationError` shape noise).
5. **Check** `next-env.d.ts` is **not** modified.
6. **Report:** PASS/FAIL with specific issues. **Blocking** = must fix before merge. **Advisory** = nice to fix.

## Verify
- Verdict is explicit PASS or FAIL; each issue is tagged blocking or advisory and cites a file:line.
- `pnpm verify` result is stated (green/red).
