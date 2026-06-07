# START HERE — the 2-minute operator guide

COSMU = an autonomous quant machine. **LLMs propose, a deterministic Gate funds.** Live trading is OFF until you arm it.

---

## 1. Run it (once)
```bash
cp .env.example .env.local        # fill the 5 keys at the top of the file
pnpm install
pnpm modal:secret                 # pushes your keys to Modal (heavy compute)
```
Keys go in **3 places, .env.local is the source**: `.env.local` → Railway dashboard → `pnpm modal:secret`.
Full key reference: [`docs/SETUP_APIS.md`](SETUP_APIS.md)

## 2. Use it every day — 3 doors
| I want to… | Do this |
|---|---|
| **Drop an idea / strategy / "copy this"** | type it into the **Idea inbox** in the app, or run `/strategize` in Claude Code |
| **Check if a trade is worth it** | `/run-gate` (deterministic verdict on real data) |
| **Run heavy compute** (sweeps, ML) | `pnpm modal:gate` (runs on Modal, ~$0 idle) |

Everything you drop flows through the **same Gate** — no shortcut to Live. The Gate decides what gets money; never the model.

## 3. Build faster (dispatch agents)
- **All ready-to-paste prompts live in `docs/AGENT_TASKS.md`.**
- **Cloud agents** (parallel) = pure code + offline tests + `next build`.
- **Local (your Mac)** = anything touching `.env.local`, Railway, live data, or `modal run`.
- One branch per agent. The **local `pnpm verify` (pre-push hook) is the gate** — CI (GitHub Actions) is manual-dispatch only, OFF by default. **Push = deploy.**

## 4. Where things live
- **Ideas (features/infra)** → `IDEAS.md` → `/triage-ideas` → `BACKLOG.md`
- **Trades/strategies** → `apps/engine/strategies/inbox/` (or `/strategize`)
- **Prompts to dispatch** → `docs/AGENT_TASKS.md`
- **Lessons from mistakes** → `docs/LESSONS.md`
- **Full picture** → `AGENTS.md` (the canonical entry doc)

## 5. The one thing that matters right now
The machine runs but has **0 honest-Gate survivors** — every theory tested has been killed by the honest Gate.
(Authored = whatever is in `apps/engine/strategies/inbox/`; tested + verdicts = the `gate_verdicts` table,
surfaced at `/verdicts`. Don't trust any hand-written count — read those.)
**Priority #1 = find the first real edge** — author funding-carry on the deep funding data and run a tick.
Everything else (UI, venues, data) is plumbing until one strategy proves net-of-fee profit.
