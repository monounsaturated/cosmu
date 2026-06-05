# Cosmu — Compute & CI Plan (where heavy work runs)

> **Problem:** the dev loop is slow because the full gate (`pnpm verify` = engine tests + typecheck + `next build`) gets run on the operator's M2 (OOMs) or in a cloud Claude session (also slow). Heavy quant compute (backtests, ML, gate sweeps) has no dedicated home yet.
> **Principle (VISION §0/§12):** buy commodity compute, build only the differentiator. Don't rent an idle box; use bursty, scale-to-zero compute driven by Claude Code commands.

## The two compute tiers (different problems, different homes)

| Tier | What | Best home | How Claude drives it |
|------|------|-----------|----------------------|
| **CI / verify** (tests · typecheck · `next build`) | bursty, per-change, ~minutes | **GitHub Actions** (`.github/workflows/verify.yml` — already exists, runs on every branch push + PRs to main) | push branch → poll `actions_list` / `pull_request_read get_check_runs` via the GitHub MCP until green/red |
| **Heavy research** (backtests · ML train · gate/WFO sweeps — once vectorbt/Nautilus land) | very bursty, CPU/RAM-hungry, scale-to-zero | **Modal** (the VISION's pick, §4/§12) | `modal run scripts/<job>.py` as a Bash command; results stream back |

**Today the engine is light** (deps: ccxt/fastapi/pydantic/sqlalchemy; ~80 fast hermetic test files). So the current slowness is almost entirely **JS install + `next build`**, NOT Python. The Modal tier matters once the heavy quant deps are pulling weight; the CI tier is the pain *now*.

## Why NOT a persistent Fly/Railway dev box
Renting a beefy always-on box is the worst of the options: you pay for it idle, you hand-maintain its deps (they drift from CI and break differently), and it doesn't auto-scale for a big sweep. **Modal beats it** — scale-to-zero (≈$0 idle), beefy on demand, image defined in code (deps can't drift), per-second billing. Fly/Railway are for *services* (the engine API + crons already live on Railway), not bursty jobs.

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
A standing Fly/Railway compute box; TradingView/QuantConnect as compute runners (those are idea scratchpads, not CI/ML infra).

---

## DECISION (2026-06-05): keep Railway + ADD Modal for heavy compute
Operator decision: **Railway stays** (always-on engine API + the autonomous tick/crons), and we **add Modal** as the scale-to-zero lane for heavy bursts (cohort sweeps, ML train, big backfills). No Fly.io. Concrete build steps for the next session:
1. `pip install modal` + `modal token new` (operator creates a Modal account; ~$0 idle, per-second billing).
2. Add `apps/engine/remote/modal_app.py`: one Modal `App` + an image built from `apps/engine[dev]`; functions = `run_tick`, `run_cohort`/sweep, `backfill`. Each reads `DATABASE_URL` from a Modal secret so results land in prod Postgres.
3. Drive from Claude Code: `modal run apps/engine/remote/modal_app.py::run_cohort -- --n 200`. Scale-to-zero → $0 when idle.
4. Keep the engine's deps importable on Modal by reusing the same `pyproject` extras — no dep drift.

## Operational findings from the 2026-06-05 session (runbook)
- **The autonomous tick is NOT scheduled.** No `Procfile`/`railway.json`/cron/in-process scheduler exists in the repo despite "4h cron" comments. **Until a Railway cron is wired, the tick never runs on its own** → the app has ingest data but no strategies/tracks. Wire a Railway cron service running `python -m cosmu.master.scheduler` every 4h.
- **Run a tick manually (writes prod DB, no HTTP timeout):** `railway run env PYTHONPATH=apps/engine python3 -m cosmu.master.scheduler --n 6`. Confirmed working: emits `authored=… gated_passed=… funded=… survivors=…`.
- **`POST /autonomy/tick` returns `upstream error`** — the endpoint runs the tick synchronously and exceeds Railway's gateway timeout. Fix: make it async (return 202 + run in background), or just use the CLI above.
- **`manage_data backfill bars` returned 0** on the Mac because `ccxt` isn't installed there (`railway run` uses local Python); funding worked because it uses stdlib `urllib`. Fixed on branch `claude/fix-bars-rest-fallback` (keyless Binance REST fallback). NB: bars are a local **file cache**, not Postgres — a local backfill can't populate the deployed app; the deployed engine fetches its own bars (REST fallback, no ccxt needed).
- **Verify is the slow gate (~16 min).** Compute Phase 1 (parallelize `verify.yml` jobs + cache pnpm & `.next/cache`) is the cheap fix; not yet done.
