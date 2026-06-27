# Epic — The LLM voices / authority lane TEMPLATE (the extend-me scaffold)

> Status: **TEMPLATE, ready to extend.** A clean, minimal, mockable scaffold for the "PageRank for
> credibility" lane. Runs at ~$0, observe-only. This doc is the **CONTRACT**: what is LOCKED (ratcheted
> validated decisions) vs FLEXIBLE (what the next chat changes). Supersedes PR #426 (which shipped an
> 11-voice, mostly-X panel and no mock-default mode).
>
> **Gate A (the deterministic FDR gate) is LOCKED and untouched by everything here.** This lane PROPOSES
> + SCORES a credibility scoreboard; the Gate alone funds.

---

## 1. The one-paragraph vision

Follow a small, pre-registered panel of public voices (X / Reddit / RSS), turn each predictive post into a
typed `Claim {entity, direction, horizon, conviction, ts}`, resolve those claims against real price bars,
and rank each voice by **price-anchored skill** (Brier-skill vs the base rate), **primacy** (who said it
first), and **lead-lag** (did the call LEAD a news event or merely ECHO it). The output is a
`voice_scoreboard` (one flat, human-readable row per voice) plus two point-in-time alt-data features
(`author_authority`, `authority_weighted_claim_signal`) that an observe-only Mind analyst reads. The LLM is
used ONLY to extract STRUCTURE from text; it never scores, never ranks, never moves money.

## 2. The pipeline (already built on `main`)

| Phase | Module | What it does | LLM? |
|------:|--------|--------------|:----:|
| 0 | `data/sources/voices.py` | Pull a voice's timeline (Reddit JSON / RSS / xAI for X) as raw PIT posts | X only |
| 1 | `mind/claims.py` | Extract typed `Claim`s from each post (instructor-style, Pydantic `extra="forbid"`) | **yes** |
| 2 | `mind/outcomes.py` | Resolve each claim against bars → per-author track record (Brier-skill vs base rate) | no |
| 3 | `mind/authority.py` | Primacy + lead-lag + skill-anchored personalized PageRank → fused authority | no |
| pass | `ingest/voices_pass.py` | One bounded tick: Phase 0→3, writes scoreboard + the 2 PIT features | — |
| **template** | **`ingest/voices_template.py`** | **mock-default / live-cheap runner — the thing the cron calls** | — |
| readout | `api/routers/mind.py::/mind/credibility` | sorted, human-readable scoreboard (skill DESC, NULLs last) | no |
| mind | `mind/analysts.py::authority_analyst` | observe-only pillar reads `authority_weighted_claim_signal` | no |

## 3. LOCKED — the ratcheted decisions (do NOT re-litigate; extend around them)

1. **Extraction = an OpenRouter `:free` model.** `config/voices.py::OPENROUTER_FREE_MODEL`
   (`meta-llama/llama-3.3-70b-instruct:free`). `:free` variants do NOT draw down the OpenRouter credit, so
   the lane is **~$0**. `build_claim_extractor_from_settings` defaults to this model on the OpenRouter seam;
   xAI/Grok is only an optional override. *Swappable: change the one constant.*
2. **Retrieval = keyless first.** Reddit public JSON + RSS need no key. X (xAI LiveSearch) is optional and
   gated on `XAI_API_KEY`. **Never the direct X API.** The starter panel is keyless-only.
3. **MOCK is the default; live-cheap is a flag.** `VOICES_LIVE_ENABLED` (env). Unset/`0` → mock mode:
   canned posts → a deterministic in-process extractor → fake bars → **no network, no LLM, $0**. `1` →
   live-cheap: keyless retrieval + the `:free` extractor (still ~$0). So a cron tick / CI run can never
   spend or block.
4. **Observe-only / zero-capital.** The lane PROPOSES + SCORES. It opens **no track / position / order**.
   The deterministic Gate alone funds. The scoreboard is the read-out; the operator decides.
5. **Leakage-safe standing tripwires.** Two disconfirmers stay GREEN in CI
   (`tests/test_authority_disconfirmers.py`): the **sniper-vs-spammer** skill test (skill is excess over the
   base rate, not volume) and the **lead-lag time-reversal** symmetry test (a real foresight call is
   asymmetric under event-timeline reversal; a pure echo flips). These are the astro-lesson guards.

## 4. FLEXIBLE — what the next chat changes

- **The panel** (`config/voices.py::VOICE_PANEL`) — operator-edited; add/remove a line and the next pass
  picks it up. Currently a **minimal 2 voices** (one keyless Reddit breadth control + one keyless RSS
  on-chain desk). Pre-registration discipline: add a voice with a falsifiable `why` BEFORE its calls are
  scored.
- **The model id** (`OPENROUTER_FREE_MODEL`) — swap to any `:free` variant.
- **The source mix** — add X (set `XAI_API_KEY`), more subreddits, more feeds.
- **The frequency** — the pass is dedup-safe and idempotent; run it on any cadence.
- **The entity routing** (`ENTITY_BARS_SYMBOL`) — extend as the panel widens to new assets.

## 5. The 2-voice starter panel (current)

| handle | platform | hypothesis (`why`) |
|--------|----------|--------------------|
| `r/CryptoCurrency` | reddit (keyless) | broad retail sentiment — breadth NOT skill; the base-rate CONTROL that proves the scoreboard rewards skill, not loudness |
| `https://insights.glassnode.com/feed/` | rss (keyless) | Glassnode Week-On-Chain — original, slow, data-driven BTC/ETH reads; a low-frequency causal candidate the lead-lag tripwire will confirm or refute |

Expected honest first verdict: **0/2 carry skill after the base rate.** That is the machine working.

## 6. Mock mode — how it works (the $0 default)

`run_mock_pass(store)` assembles a tiny self-contained world and runs the REAL `run_voices_pass`:

- **`mock_providers()`** — `FixtureVoiceProvider` with canned timelines for two archetype handles
  (`@mock_sniper` = a couple of early correct BTC calls; `@mock_spammer` = many loud ones). No network.
- **`MockChat`** — an in-process callable that turns any BTC-mentioning post into one typed `up` claim, `[]`
  otherwise, and counts calls (so a test proves re-runs don't re-extract → $0). No HTTP, no key.
- **`MockRisingBars`** — ascending daily closes so `up` claims resolve as hits. No network.

The pass then runs Phase 0→3 deterministically and lands the durable `voice_scoreboard` + the 2 PIT
features — a faithful end-to-end exercise of the whole lane with zero spend. This is the CI default and the
safe cron path.

## 7. How to extend it (next chat)

1. **Add a voice:** append a `Voice(...)` to `VOICE_PANEL` with a one-line falsifiable `why`. Keep it
   keyless (reddit/rss) unless you intend to set `XAI_API_KEY`. Map any new entity in `ENTITY_BARS_SYMBOL`.
2. **Go live-cheap locally:** `VOICES_LIVE_ENABLED=1 python3 -m cosmu.ingest.voices_template`. With the
   OpenRouter key set it uses the `:free` model. (Free-tier models are best-effort: a 429 / no-key just
   degrades to the deterministic path — the lane never crashes.)
3. **Read the board:** `GET /mind/credibility` (sorted skill DESC, NULLs = untested last) or the
   `voice_scoreboard` table directly.
4. **Swap the model:** edit `OPENROUTER_FREE_MODEL`.
5. **Keep the tripwires green:** `pytest -k "voice or authority or claim or credibility"`.

## 8. Cost note (verified 2026-06-26)

Mock mode = **$0** (no network, no LLM). Live-cheap = **~$0** (`:free` variants don't draw the credit). A
real `:free` extraction smoke test on this date returned $0 (the account's $5 OpenRouter credit was already
spent on prior paid usage, so the `:free` models 429'd before any inference — the seam degraded honestly,
usage unchanged). The lane's correctness does NOT depend on free-tier availability: mock mode carries CI and
the cron at $0 regardless.
