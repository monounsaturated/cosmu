# Voice-authority specs → Gate: first test of the credibility edge lane

Date: 2026-06-28
Branch: `claude/voice-event-specs-2026-06-28`
Status: autonomous-run POC — **DO NOT MERGE yet**

## Goal

COSMU's one structurally-defensible edge (roadmap #6) is **LLM-as-analyst credibility scoring** — the "voices"
lane: score sources on past-call accuracy, mint a point-in-time *authority* signal, and let strategies enter on
it. The feature `authority_weighted_claim_signal` is **registered**
(`apps/engine/cosmu/config/feature_registry.py:265`), but **zero strategy specs have ever entered on it**. So the
only non-price signal kind had never faced the Gate, and we did not know if the wire even worked end-to-end.

This POC authors typed StrategySpecs that enter on the authority feature and routes them through the EXACT
per-combo BRUT Gate the finder uses, to prove (or disprove) the wire — at $0.

## What was built

- `apps/engine/cosmu/research/voice_authority_poc.py` — 7 typed authority-entry specs + the injection/panel/Gate
  harness (pure, offline, deterministic). The Gate is **read-only / untouched**.
- `apps/engine/tests/test_voice_authority_poc.py` — 7 focused tests pinning the wire (all pass).

### The 7 specs (all `lane='explore'`, `strategy_kind='indicator'`)

Each entry is a single `Condition` on `authority_weighted_claim_signal` vs a fitted threshold (a `ParamRef` — no
magic numbers). `strategy_kind` is `indicator` (not `event`) because the authority signal is a **continuous PIT
alt-data series** read as a condition on the price path, not a discrete `MarketEvent` trigger.

| # | Name | op | dir | horizon |
|---|------|----|-----|---------|
| 1 | Voice authority long cross-up (1h)    | cross_up   | long  | 1h |
| 2 | Voice authority long level (1h)       | gt         | long  | 1h |
| 3 | Voice authority short cross-down (1h) | cross_down | short | 1h |
| 4 | Voice authority short level (1h)      | lt         | short | 1h |
| 5 | Voice authority long cross-up (4h)    | cross_up   | long  | 4h |
| 6 | Voice authority long mild level (1h)  | gt         | long  | 1h |
| 7 | Voice authority short cross-down (4h) | cross_down | short | 4h |

**All 7 pass the real `validate_spec`** (7/7 valid) — the feature is registered, no magic numbers, valid
horizon/universe. The authoring path for this signal kind is sound.

## Finding 1 — does REAL authority data exist? **NO. The lane is INERT.**

Queried the live production store (read-only, via the operator's `.env.local`):

- `alt_data` for `provider='social_authority'` (the metrics `authority_weighted_claim_signal` /
  `author_authority`): **ZERO rows.** The 1,093,219-row `alt_data` table spans 22 providers
  (binance, gdelt, lunarcrush, polymarket, …) — `social_authority` is **not among them**.
- `voice_claims`, `voice_scoreboard`, `market_events`: **these tables do not exist in prod** (the migrations were
  never applied — the voices pass has never run there).

The voices pass is **mock-default** (`VOICES_LIVE_ENABLED` unset) and its voice panel
(`apps/engine/cosmu/config/voices.py`) has never been activated in production. **There is no usable history** for
these features. Populating the voice panel (and running the pass on a cadence to accrue PIT history) is a
**prerequisite** before this edge can be tested on real data.

## Finding 2 — does the end-to-end pipeline work? **YES — proven end-to-end.**

Because real data is absent, the pipeline was driven with a **clearly-labelled SYNTHETIC** authority carrier
injected through the SAME `alt_by_symbol` PIT join the finder feeds funding/sentiment through. Three regimes were
run through `run_strategy_backtest_detailed` → `metrics_for_run` → `promote_brut` (the locked DSR/PBO/min-trades
BRUT Gate, `TrialStats(count=1)`, the same 30-trade floor the finder uses):

| regime | carrier | market | cells | trades | wire fired | **cleared** | median DSR | max DSR |
|--------|---------|--------|-------|--------|-----------|-------------|-----------|---------|
| `null`        | pure noise in [-1,1]            | permutation-null | 35 | 421 | yes | **0/35** | 0.259 | 0.868 |
| `leading`     | next-bar signed return + noise | permutation-null | 35 | 359 | yes | **0/35** | 0.528 | 0.951 |
| `strong_lead` | forward-hold look-ahead (labelled) | moderate-trend | 35 | 619 | yes | **5/35** | 0.310 | 0.996 |

The wire is fully functional at every stage:

1. **Specs ENTER on the authority feature** — `wire_fired=True` in all regimes (359–619 trades). The feature
   reaches the entry path; the join, the condition evaluation, and the position open all work.
2. **Backtest → metrics → Gate verdict** — every cell produces a real DSR/PBO/trade count and a promote/reject
   verdict.
3. **The Gate REJECTS pure noise** — `null` clears 0/35 (median DSR 0.259 ≪ 0.95 floor). No leak: a noise carrier
   cannot pass.
4. **The Gate reacts to signal CONTENT** — `leading` lifts the median DSR (0.259 → 0.528) but still clears 0/35
   (a one-bar lead does not survive a multi-day hold + fees — honest).
5. **A spec CAN reach a full Gate PASS** — under the labelled `strong_lead` look-ahead on a moderate-trend market,
   **5 cells clear the FULL Gate with empty reasons** (DSR 0.994–0.996, PBO 0.39–0.40 < 0.50, 31–32 trades ≥ 30,
   beats buy-and-hold). The verdict path is connected to PASS, not only to REJECT.

```
Voice authority long mild level (1h) | BTCUSDT dsr=0.996 pbo=0.40 trades=31 ret=+1.31 reasons=[]
Voice authority long mild level (1h) | ETHUSDT dsr=0.996 pbo=0.40 trades=31 ret=+1.31 reasons=[]
... (BNB, SOL identical; XRP dsr=0.994 pbo=0.39 trades=32) ...
```

> **The `strong_lead` survivors are PIPELINE-PROOF ONLY.** The carrier is an openly-injected look-ahead signal on a
> synthetic trending market. It demonstrates the *plumbing* is live. It is **NOT** a real edge and must never be
> read as one. Real authority data does not exist (Finding 1).

## Finding 3 — any real survivor? **NO — and that is the expected, correct result.**

There can be no real survivor because there is no real authority data. The value of this POC is not a survivor; it
is the verdict that **the wire is functional, not inert** — so the operator can decide whether populating the voice
panel is worth it next. It is.

## Verdict

- **Real authority data: does not exist** (lane inert — panel never populated, pass never run in prod, 0 store rows,
  voice tables absent).
- **Pipeline: works end-to-end** (spec → validate → backtest → metrics → BRUT Gate verdict; rejects noise, passes a
  genuine signal — all on the untouched locked Gate).
- **Survivor: none real** (expected; synthetic plumbing-pass cells are labelled PIPELINE-PROOF, not edge).

## Honest limitations

- The backtest ran on **synthetic bars** (keyless permutation-null + a moderate-trend demo fixture), not the
  operator's local Binance cache (M2 discipline: small N, no heavy compute, no network).
- The authority carrier is **synthetic**; the *real* `authority_weighted_claim_signal` would be far sparser and
  noisier than even the `null` regime — likely producing **fewer trades** and **no survivors** once populated.
- This proves the **wire**, not the **edge**. Whether credibility scoring carries a real, exploitable, after-fees
  edge is **untested** and can only be answered after the voice panel is populated and PIT history accrues.

## Recommended next step (for the operator)

Activate the voices lane to accrue real PIT history: register a small pre-registered voice panel
(`apps/engine/cosmu/config/voices.py` — keyless Reddit/RSS, ~$0), apply the voice-table migrations to prod, and run
`python3 -m cosmu.ingest.voices_pass` on a cadence so `social_authority` rows accumulate. Once a real series exists,
re-run this exact harness against it (swap the synthetic injector for the store's `AuthorityProvider` series) — the
spec→Gate path is already proven, so the only open question becomes the real one: is there an edge?
