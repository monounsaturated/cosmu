# xAI/Grok silent spend fix — reserve xAI for on-demand only

**Date:** 2026-06-29
**Trigger:** Operator noticed xAI (Grok) spending ~$0.20/day for the last few days, with only ~$0.18 of credit
left. Goal: stop the daily spend, preserve the remaining credit for **on-demand** tweet ingestion.

---

## What was spending the ~$0.20/day

Nothing in the code changed recently — the spend began when **`XAI_API_KEY` was added to the Modal `cosmu-engine`
secret**. That single env var silently activated four key-gated paths inside the *scheduled* crons. The root cause
is a routing default: **whenever `xai_api_key` is set, xAI became the default provider for all automatic LLM work**
(`Settings.llm_provider` returned `"xai"`), and two ingest sources were wired with the key directly.

The four scheduled vectors (all on the Modal fleet, all keyed off `XAI_API_KEY` being present):

| # | Cron | Path | xAI call | Cost driver |
|---|------|------|----------|-------------|
| 1 | `ingest` (hourly, `0 * * * *`) | `Providers.from_settings` → `XaiTwitterProvider` `twitter_sentiment` | **LiveSearch** (`_fetch_tweets`) + `grok-3-mini` scoring — **2 calls/pull** | LiveSearch is billed **per source** — the expensive one |
| 2 | `ingest` (hourly) | `build_index_provider_from_settings` → `LlmIndexProvider` | `grok-3-mini` rubric scoring, **2 rubrics** (`reg_risk_crypto`, `risk_on_off`) | cheap text scoring |
| 3 | `tick` (every 4h, `0 */4 * * *`) | `lab/author.py` → `route_and_propose(provider="xai")` | `grok-2-latest`, N candidates/tick | structured authoring |
| 4 | `tick` (every 4h) | `lab/research.py` `gather_context` → `xai_live` | **LiveSearch** real-time X/web | LiveSearch billed per source |

A throttle (`llm_source_min_interval_minutes = 60`) caps the ingest sources at ~once/hour, but with an **hourly**
cron that still means ~24 pulls/day each. The two **LiveSearch** paths (#1, #4) are the dominant cost — xAI bills
LiveSearch per source returned, so a handful of hourly/4-hourly searches plausibly sums to the observed ~$0.20/day.

## Why it was happening

`Settings.llm_provider` preferred xAI as soon as `XAI_API_KEY` existed ("already on Railway, most efficient"), and
`build_index_provider_from_settings` / `Providers.from_settings` / `research.py` each wired the key directly. So
merely *holding* the key turned the unattended fleet into a steady xAI spender — exactly the opposite of the
operator's intent (xAI for **on-demand** tweet ingestion, lean).

## What changed

One central, opt-in toggle — **`XAI_SCHEDULED_ENABLED` (default `False`)** — now gates xAI for all
scheduled/unattended work. When off (the default), the crons route to **OpenRouter `:free`** ($0) or degrade
honestly; xAI is reserved for on-demand use. Additive and reversible (set `XAI_SCHEDULED_ENABLED=1` to restore the
old behavior).

| File | Change |
|------|--------|
| `cosmu/config/settings.py` | New field `xai_scheduled_enabled: bool = False`. `llm_provider` returns `"xai"` **only when opted in**, else OpenRouter, else None. `llm_api_key` now returns the key that *matches* the provider (no xai-key + OpenRouter-url mismatch). → fixes **#3** (author) and the (off-by-default) mind judge. |
| `cosmu/ingest/run.py` | `Providers.from_settings` wires `XaiTwitterProvider` with the key **only when opted in**; otherwise keyless → `[]` ($0). → fixes **#1**. |
| `cosmu/lab/indexes.py` | OpenRouter default model switched from paid `openai/gpt-4o-mini` to the canonical **`OPENROUTER_FREE_MODEL`** (`meta-llama/llama-3.3-70b-instruct:free`). `build_index_provider_from_settings` now prefers OpenRouter `:free`; xAI only when opted in. → fixes **#2** (now runs free). |
| `cosmu/lab/research.py` | The scheduled research bus passes the xAI key for `xai_live` **only when opted in**; else fixture ($0). → fixes **#4**. |
| `tests/test_xai_scheduled_gate.py` (new) | Pins the routing: default → OpenRouter / None; opt-in → xAI; `from_settings` leaves the tweet provider keyless by default. |
| `tests/test_indexes.py` | Updated `test_build_from_settings_is_key_gated` for the on-demand-by-default behavior + free/xAI model-id assertions. |

On-demand xAI is untouched: `scripts/backfill_voices.py` and `XaiVoiceProvider`/`XaiTwitterProvider` read/take
`XAI_API_KEY` directly, so manual tweet ingestion still works on the remaining credit. The mind `claims.py`
extractor already preferred OpenRouter `:free` (the pattern this fix mirrors); the mind judge is opt-in (off).

## Expected new cost

**Scheduled xAI spend → $0.** The four cron vectors now run on OpenRouter `:free` (#2, #3) or degrade to keyless
`[]`/fixtures (#1, #4). The ~$0.18 xAI credit is preserved for on-demand tweet ingestion. No change to any
deterministic Gate / money path — the LLM here only standardizes/scores text, never funds.

## Deploy note

This is a code change; the env var `XAI_SCHEDULED_ENABLED` defaults to off, so **no secret edit is required** to
stop the spend. The fix only takes effect on the live fleet after the Modal app is redeployed (`modal deploy`) —
the cron fleet does **not** auto-deploy on merge.

## Tests

`pytest tests/test_xai_scheduled_gate.py tests/test_indexes.py tests/test_llm_author.py tests/test_lane_router.py
tests/test_compute_spend_failover.py tests/test_ingest_llm_throttle.py tests/test_mind_judges.py` → all green
(191 passed across the routing/author/ingest/index suites).
