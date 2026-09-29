# Backlog Structure Audit — 2026-06-26

> **Scope:** READ-ONLY structural audit of the backlog system. Operator question: *"Is the backlog well-sorted — small tasks vs epics, etc.?"*
> **Verdict: NO — not well-sorted.** The backlog is honest and rich in content but structurally **chronological, not actionable**. It has accreted as a stack of dated session-snapshots (9 distinct dates as `##` headers) that are never reconciled when work ships. An agent **cannot** pick a well-scoped task without reading the whole 305-line file, and several "open" items are already DONE in code. The fix is a one-time re-sort into a status-tagged taxonomy + a cleanup pass — **not** a rewrite of the content.

**Files audited:** `BACKLOG.md` (305 lines, 60 KB), `IDEAS.md` (90 lines, 21 KB), `docs/MASTER_PLAN.md`, `AGENTS.md`, `.claude/skills/triage-ideas/SKILL.md`, `docs/epics/*` (7 epic docs + `docs/epics/tasks/*`).

---

## 1. The taxonomy that EXISTS (mapped)

There are **two** intended taxonomies, and they disagree.

**(A) What `triage-ideas/SKILL.md` + `IDEAS.md` promise** (the designed loop):
```
IDEAS.md  ── DUMP ZONE (free-form)  +  Inbox (dated one-liners)
   │ /triage-ideas
   ▼
BACKLOG.md ── Now / Next / Later   (tagged: (engine|web|config)+(cloud|local)+(opus|sonnet|haiku) + epic-link)
   │ /fan-out · /split-tasks
   ▼
PRs → main ;  triaged ideas → IDEAS.md ## Archived (with disposition)
```
This is a clean 3-tier model: **idea → small task (Now/Next/Later) → done/archived**, with EPICs as named docs in `docs/epics/` linked from backlog items.

**(B) What `BACKLOG.md` ACTUALLY looks like** (17 `##` sections):

| # | Section header | Date | Kind | State |
|---|---|---|---|---|
| 1 | 🎯 PRIORITISED — deep-think synthesis | 2026-06-17 | ranked master-list | **partly stale** (item #1 DONE) |
| 2 | 🤖 EPIC — LLM strategy model (Gate B) | 2026-06-17 | epic w/ checklist | live, partly stale |
| 3 | 🧭 ALIGNMENT CHECK | 2026-06-14 | a *report*, not tasks | stale snapshot |
| 4 | 🧭 EPIC (composition + discretionary + alt-data) | 2026-06-15 | epic | mixed |
| 5 | 🧭 EPICS (interface consolidation + realtime) | 2026-06-11 | epic | mixed |
| 6 | 🧪 EPIC (research engine + paper-API + intake) | 2026-06-13 | epic | open |
| 7 | 🧠 EPIC (regime/context deep-analysis) | 2026-06-14 | epic | parked |
| 8 | ⚡ EPIC: realtime-data-lane | 2026-06-11 | epic (P0→P4) | mixed |
| 9 | 🚧 PRE-LIVE GATES (deep review) | 2026-06-11 | small tasks | mixed |
| 10 | 🚧 PRE-LIVE GATES (adversarial review) | 2026-06-10 | small tasks | open |
| 11 | ⚡ OPERATOR ACTIONS (audit fix-wave) | 2026-06-09 | operator runbook | open |
| 12 | ⚡ Alpaca equities lane | 2026-06-12 | small tasks | open (key-gated) |
| 13 | **Now** | — | small tasks | the *designed* home, buried at L243 |
| 14 | **Next** | — | small tasks | buried |
| 15 | **Later** | — | small tasks | buried |
| 16 | ⭐ TOP OF QUEUE | 2026-06-06 | small tasks | stale, self-contradictory |
| 17 | 🔬 MACHINE AUDIT — S×A×V spine | 2026-06-17 | findings + tasks | **partly stale** |

**The structural problem in one sentence:** the canonical `Now / Next / Later` buckets that the triage skill writes into (sections 13–15) are **buried in the middle of the file**, sandwiched between twelve dated epic/audit/synthesis blocks above and a stale "TOP OF QUEUE" block below. The de-facto priority signal is "scroll to whatever session-block is newest," which is the opposite of a sorted backlog.

---

## 2. Is the small-task ↔ epic split clean? **No.**

- **EPICs and small tasks are interleaved at the same heading level.** A genuine epic (LLM Gate B, regime/context, realtime-data-lane — each with its own `docs/epics/*.md`) sits as a `##` peer of a one-line tweak like "Gap-through stops fill AT the stop (engine, sonnet)". Nothing tells an agent "this `##` is a 3-week epic, that `##` is a 30-minute fix."
- **Epics are correctly externalized to `docs/epics/` (good)** — but the backlog duplicates large prose blocks of them inline (the regime epic block is ~6 lines + M1–M7 sub-items; realtime is P0–P4 inline) instead of a one-line pointer + status. The detail lives in two places and drifts.
- **Reports are mixed in with tasks.** The "🧭 ALIGNMENT CHECK 2026-06-14" section (L65–72) is a *judgment snapshot* ("DRIFTING into polish… 0 survivors"), not a list of pickable work — it's marked "for later edit/merge" and never got merged. It belongs in `docs/reports/`, not the backlog.
- **No size/priority tag on items.** The tag convention is `(engine|web|config)+(opus|sonnet)` — it encodes *area* and *model* but **not size** (S/M/L) and **not priority** (P0/P1). Priority is implied only by section and by the prose word "ranked." An agent can't filter "show me the small P0s."

**Bottom line for the operator's exact question:** an agent dropped into this file **cannot** pick a well-scoped small task without reading the whole thing, because (a) size isn't tagged, (b) the freshest priority isn't at the top, and (c) some "open" items are already done.

---

## 3. Stale / DONE-but-still-open items (code-verified)

These were checked against the actual code on `main` (commit 588b935). All are listed as **open or queued** in the backlog but are **shipped**:

| Backlog claim | Location | Reality (verified) |
|---|---|---|
| **Per-symbol `backtest_symbols` table** = the #1 priority, "the base-rebuild agent MUST create the table" | §1 PRIORITISED, L12 | **DONE.** Migrations `2026-06-17_backtest_symbols.sql` (+ 06-18, 06-19) exist; wired into `lab/finder.py`, `knowledge/store.py`, `master/tracks.py`, `master/screen_universe.py`. The whole framing of priority #1 is stale. |
| **Exit-path divergence** — "AUDITED 2026-06-17 — real gap… `paper_step` ignores `spec.exit.plan`… FIX: make paper_step apply it" | §2 Deferred, L54 | **FIXED.** `orchestrator/paper_step.py` now calls `_exit_state.step_exit_plan(...)` ("parity #5"). The described gap is closed. |
| **`track = the triple`** (audit#7) — "QUEUED, ⚠️NEEDS operator sign-off… tracks UNIQUE(version) → add symbol+venue" | §17 MACHINE AUDIT, L300 | **DONE.** Migration `2026-06-18_tracks_per_cell.sql` adds `symbol` + `venue_id`, ref_id `<version>:<symbol>:<venue>`. Memory `sav_model_brut_2026-06-18` confirms it's LOCKED. |
| **`wake the LLM lane`** (audit#10) — "open_agent_strategy called ONLY in tests… end-to-end DEAD in prod" | §17 MACHINE AUDIT, L302 | **Largely shipped.** `open_agent_strategy` now called from `lab/nlp_intake.py` and `strategy/author_agent.py` (non-test authoring entrypoints), plus the `P0.4 core SHIPPED` note one section up already says the lane is live in prod. Self-contradicts §2 P0.4. |

**Plus structural staleness:**
- The whole **"🧭 ALIGNMENT CHECK 2026-06-14"** block (L65–72) reads "0 gate survivors" — but `MASTER_PLAN.md` headline + memory (`first_gate_survivor`, `deploy_lane_hardened_2026-06-16`) record **8 honest-Gate survivors** since 2026-06-14/16. The snapshot is factually outdated and should be archived.
- **"⭐ TOP OF QUEUE — 2026-06-06"** (L264) literally says it *"SUPERSEDES the stale 'Now' above"* — but it sits 21 lines *below* "Now", and is itself the oldest dated block in the file (06-06). Two sections both claim to be the live priority; neither is.

---

## 4. Duplicates & conflicts (cross-section)

The chronological accretion means the **same work is described 2–4 times** across session-blocks, each with slightly different framing. The biggest clusters:

- **Cross-strategy correlation** appears as: "Cross-strategy correlation signals" (Later, L260) · "M4 — fleet correlation-aware funding… Subsumes 'Cross-strategy correlation signals'" (L193) · "Phase 4… cross-asset correlation" (L187). Three entries, one feature; M4 even says it subsumes the Later one but the Later one is still listed.
- **Event-study / conversational strategy factory** appears in §4 (L131), §6 (L169), and realtime §8 P1 (L200), each pointing at the others ("Union of…", "Depends on realtime-epic P1"). Genuinely one initiative spread across three epics.
- **Multi-lane INTAKE (ML|Prompt|Index)** in §6 (L167) overlaps the whole §2 LLM Gate-B epic (the `kind='llm'` lane) and §17's "wake the LLM lane."
- **DuckDB / Parquet on R2** in §6 (L175), §7 Phase 0 (L183), and §16 "Hot/cold data tiering" (L275) — three entries; note the cold tier already shipped per memory `cold_tier_migration_2026-06-15`, so two of the three are stale.
- **Per-strategy summaries / backfill-summaries**: §4 (L41 IDEAS), realtime §8 (L204), and the `backfill-summaries` skill — duplicated as both "deferred" and "mostly built, promote it."
- **`/live/defund` must close via order path** (L220) vs **"Liquidate all" / "Stop" semantics** (L158 + IDEAS L23) — same money-path requirement, three phrasings.

**Conflict to resolve:** the **discretionary live lane** (§4 L102, design-first, "a bounded exception to the deterministic Gate is the SOLE funder") sits next to the hard invariant repeated everywhere else ("the deterministic Gate remains the SOLE funder of real money"). It's flagged as a deliberate exception, but an agent skimming will hit contradictory rules. Keep it, but mark it explicitly `DESIGN-PENDING / invariant-exception` so it can't be picked up as normal work.

---

## 5. IDEAS.md — the inbox is stalled

- **The `## Inbox` holds 27 un-triaged dated ideas**, the newest from **2026-06-13** — i.e. the inbox has not been triaged in **13 days**, while `BACKLOG.md` was edited as recently as **today (2026-06-26)**. The designed loop (IDEAS → triage → BACKLOG → archive) has **broken down**: ideas are being added straight to BACKLOG (commits `8ef48ee`, `aff0415` today) and the IDEAS inbox is bypassed and rotting.
- Several inbox items are clearly **ripe and overlap shipped/backlog work** (Costs editable-from-page, "Stop" semantics, KPI pedagogy tooltips, edge_source/counterparty gated fields) — they should have been promoted or archived weeks ago.
- The **DUMP ZONE is empty** (good — nothing lost there), so the only fix needed is a `/triage-ideas` run to drain the 27-item Inbox.
- The `## Archived` section is well-kept (Shipped / Deferred / Dropped sub-buckets with dispositions) — **this is the one part of the system working as designed.** Use it as the model for the rest.

---

## 6. Recommended target structure (propose-only)

Keep the **3-tier model the skill already defines** (idea → task → done) but make it **status-first, not date-first**. Concretely:

### BACKLOG.md — proposed section order

```
# Cosmu Backlog
> (keep the header + tag legend, but FIX the tag legend — see below)

## 🔥 NOW            ← the ≤7 highest-leverage pickable items, each S/M/L tagged
## ⏭️ NEXT           ← on-deck, scoped, not started
## 🗓️ LATER          ← real but deferred; one line each
## 🧩 EPICS (index)  ← ONE line per epic: title · status · → docs/epics/<file>.md · % done
## ⚙️ OPERATOR ACTIONS ← runbook items needing local data/creds/keys (Alpaca, Supabase DDL, Modal)
## ✅ DONE (rolling, last ~30) ← recently shipped, pruned periodically into git history
## 🧊 ARCHIVED / SUPERSEDED ← stale snapshots & dead plans, kept for provenance
```

**Rules that make it agent-pickable:**
1. **Every item carries inline tags:** `[P0|P1|P2] [S|M|L] (engine|web|config|infra) (cloud|local) (opus|sonnet|haiku) → epic:<name>`. Adds the **two missing axes** (priority + size) so an agent can filter "P0 + S".
2. **Epics live in `docs/epics/` only**; the backlog holds a **one-line index entry + a status badge + % complete**, never the inline P0–P5 / M1–M7 prose. Kills the drift-in-two-places problem.
3. **Reports/snapshots are not tasks.** Move "ALIGNMENT CHECK" and any "headline/verdict" prose to `docs/reports/`; the backlog links them, doesn't host them.
4. **Status is a tag, not a section.** Replace per-session `## EPIC (2026-06-13 …)` headers with a single `→ epic:` link + a `status:` tag. Date-stamping moves into the epic doc's own changelog, not the backlog's structure.
5. **Done items roll off.** Keep only the last ~30 shipped under `## DONE`; everything older is already in git + the existing "do NOT re-add" guards. The file should trend toward ~120 lines, not grow to 305.

### Fix the tag legend
Header L4 says `(engine|web|config) + (opus|sonnet)` but the body and the triage skill both use `(cloud|local)` and `haiku` too. **Reconcile to the skill's canonical** `(engine|web|config)+(cloud|local)+(opus|sonnet|haiku)` and ADD `[P_] [size]`.

### IDEAS.md
No structural change needed — it's well-designed. Just **run `/triage-ideas`** to drain the 27-item Inbox into the new BACKLOG buckets (or Archived), and re-establish the cadence so ideas stop being written straight to BACKLOG.

---

## 7. Concrete cleanup list (specific items to fix)

**A. Mark DONE / move to ## DONE (code-verified shipped):**
1. §1 PRIORITISED item **#1 per-symbol `backtest_symbols`** → DONE (migrations + finder/store/tracks wired).
2. §2 Deferred **exit-path divergence** (L54) → DONE (`paper_step.step_exit_plan`, parity #5).
3. §17 MACHINE AUDIT **track = the triple** (audit#7, L300) → DONE (`2026-06-18_tracks_per_cell.sql`).
4. §17 MACHINE AUDIT **wake the LLM lane** (audit#10, L302) → at least PARTIAL/DONE (authoring entrypoints exist; reconcile with §2 P0.4 which already says "SHIPPED, live in prod").

**B. Archive (stale snapshots, not tasks):**
5. Entire **🧭 ALIGNMENT CHECK 2026-06-14** block (L65–72) → `docs/reports/` (and update its "0 survivors" claim — there are 8). Re-run `/align-check` fresh if a current judgment is wanted.
6. **⭐ TOP OF QUEUE — 2026-06-06** (L264–285) → Archived. It's the oldest block, self-contradicts "Now", and most items are shipped (bar backbone, honesty fixes, MCP layer, data-viz all `[x]`).

**C. Dedup (collapse to one entry + epic link):**
7. Cross-strategy correlation: keep **M4** only; drop "Cross-strategy correlation signals" (Later, L260) and fold the Phase-4 mention into the regime epic doc.
8. Event-study factory: collapse §4 L131 + §6 L169 + realtime P1 L200 into one `→ epic:realtime` item.
9. DuckDB/Parquet: keep one entry; mark the **cold-tier** half DONE (shipped per `cold_tier_migration_2026-06-15`).
10. Per-strategy summaries: collapse the 2–3 mentions into one; note "mostly built — promote to default."
11. `/live/defund` order-path (L220) + "Liquidate all" (L158) + "Stop semantics" (IDEAS L23) → one money-path item.

**D. Reclassify size/priority (add the missing tags):**
12. Tag the **PRE-LIVE GATES** items (§9/§10) as the true **P0 small tasks** they are (gap-through stops, dust trap, neutral-track funding cliff, reduce_only live-exit) — these are the highest-value *pickable* work and are currently buried below 8 epic blocks.
13. Mark the **discretionary live lane** (§4 L102) `DESIGN-PENDING · invariant-exception` so it's never picked up as routine work.

**E. Drain the inbox:**
14. Run `/triage-ideas` on the 27 stale IDEAS.md Inbox items (newest 2026-06-13); promote the ripe ones (Costs-editable, Stop-semantics, KPI tooltips, edge_source/counterparty) and archive the rest with a disposition.

---

## 8. Verdict

| Dimension | Assessment |
|---|---|
| **Content quality** | High — honest, detailed, well-cross-referenced, strong "do NOT re-add" guards. |
| **Consistent taxonomy?** | **No** — two competing models (skill's Now/Next/Later vs. de-facto dated session-blocks); EPICs and one-line tasks share a heading level. |
| **Well-categorized / deduped / prioritized?** | **No** — ~4 multi-section duplicate clusters; priority is "newest block wins"; no size/priority tags. |
| **Stale/DONE items still open?** | **Yes** — ≥4 code-verified-shipped items still listed open/queued; 2 whole snapshot sections obsolete. |
| **Agent can pick a scoped task without reading it all?** | **No** — the canonical Now/Next/Later is buried at L243; small P0s hide under epics; size isn't tagged. |
| **IDEAS inbox loop healthy?** | **No** — 27 items un-triaged for 13 days; the loop is bypassed (ideas land straight in BACKLOG). The Archived section, by contrast, is exemplary. |

**Top 3 structural fixes (in order):**
1. **Re-sort status-first, not date-first:** hoist `NOW / NEXT / LATER` to the top; demote every dated `## EPIC (2026-…)` block to a one-line entry under a single `## EPICS (index)` that links `docs/epics/*`; move snapshots/reports out to `docs/reports/`.
2. **Add the two missing tag axes — priority `[P0|P1|P2]` and size `[S|M|L]`** — to every item, and fix the tag legend to match the triage skill. This alone makes the file agent-filterable.
3. **Run the cleanup list (§7):** mark the 4 code-verified-DONE items done, archive the 2 obsolete snapshot sections, collapse the ~5 duplicate clusters, and drain the 27-item IDEAS inbox via `/triage-ideas`.

This is a one-time re-sort + a recurring `/triage-ideas` cadence, **not** a content rewrite. The raw material is good; it's the shelving that's chronological instead of actionable.
