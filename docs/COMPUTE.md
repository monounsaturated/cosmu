# Cosmu — Compute & CI Plan (where heavy work runs)

> **Problem:** the dev loop is slow because the full gate (`pnpm verify` = engine tests + typecheck + `next build`) gets run on the operator's M2 (OOMs) or in a cloud Claude session (also slow). Heavy quant compute (backtests, ML, gate sweeps) has no dedicated home yet.
> **Principle (VISION §0/§12):** buy commodity compute, build only the differentiator. Don't rent an idle box; use bursty, scale-to-zero compute driven by Claude Code commands.

## Decision (2026-06-05): Modal is the single compute platform

Evaluated **Modal vs Fly.io vs staying on Railway** against: leanest · cheapest · most powerful · vision-aligned · fewest platforms to manage.

**Verdict — Modal, and use it to RETIRE Railway (not add a vendor). Fly is rejected.**
- **Heavy research is the bottleneck**, and it is exactly Modal's sweet spot (per-second, scale-to-zero, image-as-code so deps can't drift from CI, GPU on demand). Fly's Machines can run batch but you hand-manage lifecycle — it's a services platform first. Railway has no real batch lane at all.
- **Modal also absorbs the services** the engine needs: the API as a Modal ASGI web endpoint, the 4h research loop as a `@modal.cron` scheduled function. So one platform covers API + cron + backtests + ML + sandbox.
- **Cost for our bursty profile:** Modal's $30/mo free Starter credits realistically cover the whole R&D/forward-test phase; the US non-preemptible 3.75× multiplier only bites on *sustained* 24/7 load — the post-edge V2 moment VISION §12 already defers ("vertical first, then a worker pool when alpha justifies it"). Fly killed its free tier (2024), bills volumes even on stopped machines, and drifts to the $99/mo performance tier for the lane it's worst at. Consolidating drops Railway (~$25/mo) and runs ~$0 cash during R&D.
- **Vision fit:** VISION §4/§12 already commit to "E2B or **Modal**" for sandbox/ML. Fly appears nowhere in the memo. Modal-as-one-platform is strictly *more* aligned than today's Railway+Modal split.

**Target stack:** Modal (all compute) · Supabase (data) · Vercel (web) · OpenRouter (models). Each irreplaceable; nothing idle.

**Honest caveat:** Modal web endpoints cold-start (~seconds) after idle. Fine for a personal monitoring cockpit; if the API feels laggy, pin `min_containers=1` (small cost) or leave just the API on Railway. Everything *heavy* lives on Modal regardless.

## The two compute tiers (different problems, different homes)

| Tier | What | Best home | How Claude drives it |
|------|------|-----------|----------------------|
| **CI / verify** (tests · typecheck · `next build`) | bursty, per-change, ~minutes | **GitHub Actions** (`.github/workflows/verify.yml` — already exists, runs on every branch push + PRs to main) | push branch → poll `actions_list` / `pull_request_read get_check_runs` via the GitHub MCP until green/red |
| **Heavy research** (backtests · ML train · gate/WFO sweeps — once vectorbt/Nautilus land) | very bursty, CPU/RAM-hungry, scale-to-zero | **Modal** (the VISION's pick, §4/§12) | `modal run scripts/<job>.py` as a Bash command; results stream back |

**Today the engine is light** (deps: ccxt/fastapi/pydantic/sqlalchemy; ~80 fast hermetic test files). So the current slowness is almost entirely **JS install + `next build`**, NOT Python. The Modal tier matters once the heavy quant deps are pulling weight; the CI tier is the pain *now*.

## Why NOT a persistent Fly/Railway dev box
Renting a beefy always-on box is the worst of the options: you pay for it idle, you hand-maintain its deps (they drift from CI and break differently), and it doesn't auto-scale for a big sweep. **Modal beats it** — scale-to-zero (≈$0 idle), beefy on demand, image defined in code (deps can't drift), per-second billing. Fly is a *services* platform first; its batch lane is hand-managed and it has no free tier — so it loses to Modal on the heavy lane *and* doesn't earn its place as a second vendor (see Decision above: Modal also takes the services, so Railway is retired rather than swapped for Fly).

## The critical CI caveat (read this)
**Push = deploy.** Railway + Vercel auto-deploy on every push to the working branch, and `verify.yml` runs in **parallel** with that deploy, not as a gate before it. So "let CI verify on push to main" does **not** protect main from deploying broken.
**The real gate is PR CI _before_ merge.** A merge train must:
1. integrate locally → push the **integration branch** (not main) → CI runs the full verify there;
2. only merge to main once that branch's CI is **green**;
3. (the merge to main re-runs CI + deploys, now known-good).
This is how the 2026-06-04 7-PR merge train was landed.

## Phase 1 — kill inner-loop slowness (cheap, no new vendor)
1. **Don't run full `verify` locally/in-session.** Use targeted tests while developing (`pytest -k …`, skip `next build`); let GitHub Actions be the real gate on push.
2. **Parallelize `verify.yml`** into independent jobs (`engine:test` ∥ `typecheck` ∥ `build`) so wall-clock = slowest single job, not the sum.
3. **Cache** the pnpm store and the **Next.js build cache** (`.next/cache`) — the single biggest `next build` win; pip cache is already wired.
4. **A `pnpm verify:remote` command** Claude runs: push branch → trigger workflow → tail logs via the GitHub MCP until green/red. Verdict without ever building locally.

## Phase 2 — heavy compute lane (when quant deps land, or earlier if wanted)
5. A thin `apps/engine/remote/` Modal app: one function = "run the Gate / a backtest / an ML train" on a defined image. Claude invokes `modal run …`; results stream to the session. Scale-to-zero → $0 idle. This is the same E2B/Modal sandbox the VISION already commits to, wired earlier for dev speed.

## Skip
A standing Fly/Railway compute box; a Fly migration of the services (lateral move, new vendor not in VISION — Modal absorbs them instead, see Decision); TradingView/QuantConnect as compute runners (those are idea scratchpads, not CI/ML infra).
