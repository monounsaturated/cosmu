# Credibility / LLM pipeline scout — "PageRank for credibility" (2026-06-25)

READ-ONLY scout of the dormant credibility lane (epics audit #2: "built but dark").
De-risk **edge-option-1** (source-credibility) so it is READY when the operator picks it.
No code changes — this is the report only.

---

## TL;DR / verdict

**The pipeline is FAR more complete than "built but dark" implies.** Phases 0→3 are
written, typed, point-in-time-honest, **42-test-green**, and wired into a runnable
end-to-end cron tick, a DB schema, a feature-registry entry, and a live API surface
(`GET /mind/credibility`). It is dormant for **two trivial reasons**, not missing code:

1. **`VOICE_PANEL = ()` is empty** (`cosmu/config/voices.py`) — pre-registration is a
   deliberate operator act, and nobody has registered a voice. An empty panel makes
   every pass honestly do nothing.
2. **`cosmu.ingest.voices_pass` is on no Modal schedule.** The fleet caps at 5 schedules
   (Modal Free); the pass is built to "ride" the existing 4-hourly `tick` slot exactly
   like the already-live observe-only `cosmu.strategy.agent_run` does — but that line was
   never added.

**Leakage-risk verdict: LOW / well-defended.** The CrowdIntel trap (scoring a claim with
its later outcome and feeding that back to pre-outcome time) is explicitly designed out and
explicitly tested. Outcomes resolve with `now = as_of`; a claim whose horizon extends past
`now` is `pending`, never resolved into the future; the PIT history recomputes the snapshot
at each step `t` so the authority used at `t` reflects only outcomes observed by `t`.

**Is this the fastest edge lever? Partly.** Waking it observe-only is ~1 hour of work
(register voices + add one cron line) and is genuinely cheap and reversible. But the
*binding constraint is hypothesis quality, not plumbing* — specifically **which voices**
are registered and whether any of them actually carry walk-forward skill. The pipeline
will faithfully tell you "0/N voices have skill" with honest `n`, which is the same answer
the rest of the edge hunt keeps producing. Recommend: **wake it observe-only now** (cheap
data accrual, no money path), but treat it as a *data-collection* milestone whose payoff is
weeks out (skill needs resolved claims over real horizons), not an immediate edge.

---

## 1. WHAT is built vs dark

### The data model (claims → outcomes → authority), all in `apps/engine/cosmu/`

| Phase | File | What it does | Tested |
|---|---|---|---|
| 0 — timelines | `data/sources/voices.py` | Pull a handle's recent posts as PIT-stamped raw `VoicePost` text (X-via-Grok / Reddit / RSS). `ts == available_at` (a public post is knowable when posted). Key-gated → `[]` keyless. Has `fetch_timeline_history` for backfill replay. | `test_voices.py` |
| 1 — claim extraction | `mind/claims.py` | LLM-as-extractor turns each predictive utterance into a typed `Claim {entity, direction, horizon, conviction, ts}`. Pydantic `extra="forbid"`; un-parseable items dropped; **claim ts STAMPED from the post, never model-proposed** (can't read the future). No key → `[]`. | `test_claim_extraction.py` |
| 2 — outcome resolution | `mind/outcomes.py` | **Deterministic, NO LLM.** Resolve each claim vs OHLC bars (entry = last bar ≤ claim ts; exit = first bar ≥ ts+horizon), classify hit/miss vs the **base rate** of that (entity, horizon, direction). Per-author `skill` = Brier-skill-score vs base, **sample-shrunk** (`PRIOR_STRENGTH=20`). A spammer at base rate → skill ~0. | `test_outcome_resolution.py` |
| 3 — primacy + authority | `mind/authority.py` | **Deterministic, NO LLM.** (1) primacy (who said it first), (2) lead-lag vs an event timeline (foresight vs echo), (3) personalized PageRank over who-cites-whom **anchored to the Phase-2 skill** (influence ≠ authority). Emits two PIT features. | `test_social_authority.py` |

### The wiring (the parts the brief said were missing — they exist)

- **`ingest/voices_pass.py`** — the credibility cron tick, end-to-end: Phase 0 pull →
  store new posts in `market_events` (deduped) → Phase 1 extract NEW posts only (capped by
  `MAX_EXTRACTIONS_PER_PASS=100`) → typed rows in `voice_claims` → Phase 2/3 recompute over
  the **whole** corpus → upsert `voice_scoreboard` + append `author_authority` /
  `authority_weighted_claim_signal` to `alt_data`. Runnable: `python3 -m cosmu.ingest.voices_pass`.
  Tested: `test_voices_pass.py`.
- **`config/voices.py`** — `VOICE_PANEL` (the operator's pre-registered list, **empty**),
  entity→bar-symbol routing, hard per-pass caps.
- **`config/feature_registry.py`** — both features registered, `tier1`, `asset_classes=["crypto"]`,
  with `asof_semantics = "snapshot minted at observation time (no look-ahead)"`.
- **DB schema** — `voice_claims` + `voice_scoreboard` in `knowledge/schema_postgres.sql`
  (and `schema.sql`). Append-only, deduped.
- **API** — `GET /mind/credibility` (`api/routers/mind.py`) serves `voice_scoreboard`,
  skill DESC NULLS last, honest empty panel, untested→NULL never coerced to 0. Typed models
  in `api/models/credibility.py`. Front-end reference in `apps/web/components/indexes/define-index.tsx`.
- **A second consumer** — `indexes/run.py` + `indexes/compute.py` reuse the same social-authority
  scorer through a generalized "index" framework (`compute_social_point`).

### What is genuinely dark (never run on real data)

- **The pipeline has never executed against a real timeline** because the panel is empty and
  nothing schedules it. Every test injects fixtures; prod `voice_claims` / `voice_scoreboard`
  are empty.
- **No event timeline is fed to Phase 3 yet.** `authority.py` *wants* an `Event` list
  (GDELT/news/on-chain) for lead-lag; the voices pass currently calls `compute_authority`
  with `events` unset, so every claim's lead-lag is `"none"` (mild `NEUTRAL_LEADLAG=0.75`
  discount). The epic explicitly notes the `market_events` store IS the event timeline
  `authority.py` already wants — a follow-up, not a blocker.

### NOT part of this lane (avoid conflation)

- **`realtime_worker_enabled`** (`config/settings.py:195`) toggles the **realtime bar/event
  recorder** (`realtime/worker.py`), a *separate* lane (epic P3). It does **not** gate the
  credibility pass. The credibility pass is gated only by the empty panel + the missing cron line.
- **`mind/signal_builder.py`** is the NL→strategy claim-grounding step, unrelated to voice credibility.

---

## 2. WHAT it would DO on real data, observe-only

With a non-empty panel + an LLM key (`xai_api_key` preferred, already on Railway; `openrouter_api_key`
fallback) running on a cron cadence, each pass:

1. Pulls each panel voice's newest ≤25 posts, stores new ones durably in `market_events`.
2. Sends NEW posts (≤100/pass) to a cheap LLM (`grok-3-mini` / `gpt-4o-mini`) for STRUCTURE-only
   extraction → typed `Claim` rows.
3. Deterministically resolves every stored claim against daily bars, scores each voice's
   Brier-skill-vs-base (shrunk), and runs the skill-anchored PageRank.
4. Writes one human-readable `voice_scoreboard` row per voice (skill / authority / primacy /
   calibration, NULL while untested) and appends the two PIT features to `alt_data` — the
   series the Gate would later train on, **and** the source-credibility evidence Gate B
   (agentic-lane) wants ("alpha or just beta — was he first, or following momentum?").

**It PROPOSES / SCORES only. It never funds or fires an order.** Hard railguard: the LLM is
never on the gate/scoring/money path (it proposes claim *structure*; everything downstream is
deterministic). The features must still **earn their place out-of-sample through the existing
Gate** before any strategy uses them — and a strategy that uses them still needs a human click
to go live. Zero-capital by construction, consistent with the locked S×A×V model.

---

## 3. The EXACT minimal first step to wake it OBSERVE-ONLY

No new toggle is needed — the lane has none; it is gated by data + schedule.

**Step 1 — register a pre-registered voice panel** (`cosmu/config/voices.py`).
Add a handful of voices with a one-line WHY each (the anti-survivorship discipline: register
BEFORE outcomes are known). Crypto-focused, since the features are `asset_classes=["crypto"]`
and `ENTITY_BARS_SYMBOL` maps BTC/ETH/SOL/etc. Mix X (needs `xai_api_key`), Reddit (keyless),
RSS (keyless) so it degrades gracefully if a key is absent. The epic's done-criterion is
**≥10 sources carrying walk-forward skill with honest n**.

**Step 2 — schedule the pass.** Add one line to the 4-hourly `tick` in `apps/engine/remote/app.py`
(it already runs `cosmu.strategy.agent_run` observe-only the same way), e.g.
`_run(["cosmu.ingest.voices_pass"])`. This rides the existing slot (Modal Free = 5 schedules,
all taken). `modal deploy` to ship (the fleet is a manual snapshot, not push-deploy).

**Step 3 — (optional, same pass) feed the event timeline.** Pass `market_events` rows as
`Event`s into `compute_authority` so lead-lag (foresight vs echo) activates. Pure upside,
deterministic, $0; can follow.

**Step 4 — verify.** After a few passes, `GET /mind/credibility` shows the panel with
accruing `n_posts` / `n_claims` and NULL skill until claims resolve over their horizons.
Run `profile-source` on `authority_weighted_claim_signal` (already a passing test pattern:
`test_profile_source_go_on_backfilled_pit_history`).

**Cost:** compute $0 marginal (rides existing crons); Phases 2–3 deterministic = $0; LLM
claim extraction bounded by `MAX_*` caps + the `market_events` dedup (an already-stored post
is never re-extracted, so re-runs are free). Per epic §8b: a few cents/day at panel scale.

**To accelerate skill accrual** (skill needs *resolved* claims = past horizons), backfill via
`fetch_timeline_history` + `signal_history()` to replay the authority series from historical
posts — the providers already PIT-stamp `available_at == ts` for exactly this. This turns a
weeks-long wait into an immediate walk-forward series, while staying look-ahead-honest.

---

## 4. RISKS — leakage & look-ahead

### Does the CrowdIntel trap apply? **No — it is explicitly designed out and tested.**

The trap = scoring a claim with its later outcome, then using that score at times *before*
the outcome was known. The defenses:

- **`outcomes.py`:** entry uses only bars knowable at claim time (`_entry_bar`: `bar.ts <= at`);
  exit is the first bar **at/after** the horizon; a claim whose exit bar lands after `now` is
  `pending` (`exit_b.ts > now` → not resolved). Scoring a prediction against what actually
  happened, with PIT entry, is the *correct* design — not leakage.
- **`authority.py::compute_authority`:** filters `c.ts <= as_of` for claims/posts/events AND
  resolves outcomes with `now = as_of`. The authority weight at `as_of` reflects only outcomes
  observed by `as_of`.
- **`authority.py::signal_history`:** recomputes the snapshot at each step `t` and emits
  `AltDataPoint(ts=t, available_at=t)` — a real-time judgement is knowable only when made.
- **Tests that lock this in:** `test_history_is_point_in_time_no_lookahead` (asserts
  `available_at >= ts`), `test_entry_is_point_in_time_last_bar_at_or_before_claim`,
  `test_pending_when_horizon_extends_past_now`, `test_spammer_at_base_rate_scores_near_zero_but_sniper_scores_high`,
  `test_profile_source_go_on_backfilled_pit_history`. **42/42 green** this session.

### Does the parallel leakage tripwire apply? **Yes, and it's a clean fit.**

The shuffle-placebo / time-shuffle discipline from `research/llm_narrative_pipeline.py` +
`llm_narrative_cohort.py` (content-only scoring + a disconfirmer that time-shuffles the scores)
is the exact pattern to point at `authority_weighted_claim_signal` before it earns gate trust.
And the feature does **not** bypass the Gate's own defenses: as a `tier1` alt feature it faces
the finder's deflated-Sharpe / CSCV-PBO / WFO-holdout machinery (`lab/finder.py`) like any
other feature. Recommend a feature-specific disconfirmer at wake-time:
**lead-lag symmetry** (does the signal "work" identically when the event timeline is rotated /
when claims are shuffled in time? then it's spurious, the astro lesson) — the harness exists.

### Other honest risks (not leakage, but edge-killers)

- **Popularity = alpha death.** The epic flags "follower count is an anti-prior; expect
  WSB-style alpha death after popularity." Pre-registration mitigates survivorship but not the
  decay of a once-good voice. The Brier-skill + shrinkage will surface this honestly (skill
  drifts to ~0), but only *after* enough resolved claims.
- **Thin n for a long time.** Skill needs resolved claims; a 1m/1d horizon resolves fast but a
  3m/1y claim resolves slowly. Expect NULL skill on the scoreboard for weeks unless you backfill.
- **Base-rate fragility on small panels.** `_base_rate` is computed over the bars window; with a
  narrow entity set the base rate is noisy. Not a leak, but it widens the skill confidence interval.

---

## 5. Is this genuinely the fastest edge lever, or is the constraint hypothesis quality?

**The constraint is hypothesis quality (which voices), not plumbing.** Honest assessment:

- The *cost to wake* is tiny (~1 hour, fully reversible, $0-marginal, zero money path) — so on a
  cost-adjusted basis it is **worth doing now** purely to start accruing the data, and because it
  is the data substrate Gate B (agentic-lane) needs.
- But the *payoff is not immediate*. Unlike a backtest sweep that answers today, credibility skill
  needs resolved claims over real horizons. The pipeline's most likely first answer is the same one
  the edge hunt keeps producing: **"0/N voices carry skill after costs"** — honestly reported, which
  is the machine working, not failing.
- The genuine leverage is **horizontal**: these features (`author_authority`, primacy, lead-lag)
  are precisely the "alpha or just beta — was he first, or following momentum?" forensics the
  **agentic-lane Gate B** epic specifies (`docs/epics/agentic-lane.md` §5). So waking this lane is
  best framed as **building Gate B's evidence substrate**, not as a standalone alpha source.

### Ranking vs the other edge options (memory: edge-hunt themes + agentic-lane)

| Lever | Cost to start | Time-to-signal | Money path | Best framing |
|---|---|---|---|---|
| **Wake credibility observe-only** (this) | ~1h, $0-marginal | Weeks (or instant via backfill) | None (proposes/scores) | Data substrate for Gate B; honest source scoreboard |
| Cross-sectional momentum (xsec) | Spec + sweep | Today (backtest) | Gate-funded | Primary direction per `strategy_research_direction` |
| Funding contrarian filter | Spec + sweep | Today | Gate-funded | Cheap, visible on /strategies |
| Prediction-market / Polymarket events | Backfill CLOB first | Days | Gate-funded | Edge#1 horizon/#2 favorite (needs historical odds ingest) |

**Recommendation (ranked):**
1. Keep the **xsec-momentum + funding** quant sweeps as the primary money-path edge hunt (they
   answer today, Gate-funded).
2. **Wake the credibility pass observe-only in parallel** — it is cheap, reversible, zero-capital,
   and it is the only one of these that builds the *agentic-lane Gate B* substrate. Register a
   small crypto-voice panel + the one cron line + (ideally) the historical backfill so skill
   accrues immediately rather than in weeks.
3. Add the **lead-lag-symmetry disconfirmer** at wake-time so the first feature can't pass on a
   spurious periodic/echo artifact.

**Bottom line:** the lane is not "build it" — it's "register voices + one cron line + (optional)
backfill." It is ready. The honest expectation is a slow-accruing, look-ahead-clean source
scoreboard whose real value is feeding Gate B, not an overnight alpha.

---

## Appendix — key files

- `apps/engine/cosmu/mind/claims.py` — Phase 1 LLM claim extraction (typed, PIT-stamped)
- `apps/engine/cosmu/mind/outcomes.py` — Phase 2 deterministic resolution + Brier-skill-vs-base
- `apps/engine/cosmu/mind/authority.py` — Phase 3 primacy + lead-lag + skill-anchored PageRank + PIT history
- `apps/engine/cosmu/ingest/voices_pass.py` — the end-to-end credibility cron tick (runnable)
- `apps/engine/cosmu/config/voices.py` — **`VOICE_PANEL = ()` (empty)** + caps + entity routing
- `apps/engine/cosmu/config/feature_registry.py` — both features registered (tier1, crypto)
- `apps/engine/cosmu/api/routers/mind.py` — `GET /mind/credibility` scoreboard surface
- `apps/engine/cosmu/knowledge/schema_postgres.sql` — `voice_claims` + `voice_scoreboard`
- `apps/engine/remote/app.py` — the Modal fleet; `tick` (4h) is where the pass should ride
- `apps/engine/cosmu/indexes/run.py` — second consumer (generalized index framework)
- `docs/epics/realtime-data-lane.md` §4 — the credibility-pipeline epic (P2 = the open milestone)
- `docs/epics/agentic-lane.md` §5 — Gate B; this pipeline is its source-credibility substrate
- Tests (42 green): `test_claim_extraction.py`, `test_outcome_resolution.py`,
  `test_social_authority.py`, `test_voices.py`, `test_voices_pass.py`, `test_mind_credibility.py`
