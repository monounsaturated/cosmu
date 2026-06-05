# Cosmu — Compute & CI Plan (where heavy work runs)

> **Problem:** the dev loop is slow because the full gate (`pnpm verify` = engine tests + typecheck + `next build`) gets run on the operator's M2 (OOMs) or in a cloud Claude session (also slow). Heavy quant compute (backtests, ML, gate sweeps) has no dedicated home yet.
> **Principle (VISION §0/§12):** buy commodity compute, build only the differentiator. Don't rent an idle box; use bursty, scale-to-zero compute driven by Claude Code commands.

## Decision (2026-06-05): Modal for the heavy lane, Railway stays for the backend (hybrid)

Evaluated **Modal vs Fly.io vs RunPod vs all-Railway**, scored on: leanest · cheapest · most powerful · vision-aligned · **EU-accessible (operator is France-based)** · easy to manage.

**Verdict — keep the hybrid. It's the simplest AND smartest split:**
- **Backend (engine API + 4h cron) STAYS on Railway.** Light, always-on, **warm (no cold-start)**, already wired, git-push deploy, EU region available, ~$5–20/mo. Re-platforming a working service onto a batch platform buys nothing and adds cold-start latency on the user-facing API.
- **Heavy bursty lane (backtests · gate sweeps · ML train · agent sandbox) → Modal.** Per-second, scale-to-zero (~$0 idle), image-as-code (no dep drift from CI), invoked via `modal run` from Claude Code or triggered by the engine. **$30/mo free Starter credits cover the R&D phase.**
- **Clean seam, not added complexity.** Railway runs the loop/API exactly as today; Modal is "a command that runs a heavy job." Each tool does only what it's best at — that's easier to manage than rebuilding the backend on a batch platform.

**Why Modal over the alternatives for the heavy lane:**
- *vs Fly.io* — Fly is services-first; its batch lane is hand-managed, no free tier (since 2024), bills stopped volumes. Loses on the one lane we actually need.
- *vs RunPod* — RunPod is GPU-*pod*-centric (great for cheap sustained GPU, explicit EU regions incl. **France**). Our heavy lane is **CPU-bound batch + sandbox**, where Modal's serverless DX wins. **Revisit RunPod only if/when post-edge ML training becomes GPU-hour-dominated** and Modal's GPU multiplier gets pricey.
- *vs all-Railway* — no real batch lane; resource-priced always-on means idle costs money.

**EU note (operator is France-based):** keep **Railway + Supabase in an EU region** (latency + residency). Modal jobs are batch so compute-location latency is low-stakes, and market-bar data carries no PII — but **verify Modal's EU region pinning at modal.com/docs** before any residency-sensitive use. (Polymarket's France ANJ geoblock is an operator legality call — VISION §7/§15 — unrelated to compute.)

**Stack:** Railway (backend) · Modal (heavy compute) · Supabase (data, EU) · Vercel (web) · OpenRouter (loop LLM) · Claude Max sub (coding-agent compute).

## Current spend (EU, R&D phase) — keep this DYNAMIC
Unit rates below are **reasoning inputs only**; the **live Costs card / `costs` table in the app is the canonical, dynamic source of truth** for actual spend (cost/ROI writers already wired). Re-check rates when making a scale decision.

| Vendor | Rate (2026) | R&D-phase cash |
|--------|-------------|----------------|
| **Railway** (backend) | $5/mo Hobby + $20/vCPU-mo + $10/GB-mo, billed/sec | ~$5–20/mo (light, mostly idle) |
| **Modal** (heavy lane) | $0.0000131/core/s + $0.0000022/GiB/s (×3.75 non-preempt US/EU); **$30/mo free credits** | ~$0 during R&D |
| **Supabase** (data) | Free or Pro $25/mo (pgvector) | $0–25/mo |
| **Vercel** (web) | Free / Pro $20/mo | $0–20/mo |
| **OpenRouter** (loop LLM) | `:free` tier by default | ~$0 |
| **Claude Max** (coding-agent compute) | flat sub | $100/mo (already paid; *is* the heavy-LLM lane) |

**Net new infra cash ≈ $5–45/mo** on top of the existing Max sub. Fly/RunPod would add cost without earning their lane today.

## Setup: how Modal is wired (where keys go) — LIVE as of 2026-06-05

The lane is `apps/engine/remote/app.py` (a Modal app) + `scripts/sync_modal_secret.py`. It runs the **same**
engine commands the Railway crons run (`cosmu.master.scheduler`, `cosmu.research.loop`, `cosmu.orchestrator.loop`)
on a beefier, scale-to-zero box, writing to the **same Supabase**.

**Three places keys live (keep them in sync, .env.local is the source):**

| Where | Holds | Why |
|-------|-------|-----|
| **`.env.local`** (gitignored) | everything for local dev **+ `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`** | the single source you copy from; lets `modal run` auth in a cloud/Claude session |
| **Railway env** (dashboard) | backend runtime secrets (DATABASE_URL, XAI_API_KEY, …) | already set — the always-on API + crons |
| **Modal secret `cosmu-engine`** | the runtime secrets the Modal jobs read (+ `APP_ENV=production`) | injected into the job's env; **synced from .env.local**, never hand-typed |

**One-time setup:**
1. `pip install -e "apps/engine[remote]"` (or `pip install modal`) — the client, only where you run jobs.
2. `modal setup` (writes `~/.modal.toml`) **or** put `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` in `.env.local` (from https://modal.com/settings/tokens) for non-interactive auth.
3. `pnpm modal:secret` (= `python3 scripts/sync_modal_secret.py`) — pushes DATABASE_URL/XAI/FRED/… from `.env.local` into the Modal secret. Re-run whenever a key changes.

**Run a heavy job (Claude or you):**
- `pnpm modal:gate` — full cohort + deterministic gate + ML ordering on real data (the survival model trains here as labels accrue).
- `pnpm modal:ingest` — free-data ingest + cross-asset gate.
- `modal run apps/engine/remote/app.py --job run_module --module cosmu.research.gate` — escape hatch for any engine module.

**Stays true to the rails:** these are the deterministic research/ingest entrypoints — no live orders, no LLM in the gate/money path (the engine enforces that). Modal is just more compute.

## The two compute tiers (different problems, different homes)

| Tier | What | Best home | How Claude drives it |
|------|------|-----------|----------------------|
| **CI / verify** (tests · typecheck · `next build`) | bursty, per-change, ~minutes | **GitHub Actions** (`.github/workflows/verify.yml` — already exists, runs on every branch push + PRs to main) | push branch → poll `actions_list` / `pull_request_read get_check_runs` via the GitHub MCP until green/red |
| **Heavy research** (backtests · ML train · gate/WFO sweeps — once vectorbt/Nautilus land) | very bursty, CPU/RAM-hungry, scale-to-zero | **Modal** (the VISION's pick, §4/§12) | `modal run scripts/<job>.py` as a Bash command; results stream back |

**Today the engine is light** (deps: ccxt/fastapi/pydantic/sqlalchemy; ~80 fast hermetic test files). So the current slowness is almost entirely **JS install + `next build`**, NOT Python. The Modal tier matters once the heavy quant deps are pulling weight; the CI tier is the pain *now*.

## Why NOT a persistent Fly/Railway dev box
Renting a beefy always-on box is the worst of the options: you pay for it idle, you hand-maintain its deps (they drift from CI and break differently), and it doesn't auto-scale for a big sweep. **Modal beats it** — scale-to-zero (≈$0 idle), beefy on demand, image defined in code (deps can't drift), per-second billing. Fly is a *services* platform first; its batch lane is hand-managed and it has no free tier — so it loses to Modal on the heavy lane *and* doesn't earn its place as a vendor. The backend that genuinely needs always-on hosting (engine API + cron) stays on Railway, which is light and warm; Modal is added only for the bursty heavy jobs (see Decision above — hybrid).

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
A standing Fly/Railway compute box; a Fly migration of the services (lateral move, new vendor not in VISION); RunPod for now (GPU-pod-centric — post-edge GPU-training option only, see Decision); re-platforming the working Railway backend onto a batch platform; TradingView/QuantConnect as compute runners (those are idea scratchpads, not CI/ML infra).
