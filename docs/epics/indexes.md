# Epic: Indexes — operator-defined, standardized, deterministically-scored signal series

> Shipped 2026-06-15. The operator asked for a first-class **Indexes** surface ("another page, like the strategy
> page, with its own table — shows all the created indexes"). An index can be an event topic (e.g. Middle East
> news), anything written as a **prompt rubric**, a **single social account**, or a **bucket of accounts** fused
> by skill. Indexes must be **standardized, constantly monitored, NOT hallucinated, and ranked the same way every
> time** — because strategies are built on top of them next.

## The one-line model
An **index** is a named **point-in-time numeric series** stored in `alt_data` (`provider='index'`,
`metric=idx_<id>`), scored the **same way every pass** (frozen transform) from one of four source kinds, monitored
for freshness + ranking stability, and registered so a StrategySpec can key off it later.

## Why it's not duplicate, and why it's not hallucinated
- **Reuses the canonical scorers — no second scoring path.** Text indexes (`event_topic`/`prompt_rubric`)
  delegate to `cosmu/lab/indexes.py` (the existing LLM-as-judge: rubric-anchored, CoT-then-JSON, Pydantic
  `extra="forbid"`, range-checked, retry-on-invalid, hallucinated-evidence-id dropped). Social indexes
  (`single_account`/`social_bucket`) delegate to `cosmu/mind/authority.py` (the deterministic Brier-skill +
  primacy + PageRank authority-weighted claim signal). `cosmu/indexes/` is the **operator registry + monitor +
  surface** layered on top.
- **Stable ranking = determinism.** The LLM runs at temperature 0, behind a **content-hash cache** + a **frozen
  `transform_version`**, validated to a typed schema; the same input always yields the same number. The LLM
  **only standardizes/judges text at compute time** — it is never on the gate/scoring/money path.
- **Honest.** No key / no network / no claims → the source contributes **nothing** (never a fabricated value).
  A never-computed index reads `never`/`—`, not 0.

## Architecture (engine)
| Piece | File | Role |
|---|---|---|
| Spec | `cosmu/indexes/spec.py` | typed `IndexSpec` (4 kinds, per-kind validation, slug, `metric`, market-wide) |
| Registry | `cosmu/indexes/registry.py` | define/list/get on the additive `indexes` table; fail-open `indexes_available` |
| Compute | `cosmu/indexes/compute.py` | one PIT point/pass, delegating to lab.indexes (text) + mind.authority (social) |
| Monitor | `cosmu/indexes/monitor.py` | deterministic freshness + ranking-stability + reliability label |
| Routing | `cosmu/indexes/routing.py` | `index_routes(store)` → makes `idx_<id>` a strategy-readable feature (the "strategies on top" seam) |
| Run | `cosmu/indexes/run.py` | the cron/Modal refresh pass (`python3 -m cosmu.indexes.run`) |
| API | `cosmu/api/routers/indexes.py` | `GET /indexes`, `GET /indexes/{id}`, `POST /indexes` |

## Architecture (web)
- New nav surface **Indexes** (`/indexes`) — a table of every index with current value + freshness + reliability
  + how many strategies use it, and a **Define index** form (POSTs an `IndexSpec`).
- **Index detail** (`/indexes/[id]`) — definition (topic/prompt/handles), health, the scored series chart per
  symbol, and the strategies built on it.

## Operator actions to make it live
1. **Apply the migration** `apps/engine/cosmu/knowledge/migrations/2026-06-15_indexes.sql` in the Supabase SQL
   editor. Until then `GET /indexes` returns `available:false` and the page shows the honest "registry not
   active" state (dev/test auto-create the table from `schema.sql`).
2. **Define indexes** in the app (or `POST /indexes`). Keep the panel pre-registered/honest: write the rationale
   at create time (anti-slop), before any outcome is known.
3. **Run the compute pass on Modal / a Railway cron** (HEAVY — scraping + LLM; needs `XAI_API_KEY` /
   `OPENROUTER_API_KEY` for text-index judging and the voices pass for social claims):
   - Modal: `modal run apps/engine/remote/app.py --job run_module --module cosmu.indexes.run` (add the job if
     not present), or a Railway `[[cron]]` running `python3 -m cosmu.indexes.run`.
   - Social indexes consume the **voices pass** output (`voice_claims`) — register the handles in
     `config/voices.py` so the timeline pull + claim extraction feed them.

## Next (follow-ups, not in this PR)
- **Wire `store_provider_with_indexes` into the gate/backtest construction sites** so a StrategySpec can key off
  an index feature end-to-end (the "build strategies on top of indexes" step the operator flagged as *next*).
- A rubric-LLM **bespoke scorer per prompt_rubric** is already wired (the rubric becomes the judge's question);
  consider per-index `news_symbols`/evidence tuning.
- Add a `cosmu.indexes.run` Modal job entry in `apps/engine/remote/app.py` + a Railway cron cadence.
