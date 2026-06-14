---
name: backfill-summaries
description: Write/refresh the per-strategy PLAIN-LANGUAGE summaries (research_notes kind='summary') from each Version's deterministic facts — Claude Code writes them on the flat sub, the engine only stores/serves. Use when strategies are missing a summary or show the "stale" badge. Advisory text only; never the gate, never moves money.
---

# backfill-summaries

The strategy sheet shows a **fixed two-part summary**: **Part 1 — "What this does"** (the agent prose you write here) and **Part 2 — "Why it's <Stage>"** (rendered DETERMINISTICALLY by the web from the live Gate facts — `components/strategy/ai-summary.tsx:stageReason`; you do NOT write it, so it's always current and can't go stale or be duplicated). Your job is Part 1: a 2–4 sentence plain-language read a non-quant gets — **what it trades, the hypothesis/mechanism, and (if a track exists) where its forward test stands.** Do NOT re-explain the lifecycle stage or the gate verdict in prose — Part 2 owns that. **The deployed engine never generates this text** — it has no LLM in this path. *You* (Claude Code, flat-rate sub) write the prose from the engine's **deterministic facts**, then PUT it back. The engine stores it as a `research_notes` row (`kind='summary'`, latest wins), serves it on the strategy detail contract, and the web renders it as Part 1 with an honest staleness badge.

**This is the canonical RECURRING refresh task** — run it on every regular checkup (and whenever the sheet shows a "stale — facts changed" pill): rewrite Part-1 summaries that are missing OR stale, so the plain-language read stays true as forward tests progress and strategies move through the lifecycle.

**Advisory only.** Summaries narrate; the deterministic Gate alone funds or kills. Nothing here touches the gate/money path.

## The contract (engine API)

| Call | Returns |
|------|---------|
| `GET /strategies/{version_id}/summary-facts` | `{facts: {...}, facts_hash}` — the ONLY facts you may write from + the staleness pin (404 = unknown version) |
| `PUT /strategies/{version_id}/summary` | body `{body_md, facts_hash, model, prompt_version}` → `{ok: true}` |
| `GET /strategies/{version_id}` | detail now carries `summary_md`, `summary_stale`, `summary_updated_at` (nulls = no summary yet) |

**Auth — the engine's global shared-secret gate** (middleware in `apps/engine/cosmu/api/app.py`, the docs/KEYS.md contract): when `API_SECRET_KEY` is set on the engine (production), **every route except `/health` — the GETs above included — requires a matching `x-api-key` header**; a missing/wrong header is a 401. Unset (local dev) → all routes are open. There is no per-route auth; this one middleware is the whole mechanism, the same gate the Next.js proxy satisfies by injecting the header server-side.

A stored summary is **STALE** when its pinned `facts_hash` no longer equals the current one (a metric moved, the track re-marked, the status changed). Stale ⇒ rewrite.

## Setup

```bash
export API_BASE_URL=https://cosmu.up.railway.app   # or http://localhost:8000 for a local engine
export API_SECRET_KEY=...                          # from .env.local / Railway env — required on EVERY call (except /health) when set on the engine
AUTH=(-H "x-api-key: $API_SECRET_KEY")             # attach to every curl below; harmless when the engine runs open
```

## 1 — Find versions missing or stale summaries

Via the API (works against the deployed engine):

```bash
# Candidate version ids: leaderboard (top Versions) + population graveyard (killed Versions).
curl -s "${AUTH[@]}" $API_BASE_URL/leaderboard | python3 -c "import json,sys; [print(r['version_id']) for r in json.load(sys.stdin)['rows']]"
curl -s "${AUTH[@]}" $API_BASE_URL/population  | python3 -c "import json,sys; [print(g['version_id']) for g in json.load(sys.stdin)['graveyard']]"

# For each id: missing (summary_md null) or stale (summary_stale true) ⇒ needs writing.
curl -s "${AUTH[@]}" $API_BASE_URL/strategies/$VID | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary_md'] is None, d['summary_stale'])"
```

Or by SQL for an exhaustive sweep (local sqlite Store, or the Supabase SQL editor / MCP against prod Postgres) — versions with no summary row at all:

```sql
SELECT sv.id FROM strategy_versions sv
LEFT JOIN research_notes rn ON rn.strategy_version_id = sv.id AND rn.kind = 'summary'
WHERE rn.id IS NULL;
```

(Staleness still comes from comparing the per-version `GET …/summary-facts` hash with the stored `structured->>'facts_hash'`.)

## 2 — Get the facts (and the pin)

```bash
curl -s "${AUTH[@]}" $API_BASE_URL/strategies/$VID/summary-facts
```

`facts` contains exactly: `name`, `thesis`, `rationale`, `lane`, `bar_size`, `asset_classes`, `status`, `kill_reason`, `screen` (`oos_return`, `deflated_sharpe`, `max_dd`, `num_trades`, `passed_gates`, `holdout_passed` — or null if never screened), `forward_test` (`return_pct`, `equity`, `starting_capital`, `updated_at` — or null if no track). Keep the returned `facts_hash` — you pin the summary to it.

## 3 — Write Part 1 · "What this does" (2–4 sentences, noob-readable, FACTS ONLY)

Cover Part 1, in plain words (**Part 2 — "Why it's <Stage>" — is the UI's deterministic job**; do NOT write the lifecycle/gate-verdict reasoning in prose, it duplicates Part 2 and can drift):
1. **What it trades** — asset classes + bar size (e.g. "a crypto strategy on 4-hour bars").
2. **The hypothesis / mechanism** — restate `thesis`/`rationale` simply; no jargon. This is the heart of Part 1.
3. **(optional) the headline result, ONE line** — you MAY note the bare outcome ("it cleared the Gate" / "the Gate killed it"), but leave the WHY to Part 2. The plain-words vocabulary below is reference for that one line:

| code | plain words |
|------|-------------|
| `deflated_sharpe` | after correcting for how many ideas were tried, the returns look like luck, not skill |
| `cscv_pbo` / `pbo` | high probability the backtest is overfit — it memorized the past instead of finding a rule |
| `fdr` | killed by the cohort-wide false-discovery control — when many ideas are tested at once, a few look good by pure chance; this one didn't clear that bar |
| `buy_and_hold` / `not_beating_buy_and_hold` | all that trading didn't beat simply buying and holding the asset |
| `min_trades` / `min_trades_per_symbol` | too few trades to judge — the result could easily be noise |
| `max_drawdown` | its worst losing stretch was too deep to be fundable |
| `regimes` | it only worked in one kind of market, not across calm/volatile/trending conditions |
| `holdout` | it failed the one-shot test on data it had never seen |
| `folds_positive` | it lost money in too many of the walk-forward test windows |
| `screened_out` | it never produced a screenable result (e.g. zero trades) |

4. **Forward-test state, if a track exists** — e.g. "On its own simulated $1,000 paper track it is up 1.5% (last marked <date>)." (Each track funds itself with `starting_capital` — default $1,000, NOT a pooled wallet; use the real `forward_test.starting_capital` from the facts.)

**Hard rules:**
- **Never invent a number that is not in `facts`.** No extrapolation, no "roughly", no annualizing.
- **Mark uncertainty honestly** — `screen: null` ⇒ "it hasn't been screened yet"; `forward_test: null` ⇒ "it has no forward-test track"; few trades ⇒ say the evidence is thin.
- Advisory voice: the summary explains; the Gate decides. Never imply a recommendation to fund or launch.
- Markdown is fine but keep it prose — the UI renders preserved-linebreak text.

## 4 — PUT it back (pinned to the hash from step 2)

```bash
curl -s -X PUT "$API_BASE_URL/strategies/$VID/summary" \
  -H "content-type: application/json" "${AUTH[@]}" \
  -d '{"body_md": "…the 3–6 sentences…", "facts_hash": "<facts_hash from step 2>", "model": "<the model id you are running as>", "prompt_version": "v1"}'
```

If much time passed between GET and PUT (e.g. a 4h tick re-marked tracks), re-GET the facts first so you don't pin an already-stale hash. The newest row wins, so re-running this skill is safe. A 401 anywhere means `API_SECRET_KEY` is set on the engine and your `x-api-key` header is missing or wrong.

## 5 — Verify

```bash
curl -s "${AUTH[@]}" $API_BASE_URL/strategies/$VID | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary_stale'], (d['summary_md'] or '')[:80])"
```

`summary_stale` must be `false` right after a write. The strategy page now shows the Summary card ("written by the operator's agent · advisory, not the gate") instead of "No summary yet".

## Invariants
- Engine = storage/serving only; the summary text is **always** written externally (this skill). No LLM in the deployed path.
- Facts-only prose; the `facts_hash` pin keeps honesty mechanical — when numbers move, the UI says "stale", never silently lies.
- Offline-testable plumbing: `cd apps/engine && PYTHONPATH=. python3 -m pytest tests/test_strategy_summary.py -q`
