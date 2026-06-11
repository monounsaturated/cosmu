# Task: wake the credibility pipeline (realtime-data-lane epic P2)

> Launch: cloud session, sonnet, own branch. Read `AGENTS.md` then `docs/epics/realtime-data-lane.md`
> (§4.2, §10 P2) first. Everything below already EXISTS and is tested — this task is WIRING, not building.

## Context
"PageRank for credibility" Phases 0–3 are dormant modules: `data/sources/voices.py` (Phase 0 — raw voice
timelines: X via Grok LiveSearch / Reddit / RSS, PIT-stamped) → `mind/claims.py` (Phase 1 — LLM claim
extraction, typed+validated) → `mind/outcomes.py` (Phase 2 — deterministic resolution, Brier skill vs base
rate, sample-shrunk) → `mind/authority.py` (Phase 3 — primacy + lead-lag vs an event timeline +
skill-anchored PageRank). Registered features: `author_authority`, `authority_weighted_claim_signal`
(config/feature_registry.py). The NEW `market_events` store (data/events_store.py) is the event timeline
Phase 3 wants.

## Deliverables
1. **Handle list, pre-registered:** a typed config (e.g. `cosmu/config/voices.py`) with the initial voice
   panel (handle, platform, why-this-voice one-liner). Operator fills the real list; ship with a small
   commented example. SURVIVORSHIP RULE (epic §0.2): complete timelines of pre-registered handles only —
   never add a handle because a tweet went viral after the fact.
2. **Ingest wiring:** a bounded cron entrypoint (`python3 -m cosmu.ingest.voices_pass` or folded into
   `ingest/run.py` providers) that: pulls each handle's recent posts (Phase 0, key-gated, honest [] without
   keys) → stores raw posts as `market_events` rows (provider="voices", source=handle, available_at =
   receipt time) → runs Phase 1 claims (key-gated) → persists claims durably (decide: a `voice_claims`
   table mirroring the dataclass, or structured rows in market_events — justify the choice) → Phase 2/3
   recompute on the stored corpus and write `author_authority` / `authority_weighted_claim_signal` into
   `alt_data` as ordinary PIT features (available_at = computation time).
3. **Cron:** add to `apps/engine/railway.toml` (hourly is fine; it is poll-based until the P3 worker).
4. **Web source scoreboard:** a page/section reading per-source walk-forward skill (Brier skill, hit-rate
   excess, n, shrinkage state, authority) with honest empty states. Follow the existing premium design
   system; generated contracts only.
5. **Tests:** offline (inject fetchers/chat seams per the existing patterns in tests/test_voices.py,
   test_claim_extraction.py, test_outcome_resolution.py, test_social_authority.py).

## Invariants (do not violate)
- LLM extracts structure ONLY (claims); resolution/scoring/authority stay deterministic.
- `available_at` = receipt time, never the post's own time, for anything that becomes a trading feature.
- A keyless run degrades honestly everywhere ([] / empty panel / no badge — never fabricated).
- `pnpm verify` before push; feature branch + PR; never push to main.
