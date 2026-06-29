# Fold the behavioral leakage audit into `profile_source`'s GO / REVIEW / NO-GO verdict

**Date:** 2026-06-28
**Branch:** `claude/leakage-profile-source-2026-06-28`
**Status:** propose-only / vetting-side. Touches NO Gate constant, moves NO money, fully reversible.

## The gap closed

`apps/engine/cosmu/ingest/profile_source.py` is the data-trust audit that decides whether a NEW alt-data
source is GO / REVIEW / NO-GO **before** it is wired into the feature registry. Until now every check it ran
reasoned about **declared point-in-time metadata**:

- coverage depth (rows · span)
- gaps (missing buckets / grid)
- staleness (freshness vs cadence)
- `look_ahead` — any raw `available_at < ts`
- `pit_lag` — declared release lag vs observed median availability lag
- `revision_safety` — silent same-ts restatements

None of those can catch a **baked-in alignment leak**: a feature whose metadata looks *spotless*
(`available_at == ts`, deep, fresh, no holes, no declared-lag dishonesty) but whose **actual join to bars peeks
a bar forward**. That is the exact vibe-coded failure vector ([[vibe_coding_leakage_risk]]) — a survivor that is
genuinely real on paper and zero/negative live, invisible to the Gate (which validates edge-after-costs, not
pipeline honesty).

Meanwhile `apps/engine/cosmu/research/leakage_tripwire.py::audit_feature` (merged #387) already catches this
**behaviorally** by running three independent disconfirmers against the *real* bars:

1. **available_at audit** — re-derives the `align_asof` join from the raw points; a value on a bar with no point
   available by then = look-ahead, a non-latest revision = wrong-winner.
2. **shuffle-null** — permute the feature's values in time; a real alignment's IC sits OUTSIDE the shuffled
   noise band, a spurious one sits inside it.
3. **forward-shift sanity** — the honest cheat (+1 bar) must help; if lagging the feature −1 bar (a *more*
   honest read) materially beats the live read, the live wiring is already a bar too early = baked-in peek.

`profile_source` simply **never called it**. This change wires it in.

## What changed

- `profile_points(...)` and `profile_source(...)` gained an optional `bars: list[Bar] | None` argument (plus
  `behavioral_horizon` and a `behavioral_min_obs` threshold).
- New helper `_behavioral_checks(...)` calls `audit_feature(points, bars, horizon=...)` and translates the
  `TripwireReport` into profiler `CheckResult`s that fold into the existing roll-up.
- `audit_feature` is imported **lazily inside the helper** so the lightweight metadata audit + its CLI keep zero
  dependency on the research stack; the behavioral path pulls it in only when bars are actually supplied.
- Preserves every existing metadata check — this **adds** a behavioral gate, it does not replace anything.
- Constant added: `BEHAVIORAL_MIN_OBS = 30` (minimum joined observations to trust the disconfirmers). It is a
  vetting-policy constant in the ingest layer — NOT a strategy param and NOT a Gate constant.

## Verdict mapping (the fold)

When matched `bars` are supplied and the join overlap is deep enough (`report.n_obs >= BEHAVIORAL_MIN_OBS`):

| New check | Source disconfirmer(s) | Severity | Effect on verdict |
|---|---|---|---|
| `behavioral_lookahead` | available_at audit **AND** forward-shift sanity (FAIL if **either** fails) | **hard** | FAIL ⇒ **NO-GO** |
| `behavioral_shuffle` | shuffle-null (`survives`) | **soft** | FAIL ⇒ at least **REVIEW** |

Roll-up is unchanged: any hard fail → NO-GO; else any soft fail → REVIEW; else GO.

**Rationale for the conservative split:**

- A positive look-ahead — the join peeked a not-yet-published value, *or* lagging the feature recovers a
  stronger fit (the live read was a bar too early) — is **direct evidence the wiring peeks the future**. It is
  the same class as a raw `available_at < ts` leak, so it is **HARD ⇒ NO-GO**.
- A shuffle-null FAIL means the IC collapsed *into* the shuffled noise band: the "edge" is indistinguishable
  from noise — an artefact / leak **smell**, not proof of a peek. A feed can legitimately have no clean IC on a
  given bar grid yet. So it is **SOFT ⇒ REVIEW**: we down-weight, we do not auto-reject. (Note: a real
  baked-in *alignment* leak typically still SURVIVES the shuffle — the leak is the alignment, not the data — so
  it is the forward-shift / available_at checks, not the shuffle, that catch the headline case. The shuffle
  guards the orthogonal spurious-IC class.)

## Graceful degradation (never a silent pass)

- **No bars supplied** → a single INFO `behavioral_audit` check: `"skipped — no matched bars supplied"`.
- **Overlap too thin** (`n_obs < BEHAVIORAL_MIN_OBS`) → INFO `behavioral_audit`:
  `"skipped — only N joined obs (< 30); too thin to audit behaviorally"`.

In both cases NO hard/soft behavioral check is emitted, so the behavioral gate cannot move the verdict on its
own — but the skip is **visible** in `checks` / `to_dict()` / `to_text()`, so a human always knows whether the
behavioral audit ran. It never silently blesses a source it could not behaviorally audit.

## Tests

New focused file: `apps/engine/tests/test_profile_source_behavioral.py` (offline, deterministic, injected
clock). Uses an AR(1)-smooth synthetic market (mirrors the tripwire's own offline generator) so a baked-in
1-bar-early read DEGRADES rather than destroys the IC — the condition that lets the forward-shift sanity see it.

- `test_baked_in_alignment_leak_is_no_go_via_behavioral_path` — **headline**: spotless metadata (`look_ahead`,
  `pit_lag`, `coverage_depth` all PASS) but the join carries bar t+1's value back-dated to bar t ⇒
  `behavioral_lookahead` FAILS ⇒ **NO-GO**.
- `test_clean_pit_source_with_bars_is_go` — honest PIT source with a real edge clears metadata + all three
  disconfirmers ⇒ **GO** (no over-rejection).
- `test_behavioral_audit_skipped_without_bars_is_not_silent_pass` — no bars ⇒ INFO skipped, verdict unchanged,
  no behavioral hard/soft check emitted.
- `test_behavioral_audit_skipped_when_overlap_too_thin` — ~5 overlapping bars ⇒ INFO skipped.
- `test_baked_in_leak_named_in_reasons_and_dict` — NO-GO reason surfaces the look-ahead; new checks serialize.

Existing `tests/test_profile_source.py::test_to_dict_and_to_text_are_stable_for_tooling` updated: the serialized
check-set now also contains the INFO `behavioral_audit` (skipped) check — an intentional, visible part of the
contract, not a regression.

**Result:** `tests/test_profile_source_behavioral.py` (5) + `tests/test_profile_source.py` (10) = **15 passed**.

```
$ python3 -m pytest tests/test_profile_source.py tests/test_profile_source_behavioral.py -q
15 passed
```

(Per M2 discipline only the new + directly-affected test files were run, not the full suite.)

## Limitations / honest caveats

- **Needs matched bars + a deep overlap.** The headline behavioral catch only fires when the caller supplies
  bars and `n_obs >= 30`. Callers that profile a source with no bars (the existing CLI path) still get only the
  metadata verdict — but now with a *visible* "behavioral audit skipped" note rather than a false sense of a
  full clean.
- **The CLI was not wired to fetch bars** (keeps it keyless/offline by default). Folding bars into the CLI is a
  follow-up; the programmatic `profile_points(..., bars=...)` / `profile_source(..., bars=...)` path is the one
  the edge/ingest lane should call.
- **Shuffle-null is advisory-soft here.** A real alignment leak survives the shuffle (the leak is the
  alignment), so the shuffle does NOT catch the headline case — the forward-shift / available_at checks do. The
  shuffle is folded as REVIEW only to guard the orthogonal spurious-IC class, deliberately not as a NO-GO.
- **Horizon = 1 by default.** A leak that only manifests at a longer forward horizon would need the caller to
  pass `behavioral_horizon`. Single-horizon is the conservative default matching the tripwire.
- **Determinism** depends on the fixed shuffle seed inside `audit_feature` (seed=0, 200 trials). Same as #387.

## Invariants honored

- Gate scoring constants / formulas: **untouched**.
- Per-(strategy × symbol × venue) BRUT model: **untouched** (this is source admission, not cell scoring).
- No money path, no prod/data mutation, no merge. Fully reversible (single module + one test file + one
  one-line test assertion update).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
