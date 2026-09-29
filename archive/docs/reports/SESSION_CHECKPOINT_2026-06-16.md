# Session checkpoint — 2026-06-16 (autonomous money-path + A–H fan-out)

**Resume point.** main @ `847dee4`. **8 of 9 tasks merged** (TASK I + A,B,C,D,E,F). **Only TASK G remains.**

## ✅ Merged to main (verified green before each merge)

| Task | PR | What landed |
|------|----|-------------|
| **I — money path** | #258 | Operational ignition: drove a real gate-passed entry through `execute_orders` + the **real** `AlpacaExecutionAdapter` (paper keys) — the order **really hit Alpaca's paper API** (real venue order id, `status=accepted`), `is_paper=0` (all 43 prior fills were `is_paper=1`). Fixed a real bug: `_live_venue` booked Alpaca-`paper` orders under `venue="sim"` despite `is_paper=0` → normalized `paper→testnet` so `step_tracks.held_live` manages them. +3 tests. The `:192` interlock and `_resolve_live_adapters` SIM-only default are untouched. |
| **A — venue depth** | #267 | Screen now charges per-venue `slippage_bps`/`impact_bps` (was global 5/50). **NONE flip pass→fail** — Gate is correctly strict (~0 survivors at 5/50) and every inbox spec *executes* on `binance`; thin-book protection is installed for when a spec actually trades on Polymarket/etc. `research/gate.py` + `DEFAULT_*` untouched → cost-parity preserved. +2 tests. |
| **B — Modal sweep** | #264 | `matrix_cell` + `sweep` `.starmap` entrypoint in `remote/app.py`, `pnpm modal:sweep`, broad 38-asset default universe, +6 tests. |
| **C — lab batch** | #265 | `cosmu.lab.batch` one-command generate→validate→gate; theme angles 8→32, feature hints ~14→55; +9 tests. |
| **D — budget truth** | #261 | Real LLM-cost table (`:free`→$0), fees rolled into `costs` as `category="trading"`, dated spend series, fee display in go-live modal. +289 test lines. (Dropped D's separate Modal cron — main already folded cost-refresh into the combined `tick` to stay under Modal Free's 5-schedule cap.) |
| **E — research uses everything** | #263 | `gather_context` reads ingested `twitter_sentiment` (PIT, $0); de-hardcoded Tavily query; `xai_live` tool; registered `twitter_sentiment`; quarantined gtrends + neutralized influencer dup. +341 test lines. |
| **F — web equity curve** | #266 | Backtest gross/net equity overlay + drawdown band; `max_dd` in the table (new `LeaderboardRow` field, contracts regenerated); hid dead/empty panels. |

## ▶️ REMAINING: TASK G — gate hardening (NOT started)

Full spec: `docs/LOCAL_AGENT_PROMPT.md` → **TASK G**. Branch `fix/gate-hardening`. Engine-only. It **changes gate verdicts** (items 1 & 3) — review flipped pass/fail before merge, like A. Items:
1. `master/verdict_log.py:44,54` — `data_source` default `"live"`→`"unknown"`.
2. `research/llm_narrative_cohort.py` — placebo over ~20 seeds (require DSR > placebo 95th pct).
3. `evolution/loop.py` — apply `finder.py:62 _MIN_TRADES_PER_SYMBOL` in screening.
4. `research/gate.py` — route `_run_variant` through `_purged_embargoed_split`.
5. CI test: no `research/*_arm.py` writes literal `passed_gates:1`/`holdout_passed:1` without a computed verdict.
> Check overlap: main's recent deploy-hardening commits already touched arm self-stamps/DSR floors — confirm item 5 isn't already done.

### To resume (one step):
Launch one agent on `fix/gate-hardening` per the TASK G spec with the **anti-hang contract** (below), then verify + merge. That completes all 9.

## ⚠️ Two standing facts

1. **First real € (TASK I 1c) is BLOCKED on a missing credential, not the regime gate.** `.env.local` has `ALPACA_PAPER_API_KEY/SECRET` only — **no live `ALPACA_API_KEY`/`ALPACA_API_SECRET`**, and `live.mode=testnet`. To enable a real order: add live Alpaca keys, set `live.mode=real`, remove the paper keys (so `resolve_mode`→`live`); the **regime gate still applies** (never bypass). Then a tiny `$50–100` live launch.
2. **Machine contention is the real throttle.** This 16 GB / 8-core M2 ran **load 25–50** because several other Claude sessions each ran the full `engine:test` at once — that's what made the first two agents look "hung" for ~2h (not a code bug). Lessons that worked: **MAX 1–2 worktree agents**, **never two `next build` at once**, and the **anti-hang agent contract = commit BEFORE verify** (so work survives a load spike; the orchestrator runs the authoritative full verify serially before merge). Heavy sweeps belong on Modal, not the M2.

## Housekeeping
- `.env.local` symlink in the orchestrator worktree was **removed** — do NOT recreate it; with default `APP_ENV` it makes `engine:test` hit the prod DB and ~44 tests fail. Real keys load via the symlink only when running the live exercise; remove it before pushing.
- Disposable local branches left by the orchestrator (safe to delete): `verify/a|b|c|f`, `salvage/budget-truth`, `salvage/research-uses-everything`.
- Reports: `docs/reports/ignite-defensive5-2026-06-16.md` (TASK I detail).
