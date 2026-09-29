---
name: deploy-check
description: The pre-push gate — run `pnpm verify` and confirm the tree is green and coherent before pushing (push = deploy). Use before every push.
---

# deploy-check

**Push = deploy.** Railway (engine) and Vercel (web) auto-deploy on push to the working branch. One trigger only: `git push`. Never also run `railway up` / `vercel deploy` (double-deploy race).

## Steps
1. **Run the dev gate:** `pnpm verify` = `naming:check && contracts:generate && engine:test && typecheck`. All offline, no keys required.
2. **Contracts in sync:** `contracts:generate` must produce NO diff you didn't intend — web types are generated from the engine OpenAPI, never hand-typed. If it changed, commit the regenerated `@cosmu/contracts-ts`.
3. **Naming guard green:** `pnpm naming:check` — no dead vocabulary (the lifecycle is LOCKED).
4. **Tests green:** the full `engine:test` passes locally (heavy finder/ML tests need real memory — run them on the dev machine, not a tiny container).
5. **No secrets staged:** `git diff --cached` carries no keys; tokens live in gitignored `.env.local`.

## Verify
- `pnpm verify` exits 0.
- Then, and only then: `git push`. Watch Railway `/health` and the Vercel build.
