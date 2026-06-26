# LLM / Mind / Authority-Index stack — deep assessment vs the operator's vision (2026-06-26)

READ-ONLY assessment. No code changed. Maps the operator's **authority-index socle** vision against
what is already built in the engine, file-by-file, and names the smallest concrete first build that
turns the vision into a running thing.

**Headline: ~85% of the vision already exists, built, tested (28 lane tests green), and look-ahead-clean.
It is dormant for two trivial reasons — an empty voice panel and one missing cron line — not missing code.
The "take the leap" first step is ~1–2 hours of wiring, observe-only, $0-marginal.**

---

## 0. The operator's vision, restated as a pipeline

> A SOCLE that (1) gathers data → (2) formats it with an LLM → (3) monitors a specific situation →
> (4) builds an INDEX → (5) strategies are based off these indexes. Within an index, each DATA SOURCE
> gets an **AUTHORITY SCORE** from how good its PAST CALLS were — a crypto influencer right 9/10 times
> on BTC-up = high authority, computed by matching the **timestamp of the tweet/release** vs the
> **timestamp of the price move**. Modules reused differently at different pipeline steps. Hard parts he
> named: temporal consistency of scores, quantifying qualitative LLM data (anchor it factually on
> price-impact), ingestion frequency, accuracy.

This is, almost verbatim, the **"PageRank for credibility"** lane (`cosmu/mind/`) plus the **Indexes**
epic (`cosmu/indexes/`). Both are shipped. The vision is not aspirational here — it is mostly *deployed
but un-fed*.

---

## 1. Step-by-step MAP — vision vs what's BUILT

| Operator's step | Built? | Where (file evidence) |
|---|---|---|
| **(1) Gather data** — voice timelines (X/Reddit/newsletters), PIT-stamped | ✅ BUILT | `cosmu/data/sources/voices.py` (`XaiVoiceProvider` via Grok LiveSearch, `RedditVoiceProvider`, `RssVoiceProvider`); the pass stores deduped posts in `market_events` (provider="voices") — `cosmu/ingest/voices_pass.py:61-94,225-243` |
| **(2) Format it with an LLM** — turn prose into structured, typed data | ✅ BUILT | `cosmu/mind/claims.py` — an LLM-as-extractor turns each post into a typed `Claim{entity,direction,horizon,conviction,ts}`, Pydantic `extra="forbid"`, retry-on-invalid, **drop** un-parseable. The LLM proposes STRUCTURE only; never scores. Also `cosmu/ingest/llm_formatter.py` for the generic case. |
| **(3) Monitor a situation** — a named, constantly-refreshed numeric series | ✅ BUILT | Indexes: `cosmu/indexes/{spec,registry,compute,monitor,run,routing}.py`; four kinds (`single_account`, `social_bucket`, `event_topic`, `prompt_rubric`); refreshed per cadence into `alt_data` (provider='index'); freshness + ranking-stability monitor in `monitor.py`. |
| **(4) Build an INDEX with per-source AUTHORITY from past-call accuracy** | ✅ BUILT — **this is the heart and it is exactly his idea** | `cosmu/mind/outcomes.py` (Phase 2) + `cosmu/mind/authority.py` (Phase 3). See §1.1 below. |
| **(5) Strategies built off the indexes** | ◑ HALF-BUILT | The two authority features + every `idx_<id>` are **registered, store-routed, key-off-able** (`cosmu/config/feature_registry.py:264-291`, `cosmu/indexes/routing.py`). A quant `StrategySpec` *can* read them. The gap: the routing isn't merged into the gate/backtest construction sites by default, and the **LLM** strategy lane's Mind panel does not yet read the authority signal (§4). |

### 1.1 "Authority from call-accuracy vs price-timestamp" — IS this exactly his idea? YES.

His description: *match the timestamp of the tweet vs the timestamp of the price move; right 9/10 times → high authority.*

The code does precisely this, deterministically, with no LLM on the scoring path:

- **`outcomes.py::resolve_claim`** — entry price = the last bar knowable **at the claim's timestamp**
  (`_entry_bar`, `bar.ts <= claim.ts`), exit = the first bar **at/after `claim.ts + horizon`**
  (`_exit_bar`). A `hit` is whether the claimed direction matched the realized move (flat-band aware).
  This is literally "tweet-timestamp → price-move-at-horizon".
- **It does NOT use raw hit-rate** — it scores each call **against the base rate** of that
  (entity, horizon, direction) over every window in the bars (`_base_rate`), then computes a
  **Brier Skill Score vs that base rate**, **shrunk for sample size** (`n/(n+20)`,
  `PRIOR_STRENGTH=20`). This is *better* than his "9/10 times" framing: a spammer who fires the
  dominant drift and is "often right" scores **~0** (no excess over base), and a lucky 3-for-3 is
  shrunk toward 0. The headline scalar is `AuthorTrackRecord.skill ∈ [0,1]`.
- **`authority.py`** fuses three signals into the per-voice authority and a per-asset signal:
  1. **Primacy** — who said it FIRST (`annotate_primacy`); later same-direction calls in a 7d window
     are echoes, down-weighted.
  2. **Lead-lag vs an event timeline** — a claim that PRECEDES a same-entity event is *evidence*
     (foresight); one that FOLLOWS it is an *echo* (`classify_lead_lag`).
  3. **Citation-graph personalized PageRank ANCHORED to the Phase-2 skill** (`personalized_pagerank`,
     teleport ∝ each voice's `skill`) — so **influence ≠ authority**: a loud, well-cited but *wrong*
     account (skill ~0) cited only by other noise accumulates ~no authority.
- It emits two **point-in-time features with history**: `author_authority[handle]` and
  `authority_weighted_claim_signal[entity]` (`AuthorityProvider.fetch_series`).

**Empirically proven on real data** (`docs/reports/credibility-dryrun-2026-06-25.md`): on 13 months of
real BTC/ETH/SOL/DOGE bars, a constructed sniper (early + right) scores **skill 0.701**, a spammer
(loud, base-rate) **0.000**, a late-follower **0.000**. The separation is total and the call→outcome
link is the source of the edge (shuffle null collapses it to exactly 0, permutation p=0.020).

**Verdict on §1: the "authority-index from price-anchored call accuracy" socle exists and works.**

---

## 2. The LLM strategy lane (AgentSpec → Gate B)

### Exists? Realistic? Observe-only-live? — YES / YES / YES.

- **`cosmu/strategy/agent_spec.py`** — `AgentSpec` is a typed `kind='llm'` strategy: an NL `rationale`,
  `symbols × venues`, a **mandatory `AgentExitPolicy`** (SL/TP/trailing/time-stop), `max_position_pct`,
  `mode` (autonomous / slack_hitl / manual), `cadence`. It carries **no param_space / no compiled code**
  — an agent reasons, it isn't grid-fitted. Mirrors `StrategySpec`'s role for the LLM model.
- **`agent_loop.py` + `analysts.py`** — "LLM proposes": the Mind's analyst panel
  (Technical · Sentiment · Macro · Social&News · Positioning · OSINT · ML · Memory) reads point-in-time
  signals into weighted `Stance`s; `stances_to_decision` maps the weighted consensus to ONE typed
  `Decision`. **ABSTAIN is honoured** — no data → no Decision (never fabricated). The judge LLM is
  *injected* (heuristic offline, cheap OpenRouter at runtime).
- **`agent_decision.py`** — "deterministic disposes": `finalize_decision` sizes/exits/cautions. Thin or
  single-source signals are **sized down, never auto-discarded** (the operator's risk-machine posture,
  matching agentic-lane.md §5 "single source ≠ kill").
- **`agent_executor.py` + `agent_run.py`** — the **observe-only** executor: for each (symbol × venue)
  product it reasons → finalizes → **records the decision + its trace as an audit event**. **ZERO
  capital by construction** — opens no track, position, or order. It is **already wired into the 4-hourly
  Modal `tick`** (`apps/engine/remote/app.py:201`). `agent_author.py` persists an AgentSpec as a
  `kind='llm'`, `status='screened'`, zero-capital strategy_version.

### Structural flaws / honest gaps in the LLM lane

1. **Gate B is designed, not yet built as a scorer.** `docs/epics/agentic-lane.md` §5 specifies Gate B
   = a score + evidence bundle (unbiased critics, two passes, **source forensics with alpha-vs-beta
   regression**, ticker-anonymization, reverse-evidence disconfirmers). Today the lane has: AgentSpec,
   the observe loop, the Mind panel/`debate.py` (consensus + bull/bear split), and `judge.py`/`rubric.py`
   (LLM-as-judge per pillar). It does **not** have a Gate-B module that produces the evidence bundle or
   runs the LLM-specific disconfirmers. **The good news: the authority track-record (§1) IS the
   source-forensics substrate Gate B's component 4 calls for** ("is he right? alpha or beta? was he
   first?") — the dry-run frames waking the credibility lane as *building Gate B's substrate*.
2. **The per-strategy LLM-spend cap is not wired** (`agent_run.py` header note, P0.5). Volume is low
   today (one global Mind context per run), but it must be capped before scaling an agent fleet.
3. **Venue is recorded, not differentiated.** `default_reason_fn` shares per-symbol context across an
   agent's venues (alt_data has no venue column) — honest, but per-venue funding/feeds is backlogged.

**Net: the LLM lane is real, honest, observe-only-live, and structurally sound. The missing piece is the
Gate-B evidence/forensics scorer — and its hardest input (price-anchored source skill) already exists.**

---

## 3. The HARD PARTS he named — how the code handles each + what's missing

| Hard part (operator's words) | How current code handles it | Missing / risk |
|---|---|---|
| **Temporal consistency of scores** ("same input → same ranking, always") | **FROZEN `transform_version`** pinned into every artifact: `CLAIM_EXTRACT_VERSION`, `OUTCOME_RESOLVE_VERSION`, `AUTHORITY_VERSION="social-authority-v1"`, `INDEX_TRANSFORM_VERSION`. Phases 2–3 are **pure + deterministic** (clock injected, never wall-time). Text indexes run at **temperature 0 behind a content-hash cache**. Same input → same number → stable ranking — his exact requirement, met. | Nothing structural. Old history is never silently re-scored (recompute under a new version is a deliberate act). |
| **Quantifying qualitative LLM data** (his idea: anchor on price-impact) | **Exactly his idea, and it is the design's spine.** The LLM only emits a *typed claim*; the NUMBER (skill) comes from resolving that claim against **real OHLC bars vs the base rate** (`outcomes.py`). Qualitative → quantitative via price-impact, with the LLM nowhere near the score. | None on the social path. Text indexes (`event_topic`/`prompt_rubric`) are scored by an LLM-as-judge rubric, NOT yet price-anchored — that is sentiment-of-news, a weaker quantification than the price-anchored claim path. Worth flagging if he wants *every* index price-anchored. |
| **Ingestion frequency** | Bounded per-pass caps decouple cost from cadence: `MAX_POSTS_PER_VOICE_PER_PASS=25`, `MAX_EXTRACTIONS_PER_PASS=100`, and **`market_events` dedup** means an already-stored post is **never re-extracted** (re-runs are free). Index cadence is per-spec (`cadence_minutes`). Realtime-data-lane epic Tier-1 already moved ingest to 15-min. | The voices pass is on **no schedule** (see §5). Frequency knobs exist; the clock isn't ticking. |
| **Accuracy** | Accuracy is *defined* as Brier-skill-vs-base-rate (not raw hit-rate), **sample-shrunk**, and **calibration error** is tracked (`_calibration_error`, ECE over conviction buckets). The dry-run proves the metric rewards beating the base rate, not being loud. The **lead-lag symmetry disconfirmer** (the astro test) catches echo masquerading as skill. | Accuracy improves only as claims *resolve* over real horizons (1d/3d fast; 1m/3m slow). Backfill (`fetch_timeline_history` + `signal_history`) turns a weeks-long wait into an immediate look-ahead-honest walk-forward series — recommended, keyless for Reddit/RSS. |

---

## 4. The "TAKE THE LEAP" plan — the SMALLEST first build that makes it run

The vision is one panel and one cron line away from being a live, accruing thing. In strict order:

**Step 0 (prerequisite, ~5 min): apply the two migrations in prod** if not already —
`voice_claims`/`voice_scoreboard` ship in `schema.sql` and `indexes` has
`migrations/2026-06-15_indexes.sql`. The code fails-open until applied (honest "not active" state).

**Step 1 (THE leap, ~30 min): register a pre-registered voice panel.** `config/voices.py::VOICE_PANEL`
is `()` today — this is the *binding* input. Add 5–15 **crypto-focused** voices (entities must be in
`ENTITY_BARS_SYMBOL`: BTC/ETH/SOL/BNB/XRP/DOGE/ADA/AVAX/LINK/DOT/LTC), each with a one-line `why`
written **before** any outcome is known (anti-survivorship — the whole point). Keys already present in
`.env.local` (`XAI_API_KEY` + `OPENROUTER_API_KEY`); Reddit/RSS keyless.

**Step 2 (~15 min): wake the pass observe-only.** Add one `_run(["cosmu.ingest.voices_pass"])` line to
the 4-hourly `tick` in `apps/engine/remote/app.py` (Modal Free's 5-schedule cap is full — it must
**ride** `tick`, not get a 6th slot), then `modal deploy` (manual snapshot). The pass is idempotent,
deduped, capped — safe on any cadence. Optionally add `_run(["cosmu.indexes.run"])` too, after defining
a social index over the same handles via `POST /indexes`.

**Step 3 (~15 min, pure upside, $0): wire the event timeline into `compute_authority`.** The pass calls
it with `events` unset → every claim's lead-lag is `"none"` (mild 0.75 discount), so the
foresight-vs-echo separation proven in the dry-run is **latent in production**. Pass the `market_events`
rows (or GDELT prints) as `Event`s so primacy/lead-lag activates. Deterministic.

**Step 4 (the loop-closure, the one real code gap): let a strategy READ the authority signal.**
- *Quant path:* merge `store_provider_with_indexes` / the `social_authority` route into the
  gate/backtest construction sites so a `StrategySpec` keying off `authority_weighted_claim_signal` or
  `idx_<id>` is read end-to-end. (Routing exists; it just isn't the default provider yet.)
- *LLM path:* add **one analyst** to the Mind panel in `analysts.py` that reads
  `authority_weighted_claim_signal` for the symbol (it currently reads LunarCrush + news_sentiment but
  **not** the authority feature) — closing "credible voices turning bullish → the agent sees it".

**Outcome of the leap:** a slow-accruing, look-ahead-clean **source scoreboard** (`/mind/credibility`,
already built) + the two PIT features + index series, all feeding the Gate as ordinary OOS features and
the agentic-lane Gate-B evidence bundle. **Expect the first honest verdict to be "0/N voices carry skill
after costs"** — that is the machine working, the same honest answer the rest of the edge hunt produces.
The payoff is the substrate, not overnight alpha. Frame it as **building Gate B's substrate**.

---

## 5. Structural flaws & leakage — is the PIT honest? CONFIRMED CLEAN.

The #1 risk the brief flags — *scoring a call using its later outcome = look-ahead* — is **correctly
defended**, and I verified it at the code level:

- **`compute_authority(as_of=t)`** filters to `c.ts <= as_of` / `p.ts <= as_of` / `e.ts <= as_of`, and
  resolves outcomes with **`now = as_of`**. A claim whose exit bar lands after `as_of` is **PENDING**,
  never resolved into the future (`outcomes.py::resolve_claim`: `if exit_b is None or exit_b.ts > now`).
- **`signal_history`** recomputes the snapshot at each step `t` and stamps `available_at == t` — a
  real-time credibility judgement is knowable only when made; **no backdated availability**. This is the
  exact discipline the realtime-data-lane epic mandates (scraped archives feed event studies, never
  backdated trading features).
- The claim timestamp is **stamped from the post** (`ts == available_at`), **never** model-proposed
  (`claims.py::_claim_from_proposal`) — a claim can never read the future.
- The scoreboard upsert writes the **current** snapshot's skill as a *display* row; the **feature**
  series is the append-only PIT history, so a "live" feature read at time `t` never sees skill computed
  from `>t` outcomes.
- **Tested:** `test_history_is_point_in_time_no_lookahead`, `test_entry_is_point_in_time_last_bar...`,
  `test_profile_source_go_on_backfilled_pit_history` — all green (28 lane tests pass this session).
- **Disconfirmer in place:** the lead-lag time-reversal symmetry test (the astro lesson) kills a pure
  echo (dry-run: follower fwd-skill 0.000 / bwd-skill 0.694 → asymmetry −0.694). This is the standing
  tripwire on `authority_weighted_claim_signal` before it earns Gate trust.

**Minor flaws (not leakage):**
1. **Single-voice saturation** — with one high-authority voice the per-entity signal saturates to ±1
   (dry-run §4 artifact). A real multi-voice panel produces a graded signal; not a bug, but the panel
   should have ≥several voices per entity for the signal to be informative.
2. **Text indexes are sentiment-judged, not price-anchored** — `event_topic`/`prompt_rubric` indexes use
   an LLM-as-judge rubric, which is a weaker quantification than the price-anchored claim path. If the
   operator wants *every* index grounded on price-impact, the social path is the model to extend.
3. **Gate B forensics scorer is unbuilt** (§2) — the design exists; the authority lane is its hardest
   input and is ready.
4. **LLM-spend cap unwired** for the agent loop (§2) — cap before scaling the fleet.

---

## 6. Bottom line

- **~85% of the operator's authority-index vision is already built, tested, and look-ahead-clean.** The
  socle (gather → LLM-format → monitor → authority-index → strategy-readable feature) exists as
  `cosmu/mind/` + `cosmu/indexes/` + `cosmu/strategy/agent_*` + the feature registry + the API + the web
  Indexes page.
- **"Authority from price-anchored call accuracy" is exactly his idea**, implemented *better* than
  "9/10 right" (Brier-skill-vs-base-rate, sample-shrunk, calibration-tracked, echo-disconfirmed), and
  **proven on real data** (skill 0.701 vs 0.000 vs 0.000).
- **The leap is ~1–2 hours, observe-only, $0-marginal:** register a voice panel → ride `voices_pass` on
  `tick` → wire the event timeline → add one analyst / merge the index route so a strategy reads the
  signal.
- **The PIT is honest. The leakage risk the brief worried about is correctly defended and tested.**

### Cited files
- Mind / authority: `apps/engine/cosmu/mind/{claims,outcomes,authority,analysts,debate,judge,rubric}.py`
- Ingestion: `apps/engine/cosmu/ingest/voices_pass.py`, `apps/engine/cosmu/data/sources/voices.py`
- Panel config: `apps/engine/cosmu/config/voices.py` (`VOICE_PANEL = ()`)
- LLM strategy lane: `apps/engine/cosmu/strategy/{agent_spec,agent_loop,agent_decision,agent_executor,agent_author,agent_run}.py`
- Indexes: `apps/engine/cosmu/indexes/{spec,registry,compute,monitor,run,routing}.py`
- Features: `apps/engine/cosmu/config/feature_registry.py:264-291` (the two authority features)
- Cron fleet: `apps/engine/remote/app.py` (tick:201 has `agent_run`; `voices_pass`/`indexes.run` absent)
- Migrations: `apps/engine/cosmu/knowledge/migrations/2026-06-15_indexes.sql`; tables in `schema.sql`
- API: `apps/engine/cosmu/api/routers/{mind,indexes}.py`; web: `apps/web/app/indexes/`
- Epics: `docs/epics/{agentic-lane,indexes,realtime-data-lane}.md`
- Proof: `docs/reports/credibility-dryrun-2026-06-25.md`, `docs/reports/credibility-pipeline-scout-2026-06-25.md`
