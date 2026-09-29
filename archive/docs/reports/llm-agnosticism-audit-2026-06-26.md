# LLM-Agnosticism Audit — is Cosmu drivable by any coding agent?

**Date:** 2026-06-26 · **Scope:** READ-ONLY audit of the agent-tooling surface (entry docs,
skills, verify gate, hardcoded provider assumptions). The *product runtime* (where Claude/Grok
models are a deliberate, OpenRouter-routed choice) is explicitly out of scope except to confirm
it is abstracted.

**Verdict: YES — agnostic, ~85%.** The architecture is genuinely tool-neutral: one canonical
`AGENTS.md` (self-described as agent-agnostic), pointer files for Cursor and Copilot, skills that
are plain runnable Markdown (no Claude-only tooling), a `pnpm verify` gate with honest degradation,
and a provider-neutral LLM seam (OpenRouter + xAI, OpenAI-compatible). A Codex agent dropped in
**would** know how to build/test/deploy from `AGENTS.md` alone. The residual ~15% is *framing and
discoverability*, not lock-in: no Codex pointer file, skill/doc prose that names "Claude Code" as
the implicit driver, two skills missing from the `AGENTS.md` index, and no tool-neutral `make
verify` alias (every path hard-names `pnpm`).

---

## 1. Agent-entry surface — Claude-specific or agnostic?

**Strongly agnostic by design.** There is **no `CLAUDE.md` anywhere in the repo** (verified:
`find . -name CLAUDE.md` → empty) — so there is no Claude-only entry doc that diverges from the
shared one. The single canonical entry is `AGENTS.md`, whose first line states it outright:

> "This is the single canonical entry doc. It is agent-agnostic — Claude Code, OpenAI Codex, and
> Cursor all drive from this file." (`AGENTS.md:3`)

Two tool-specific pointer files exist and are **byte-equivalent redirects** to it (no divergent
guidance):

| File | Content |
|------|---------|
| `.cursorrules` | "Read AGENTS.md first — it is the canonical entry point. Follow the runnable playbooks in `.claude/skills/`. Run `pnpm verify` before pushing." |
| `.github/copilot-instructions.md` | Identical 3 lines. |

`AGENTS.md` itself is tool-neutral on the essentials a cold agent needs: the stack
(`AGENTS.md:8-12`), how the loop runs honestly (`:14-39`), the dev gate `pnpm verify` (`:56-65`),
the canonical env vars (`:67-72`), and a "Session protocol (for any coding agent)" (`:105-117`).
**A Codex agent would know how to build, test, and deploy from this file alone.**

**Gap (discoverability, not lock-in):** there is **no Codex/OpenAI pointer file**. Codex looks for
`AGENTS.md` (which exists — good) but the explicit per-tool redirect pattern is only completed for
Cursor and Copilot. A Codex agent that *only* reads tool-specific config would still land fine
because `AGENTS.md` is the file it natively expects; the asymmetry is cosmetic but worth closing
for parity.

---

## 2. Skills — Claude-Skill-tool-bound, or runnable by any agent?

**Runnable by any agent.** All 26 skills under `.claude/skills/<name>/SKILL.md` are plain Markdown
with standard YAML frontmatter (`name` + `description`) and a `## Steps` body whose steps are
**concrete commands and API calls**, not Claude-tool invocations. Evidence:

- `run-gate/SKILL.md` steps: `POST /research/gate`, `POST /research/cross-asset-gate`, and a
  `python3 -m pytest …` verify line — all driveable by any agent with a shell + HTTP.
- `deploy-check/SKILL.md`: `pnpm verify` → `git push`. No Claude tooling.
- **No SKILL.md references the Claude "Skill tool", the slash-command runtime, or any Claude-only
  capability** (verified: `rg 'Skill tool|slash command|type the slash' .claude/skills/` → empty).
- `AGENTS.md:73-104` even documents the dual invocation explicitly: "**Claude Code:** type the
  slash command. **Any other agent (Codex, Cursor, …):** open `.claude/skills/<name>/SKILL.md` and
  follow it."

**Residual Claude-leaning prose (7 mentions across 5 skills).** `rg 'Claude Code' .claude/skills/`
returns 7 hits in `fan-out`, `split-tasks`, `research-to-cohort`, `backfill-summaries`,
`strategize`. These read "Claude Code does X" where a Codex agent would read "*I* do X" — they're
*narration*, not a hard dependency, but they subtly tell a non-Claude agent "this is for someone
else." `fan-out/SKILL.md` is the most Claude-coupled: its Mode A leans on background agents in
worktrees (`isolation: worktree`, `run_in_background`), which is a Claude-Code orchestration
primitive. That's acceptable (orchestration is inherently harness-specific) but should be fenced as
"Claude-Code-specific; other agents use Mode B (separate chats)".

**One runtime coupling worth naming:** `apps/engine/cosmu/lab/strategize.py` (the strategy-intake
router) returns a route with `delegated: True` and a comment "Claude Code must drive the named
skill" (`:6, :47, :105, :110`). Mechanically it just returns `SKILL_FOR[intent]` (a skill name) +
a flag — *any* agent can read that name and open the matching `SKILL.md`. The offline-authorable
intents (`vibe`/`batch`/`pine`) author deterministically with **no LLM at all**. So the coupling is
naming, not function — but the literal "Claude Code must drive" wording overstates it.

---

## 3. Universal verify/lint/test/build entrypoint?

**Yes — `pnpm verify` — but it is `pnpm`-only, with no tool-neutral alias.** A non-Claude agent
*would* discover it: it is named in `AGENTS.md:56-65`, `README.md:43-49`, every relevant skill, the
pre-push hook, and `verify.yml`. It is well-built:

- `package.json:31` — `verify = naming:check && contracts:generate && contracts:check-drift &&
  engine:test && typecheck && build`. Plus `verify:fast` (skip build) and `verify:local`
  (offline-only).
- `.githooks/pre-push` is the real gate and **degrades honestly**: missing `python3` errors with a
  fix hint; missing pytest/xdist/node_modules **SKIP loudly** rather than false-fail (`:25-89`). A
  minimal Codex sandbox without the full toolchain still gets a sane signal.

**Gaps:**
1. **No `make verify` / `justfile` / shell wrapper.** `make` *is* available on this machine
   (`/usr/bin/make`), and `AGENTS.md` claims Codex/Cursor parity — but every entrypoint hard-names
   `pnpm`. An agent in an environment where `pnpm` isn't the assumed runner (or that reaches for
   `make`/`just` by convention) has no neutral alias. A 5-line `Makefile` delegating to the pnpm
   scripts (`verify: ; pnpm verify`) would make the gate runner-agnostic at zero behavioral cost.
2. The full `verify` requires `pnpm install` first (Node 22–25 per `package.json:5-6`) — fine, but
   the dependency on the JS toolchain to run *Python* tests (`engine:test` is invoked via a pnpm
   script) is an implicit coupling; the underlying `PYTHONPATH=apps/engine python3 -m pytest …`
   command is in `package.json:16` and runnable directly, but a cold agent won't know that without
   reading the script.

---

## 4. Hardcoded Claude/Anthropic assumptions in TOOLING (vs. product runtime)

**Tooling is clean.** `rg -i 'claude|anthropic' scripts/ .githooks/ .github/workflows/
package.json` returns exactly **one** hit — a path filter in `verify.yml` skipping heavy jobs on
`.claude/**`-only pushes. No build/test/lint/deploy script names a model or provider. The
pre-push hook, the 25 files in `scripts/`, and the CI workflow are all provider-neutral.

**Product runtime is deliberately abstracted (not a problem).** Claude/Anthropic references in
`apps/engine/cosmu/` are runtime choices behind a neutral seam:
- `cosmu/lab/llm.py` is "the REAL LLM seam — call **OpenRouter** … the HTTP transport is
  injectable so CI runs with no network/keys". It defines `OPENROUTER_URL` *and* `XAI_URL`
  ("OpenAI-compatible, same request shape") — i.e. the provider is swappable by config, and the
  `anthropic/claude-3.7-sonnet` mention in `cosmu/lab/router.py:41` is an *example* of a model id
  you can paste in, not a hardcode.
- `cosmu/config/settings.py:122` has a `claude` `VendorBudget` field — a cost-tracking line item,
  alongside other vendors, not a lock.

So the only place Claude is "hardcoded" is where the *system being built* chooses a model — which
is the intended design (`docs/VISION.md:149-156`: "steerable by any coding agent … typed seams").

---

## 5. Concrete changes to reach full agent-agnosticism

Ranked by leverage (all low-risk, docs/config-only):

1. **Add a tool-neutral `make verify` (and `make verify-fast`, `make install`).** A ~6-line root
   `Makefile` delegating to the existing pnpm scripts. Closes the one real runner-coupling; gives
   `make`/`just`-convention agents (incl. some Codex setups) a zero-config entrypoint. Name it in
   `AGENTS.md` next to `pnpm verify` as "equivalent".

2. **Complete the per-tool pointer set: add a Codex pointer.** `AGENTS.md` already *is* the file
   Codex reads, but add an explicit one-liner in `AGENTS.md` (or a `.codex` note) confirming
   "Codex: this file is your entry; skills are in `.claude/skills/`" — matching the Cursor/Copilot
   redirects so the agnostic claim is symmetric.

3. **Fix the `AGENTS.md` skills index — it's stale.** The table lists 25 skills but 26 exist;
   `health-check` and `research-to-cohort` are **missing** from `AGENTS.md:78-104`. A non-Claude
   agent driving from the index can't discover them. Add both rows. (Also consider generating this
   table from the `.claude/skills/*/SKILL.md` frontmatter so it can't drift again.)

4. **De-Claude the skill/router prose (mechanical).** In the 7 "Claude Code" mentions across
   `fan-out`, `split-tasks`, `research-to-cohort`, `backfill-summaries`, `strategize` SKILL.md
   files — and the `cosmu/lab/strategize.py` comments — replace "Claude Code drives/must drive X"
   with "the coding agent drives X" except where the capability is genuinely Claude-Code-specific
   (e.g. `fan-out` Mode A background-worktree agents), which should be **fenced** as such with Mode
   B given as the agent-neutral path.

5. **(Optional) Document the direct test command.** Add one line to `AGENTS.md`/`README.md` noting
   that the engine suite runs standalone via `PYTHONPATH=apps/engine python3 -m pytest apps/engine/tests`
   for agents without the Node toolchain — decoupling the Python gate from `pnpm` for minimal
   environments.

**None of these touch money, the gate, or the runtime.** They make the *already-agnostic*
architecture legible to a non-Claude agent and remove the last "this is for Claude" signals.

---

## Evidence index

| Claim | File(s) |
|-------|---------|
| Canonical agnostic entry, no CLAUDE.md | `AGENTS.md:1-3`; `find . -name CLAUDE.md` empty |
| Tool pointers redirect to AGENTS.md | `.cursorrules`; `.github/copilot-instructions.md` |
| Skills are runnable Markdown, no Skill-tool dep | `.claude/skills/*/SKILL.md`; `run-gate`, `deploy-check`, `fan-out` |
| Dual invocation documented | `AGENTS.md:73-104` |
| Verify gate + honest degradation | `package.json:31-33`; `.githooks/pre-push:25-89` |
| Tooling free of provider hardcode | `rg -i 'claude\|anthropic' scripts/ .githooks/ .github/workflows/ package.json` → 1 path-filter hit |
| Runtime LLM seam is provider-neutral | `cosmu/lab/llm.py` (OpenRouter + xAI); `cosmu/lab/router.py:41` |
| "Claude Code must drive" coupling (naming) | `cosmu/lab/strategize.py:6,47,105,110` |
| Stale skills index (25 vs 26) | `AGENTS.md:78-104` vs `ls .claude/skills` (`health-check`, `research-to-cohort` missing) |
| `make` available for a neutral alias | `/usr/bin/make` present |
| Design intent: steerable by any agent | `docs/VISION.md:149-156`; `docs/MASTER_PLAN.md:78,125` |
