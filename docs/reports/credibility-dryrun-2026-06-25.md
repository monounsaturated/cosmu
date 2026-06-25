# Credibility / voices lane — OFFLINE DRY-RUN on real data (2026-06-25)

EXPERIMENT, zero production impact. This is the **empirical** complement to the static scout
(`credibility-pipeline-scout-2026-06-25.md`, PR #386). The scout *read* the lane and asserted it
separates skill from noise and is look-ahead-clean. This report **ran** it: a constructed voice
panel with KNOWN behaviors scored end-to-end against REAL market bars (keyless), to prove those
claims with numbers — and to build + fire the **lead-lag-symmetry disconfirmer** the scout
recommended adding at wake-time (its §4 "the astro lesson").

No prod schedule, no toggle, no Gate, no DB write, no wake, no merge of lane code. The lane
(`cosmu.mind.{claims,outcomes,authority}`) was imported **unchanged**; only daily bars were read.

Harness: `apps/engine/scripts/research/credibility_dryrun.py` — run
`python3 -m scripts.research.credibility_dryrun` from `apps/engine`. Deterministic (seeded);
re-runnable; touches no DB and no money path.

---

## TL;DR

1. **Does the scoreboard separate skill from base-rate? YES, decisively.** On 13 months of real
   BTC/ETH/SOL/DOGE daily bars, the sniper (early + right on the rare big moves) scores
   **skill 0.701**; the spammer (fires the dominant drift on 228 days) scores **0.000**; the
   late-follower (echoes a move already on the tape) scores **0.000**. Influence ≠ authority,
   confirmed on real data, not fixtures.

2. **Does lead-lag kill the follower? YES.** The time-reversal symmetry disconfirmer (the astro
   test) gives the follower **forward-skill 0.000 vs backward-skill 0.694 → asymmetry −0.694**:
   its calls describe the past, not the future. The sniper is the mirror image
   (**fwd 0.701 / bwd 0.000 / asymmetry +0.701** — genuine foresight). A pure echo is caught
   exactly as the astro hierarchical-Bayes study caught non-causal astro signals.

3. **The data-feed requirement is NOT the binding constraint — keys and plumbing exist.** Both
   `XAI_API_KEY` (X-via-Grok retrieval + LLM extraction) and `OPENROUTER_API_KEY` (extraction
   fallback) are present in `.env.local` today. Reddit + RSS feeds are keyless. The lane can run
   this afternoon. The binding constraint is **hypothesis quality — which voices** (the panel is
   empty) — plus **operational** (Modal Free's 5-schedule cap is full, so the pass must *ride*
   `tick`, not get a 6th slot).

4. **Verdict: worth waking observe-only; first honest conclusion will most likely be "0/N voices
   carry skill."** The machinery is correct and look-ahead-clean (proven below). The payoff is a
   slow-accruing, honest source scoreboard whose real value is feeding agentic-lane Gate B
   ("alpha or just beta — was he first or following momentum?"), not overnight alpha.

---

## 1. The experiment

### Outcome timeline — REAL bars (keyless)

`default_crypto_reference().fetch_bars(sym, "1d", limit=400)` for four entities. ~13 months,
a genuinely **declining** window (so "up" is not free — base rates are non-trivial):

| Entity | Bars | Range | Close drift |
|---|---|---|---|
| BTC | 400 | 2025-05-21 → 2026-06-24 | 109,644 → 61,078 |
| ETH | 400 | 2025-05-21 → 2026-06-24 | 2,551 → 1,622 |
| SOL | 400 | 2025-05-21 → 2026-06-24 | 173.5 → 68.1 |
| DOGE | 400 | 2025-05-21 → 2026-06-24 | 0.23 → 0.08 |

### Three voices with KNOWN behavior (claims generated FROM the real bars)

Horizon `3d`, claims constructed deterministically so each archetype's behavior is deliberate and
auditable:

- **`@sniper`** — calls the realized direction of the **rarest/biggest** 3d moves (top-12 by
  magnitude per entity), stamped at the move's START. Early + right on the hard calls → should
  beat the base rate. 48 claims.
- **`@spammer`** — fires the window's **dominant drift** direction on ~50 distinct days per entity.
  Loud, often "right" in absolute terms in a trending tape, but only at the base rate → no excess
  skill. 228 claims.
- **`@follower`** — after each big realized move, posts that the move **continues** (same
  direction), stamped at the move's END (`i + horizon`). It is reacting to news already on the
  tape — a momentum echo. Its forward 3d outcome from there is ~a coin flip. 48 claims.

Total: **324 claims, 156 events, as_of 2026-06-25.** (Events = a dated marker at the end of each
top-decile-magnitude move, the lead-lag input.)

---

## 2. Result A — the sample scoreboard (Phase 2 + Phase 3)

`resolve_claims` → `score_authors` → `compute_authority`, all deterministic, `now = as_of`:

```
handle       n_res    hit   base  excess     BSS   skill  authority  primacy
@sniper         48  1.000  0.416   0.584   0.993   0.701     1.0000    0.542
@spammer       228  0.539  0.448   0.092  -0.559   0.000     0.0000    0.474
@follower       48  0.312  0.416  -0.103  -1.603   0.000     0.0000    0.042
```

Reading it:

- **`@sniper`** — hit-rate 1.000 vs a base rate of 0.416 (**excess +0.584**), Brier-skill-score
  0.993, headline **skill 0.701** (BSS shrunk by `n/(n+20)` for sample size). It also captures
  **100% of the authority** (skill-anchored PageRank teleports to the only proven node) and the
  highest primacy (0.542 — it spoke first on its topics).
- **`@spammer`** — hit-rate 0.539 (it *is* "often right" in absolute terms, exactly the influence
  trap) but its base rate is 0.448 → **excess only +0.092**, and a conviction-0.85 forecast is
  badly calibrated to a near-coin outcome → **BSS −0.559 → skill 0.000**. Loud, often right,
  **zero authority.** This is the "spammer at base rate scores ~0" invariant holding on real bars.
- **`@follower`** — hit-rate 0.312 is *below* the base rate (momentum-continuation after a big
  move mean-reverts in this tape) → **excess −0.103, BSS −1.603, skill 0.000, authority 0.000,
  primacy 0.042** (it is always an echo, never first).

**Skill is cleanly separated: 0.701 / 0.000 / 0.000.** The metric rewards beating the base rate,
not being loud or being right-in-absolute-terms.

---

## 3. Result B — the lead-lag SYMMETRY disconfirmer (the astro test)

The astro lesson (`astro_hier_bayes_2026-06-15` memory): if an apparent "skill" is identical at
lead `h=+1` and lag `h=-1`, the relationship is **non-causal** — correlated with, not predictive
of, the outcome. Applied to voices: resolve each voice's calls **forward** (the real test — did the
+horizon move match?) and **backward** (did the −horizon move that *already happened* match?). A
genuine forecaster is **asymmetric** (high forward, chance backward); a pure echo is **symmetric**
or inverted (backward ≥ forward, because it is describing the past).

```
handle        skill_fwd  skill_bwd  asymmetry         verdict
@sniper           0.701      0.000      0.701    CAUSAL(foresight)
@spammer          0.000      0.000      0.000    NON-CAUSAL echo
@follower         0.000      0.694     -0.694    NON-CAUSAL echo
```

- **`@follower` is KILLED.** Forward skill 0.000, backward skill **0.694** → asymmetry **−0.694**.
  Its calls predict the future no better than chance but match the immediately-preceding move
  almost perfectly — the exact signature of reacting to news, not foreseeing it. **The
  late-follower gets killed by the disconfirmer, as required.**
- **`@sniper` survives** with the opposite, healthy profile: it predicts the future (0.701) and has
  *no* special relationship to the past (0.000) → asymmetry **+0.701**, genuine foresight.
- **`@spammer`** is flat at 0.000 both ways — no skill in either time direction (pure base-rate
  noise), correctly earning nothing.

This is the standing disconfirmer the scout (§4) recommended adding at wake-time. It works, and it
is exactly the astro-style test that has repeatedly saved this project from spurious periodic/echo
"edges."

---

## 4. Result C — two more robustness checks (no look-ahead, no timing artifact)

**Shuffle null** — keep the sniper's claim timestamps, randomize the directions 50×. If the
"skill" lived in *when* it spoke rather than *what* it said, the null would reproduce it:

```
real sniper skill = 0.701 | shuffled-direction null: mean 0.000, max 0.000 (n=50) | permutation p = 0.020
→ PASS — skill is in the CALL, not the timing
```

The edge is entirely in the directional call; destroying the call→outcome link collapses skill to
exactly 0. (p=0.020 is floored by the 50-shuffle resolution; the separation is total.)

**Point-in-time** — recompute the sniper's record at a mid-history snapshot:

```
as_of 2025-12-07: sniper has 25 resolved claims; as_of 2026-06-25: 48 resolved.
→ PASS — fewer claims resolved earlier (no look-ahead)
```

A snapshot mid-history sees only the claims whose horizons have already resolved by that date —
the lane never reads the future. This empirically reproduces what
`test_history_is_point_in_time_no_lookahead` asserts on fixtures.

**Authority-weighted signal** (per entity, as_of now): BTC/ETH/SOL all read **−1.0** (the only
high-authority voice, the sniper, made down-calls that dominate the credibility-weighted
consensus); DOGE reads **None** — honest abstain, no active claim in the 30-day window. Worth
noting: with a one-voice authority mass the signal saturates to ±1; a real multi-voice panel would
produce a graded signal. This is a *construction* artifact of the toy panel, not a lane bug.

---

## 5. The data-feed requirement — what a REAL answer needs

The lane is fed by three Phase-0 sources (`cosmu/data/sources/voices.py`). Profiles:

| Source | Key needed | Cost | Historical depth | PIT honesty |
|---|---|---|---|---|
| **Reddit** (`RedditVoiceProvider`) | none (public JSON) | $0 | ~1,000 items/user, paginated | `available_at == ts` on backfill |
| **RSS/Atom** (`RssVoiceProvider`) | none | $0 | shallow (30–100 entries; no deep archive) | `available_at == ts` on backfill |
| **X via xAI Grok LiveSearch** (`XaiVoiceProvider`) | `XAI_API_KEY` | paid (Grok LiveSearch) | **best-effort** — LiveSearch is not a guaranteed archive | `available_at = read time` |
| Phase 1 extraction (`mind/claims.py`) | `XAI_API_KEY` *or* `OPENROUTER_API_KEY` | cheap (`grok-3-mini` / `gpt-4o-mini`), capped at `MAX_EXTRACTIONS_PER_PASS=100`, deduped so re-runs are free | n/a | claim ts stamped from the post |

**Verified present in `.env.local` today: `XAI_API_KEY` and `OPENROUTER_API_KEY` (and
`DATABASE_URL`, `API_SECRET_KEY`).** So the lane needs **no new credentials** to run — X
retrieval, LLM extraction, Reddit, and RSS are all available now.

### What a real answer actually requires (in priority order)

1. **A pre-registered voice panel** — `VOICE_PANEL` is `()`. This is the real first input and the
   *binding* one. It must be crypto-focused (features are `asset_classes=["crypto"]`,
   `ENTITY_BARS_SYMBOL` covers BTC/ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK/DOT/LTC) and registered
   *before* outcomes are known (anti-survivorship). The epic's done-criterion is **≥10 sources
   carrying walk-forward skill with honest n**.
2. **Resolved claims over real horizons** — skill needs claims whose horizons have *elapsed*. A 1d/3d
   horizon resolves fast; a 1m/3m/1y claim is `pending` for weeks/months. Two ways to get there:
   - **Live accrual:** run the pass on a cadence; skill is NULL on the scoreboard until horizons
     resolve (honest, but slow).
   - **Backfill (recommended):** `fetch_timeline_history` + `signal_history()` replay the authority
     series from historical posts with `available_at == ts` — turning a weeks-long wait into an
     immediate, still look-ahead-honest walk-forward series. Reddit (deep) and RSS (shallow) backfill
     keyless; X backfill is best-effort via LiveSearch.
3. **(Optional, pure upside) an event timeline** — pass `market_events` rows as `Event`s into
   `compute_authority` so lead-lag (foresight vs echo) activates in production. Today the pass calls
   it with `events` unset → every claim's lead-lag is `"none"` (mild 0.75 discount), so the
   foresight-vs-echo separation proven in §3 is *latent* until wired. Deterministic, $0.
4. **One cron line** — `voices_pass` is on no Modal schedule, and **Modal Free's 5-schedule cap is
   full** (`ingest` hourly, `heartbeat`, `tick` 4h, `cold_tier_maintenance` weekly, `daily_backup`
   daily). So the pass must **ride** the existing 4-hourly `tick` slot (one `_run([...])` line in
   `apps/engine/remote/app.py`), then `modal deploy` (manual snapshot, not push-deploy).

**Binding constraint = hypothesis quality (which voices) + the operational ride-on-tick, NOT keys
and NOT plumbing.** Compute is $0-marginal; extraction is a few cents/day at panel scale.

---

## 6. Honest verdict — is this lane worth waking?

**Yes, observe-only — but framed correctly.**

- **It works.** On real data, the scoreboard separates skill (0.701) from loud-but-base-rate
  (0.000) from echo (0.000); the disconfirmer kills the echo (asymmetry −0.694); the shuffle null
  and the PIT snapshot confirm the result is in the call, not the timing or the future. The
  machinery the scout described statically is **empirically sound**.
- **It is cheap and reversible.** ~1 hour to wake (register a panel + one cron line + ideally a
  backfill), $0-marginal, zero money path. The LLM proposes claim *structure* only; everything that
  scores or weights is deterministic; features still face the full Gate OOS before any strategy uses
  them; live still needs a human click.
- **Its first conclusion will most likely be "0/N voices carry skill after costs."** That is the
  same honest answer the rest of the edge hunt produces — the machine working, not failing. The
  value is the *honest source scoreboard* + the PIT features, which are precisely the
  agentic-lane **Gate B** evidence substrate ("alpha or just beta — was he first, or following
  momentum?"). Frame waking it as **building Gate B's substrate**, not as standalone alpha.
- **The one thing to wire at wake-time** (beyond a panel) is the **event timeline into
  `compute_authority`** — without it the foresight-vs-echo separation proven in §3 stays latent in
  production. And keep this **time-reversal/shuffle disconfirmer** as the standing tripwire on
  `authority_weighted_claim_signal` before it earns Gate trust.

**Bottom line:** the lane is not "build it" — it is "register voices + one cron line + (optional)
backfill + wire the event timeline." It is ready, it is honest, and this dry-run proves on real
data that it does what it claims. Expect a slow-accruing, look-ahead-clean source scoreboard whose
real payoff is Gate B, not overnight alpha.

---

## Appendix — reproduce

```
cd apps/engine && python3 -m scripts.research.credibility_dryrun
```

Harness: `apps/engine/scripts/research/credibility_dryrun.py` (imports the lane unchanged; reads
keyless daily bars only; deterministic seed; no DB / no money path).

Lane under test (unchanged): `cosmu/mind/{claims,outcomes,authority}.py`,
`cosmu/ingest/voices_pass.py`, `cosmu/config/voices.py`. Existing lane tests re-run green this
session: `test_outcome_resolution.py`, `test_social_authority.py`, `test_mind_credibility.py`
(28 passed).
