# Novelty-gate the wave-0 inbox seeds — protect the FDR budget at the authoring door

Date: 2026-06-28
Branch: `claude/inbox-novelty-gate-2026-06-28`
Roadmap item: #8 (autonomous POC — DO NOT MERGE yet)

## The hole

The dominant strategy-authoring door is:

```
.json spec → strategies/inbox/ → scan_inbox() → FarmLoop.run_cohort(extra_seeds=...) → wave-0
```

Inside `apps/engine/cosmu/evolution/loop.py`, the novelty check `_novelty_ok` (≈ loop.py:516)
was applied to the **mutation** and **wildcard** children (≈ loop.py:321 / :337) — but **never**
to the wave-0 inbox/chat seeds themselves (the `extra_seeds` loop at ≈ loop.py:277).

Wave-0 seeds were only structurally de-duplicated by `_is_duplicate` → `combo_hash`, which is an
**exact-combo** content address. Two specs that are *near*-duplicates (same entry-feature structure
but a different hold window, direction, etc.) hash differently, so each one slipped through and
consumed an **independent slot in the Gate's BH-FDR multiple-testing budget**.

This is not hypothetical: the inbox-lint (#460) measured **26 near-duplicate clusters among 125
real inbox specs**. Each near-clone deflates the survivors a little more for no added information.

## The fix (human-vs-agent policy split)

Mirrors the policy already used at the *authoring* layer (`lab/author.py`: an agent batch hard-rejects
near-dups, a human's intentional re-run stays advisory) — now enforced at the wave-0 **intake** door.

1. **Provenance is threaded onto the wave-0 seeds.**
   - `Candidate` gained an `authored_by: str = "human"` field.
   - `run_cohort(..., extra_seeds_authored_by: list[str] | None = None)` accepts a per-seed
     provenance list parallel to `extra_seeds` (defaults to `"human"` — the conservative,
     never-silently-drop side).
   - `scan_inbox` resolves each file's provenance from the audited authoring events
     (`strategize_authored` / `inbox_queued`, matched on the file's `content_hash`) via the new
     `inbox._authored_by`. Unknown / no positive evidence ⇒ `"human"`.

2. **Each non-seed wave-0 candidate is novelty-checked** against the seeds already admitted *this
   wave* (the same `_novelty_ok` structural-distance check the children use), via the new pure
   helper `FarmLoop._wave0_novelty_verdict(cand, admitted) -> "ok" | "skip" | "flag"`:
   - curated `seed_population()` seeds are never inter-checked (matches the `_is_duplicate` seed
     exemption) → `"ok"`.
   - genuinely-novel seed → `"ok"` (existing behaviour preserved exactly).
   - **AGENT** near-dup → `"skip"` — HARD-DEDUPE; counted as a `duplicate`, never generated, so a
     machine batch can't flood the FDR budget with clones.
   - **HUMAN** near-dup → `"flag"` — KEPT (intentional authorship respected) but **annotated** with
     a visible `inbox_near_dup` audit event so the operator sees it was a near-dup.

3. **Audit trail.** Both outcomes emit an `inbox_near_dup` event (`action: "skipped" | "kept_flagged"`,
   with `name` / `authored_by` / `lane`) inside the existing persist transaction — so a near-duplicate
   is never silently dropped: it is either explained (agent) or surfaced + kept (human).

## Files changed

- `apps/engine/cosmu/evolution/loop.py`
  - `Candidate.authored_by` field.
  - `run_cohort(extra_seeds_authored_by=...)` param; threads per-seed provenance onto the chat/inbox
    Candidates.
  - new `_wave0_novelty_verdict(...)`; wave-0 loop applies it (skip agent dups / flag human dups /
    track the admitted live set); `inbox_near_dup` events emitted in the persist batch.
- `apps/engine/cosmu/lab/inbox.py`
  - new `_authored_by(store, content_hash)` provenance resolver (reads the authoring events,
    human-default).
  - `scan_inbox` collects per-file provenance and passes `extra_seeds_authored_by` to `run_cohort`.

The Gate math (DSR / PBO / folds / min-trades / BH-FDR-q / beat-B&H / holdout floors) is **untouched**.
This change only governs *what enters* the budget at the authoring door — it never loosens the Gate.

## Tests

`apps/engine/tests/test_inbox_novelty_gate.py` (8 tests, all green, offline):
- **Unit (pure verdict):** agent near-dup → `skip`; human near-dup → `flag`; novel seed → `ok`
  (both provenances); seed lane never checked; first seed with empty admitted set → `ok`.
- **End-to-end (real `run_cohort` over a small offline fixture market):** of two near-duplicate
  authoring-door seeds, the AGENT batch drops the clone (`duplicates >= 1`, `lanes["chat"] == 1`,
  `inbox_near_dup action=skipped`) while the HUMAN batch keeps both (`duplicates == 0`,
  `lanes["chat"] == 2`, `inbox_near_dup action=kept_flagged`); two genuinely-distinct seeds pass
  with no event.
- **Provenance resolver:** agent file resolves `"agent"`; unknown hash defaults `"human"`.

Run: `python3 -m pytest tests/test_inbox_novelty_gate.py -q` → **8 passed**.
Regression: `test_lab_inbox.py`, `test_novelty_gate.py`, `test_farmloop_holdout_oneshot.py`,
`test_rerun_cohort.py`, `test_lab_batch.py`, `test_cohort_gate.py`,
`test_generous_paper_near_miss.py` → all green.

## Honest limitations

- **Provenance defaults to human.** If an agent-authored `.json` was dropped into the inbox without a
  recorded `strategize_authored`/`inbox_queued` event (e.g. a hand-copied file or an older batch run
  before this provenance was recorded), it resolves to `"human"` and its near-dups are *flagged, not
  dropped*. This is deliberate (never silently drop the operator's work) but means the agent
  hard-dedupe only bites batches that go through the proper authoring path.
- **In-batch only.** The wave-0 check compares each seed against the other authoring-door seeds
  admitted *in the same cohort* (plus the memory dead-end recall inside `novelty_gate`). It does not
  cross-check against historical inbox seeds from prior cohorts — the existing `_is_duplicate`
  registry (combo_hash) already covers exact prior repeats; near-dups vs. *prior* cohorts are not
  newly deduped here.
- **`lab/research.py` agent lane unchanged.** The research-to-cohort lane also feeds `extra_seeds`;
  it now defaults to human provenance (flag, not drop). Threading agent provenance there is a
  follow-up, out of scope for this targeted inbox-door fix.
- **`structural_distance` threshold (0.25) is the existing one** — this change reuses it verbatim, so
  it inherits whatever calibration that gate has; no constant was changed.
