# 🔭 ASTRO VERDICT v1 — the canonical, retrievable record

> **Name:** `ASTRO_VERDICT_v2` · **Date:** 2026-06-15 · **Status:** CLOSED (every channel, incl. belief) · **Verdict:** **NO EXPLOITABLE EDGE**
> **One line:** Across 18 experiments and 10 scientific dimensions on 32+ real assets over 2009–2026, astrology
> (and every live-honest alt-signal) carries **0 tradeable edges** after an honest gate. This is not a strictness
> artifact — it is a definitive, multiply-confirmed null. The machine works; there is nothing to find.

This document is the **standardized template** for future explorations. Retrieve it via the memory pointer
[[astro_markets_no_edge]], the Research Registry (`r2://cosmu-lake/research_registry/`), or
[`docs/research/RESEARCH_PREVIEW.md`](RESEARCH_PREVIEW.md) (auto-generated scoreboard of all experiments).

---

## 1. The verdict (decision-grade)
- **Pure astrology** (planets/aspects/lunar/eclipses/retrogrades/nodes/declination/natal): **dead** at every test.
- **Named financial-astro systems** (Bradley/Gann/Merriman): **dead** (Merriman +1pp hit-rate is near-saturation, not economic).
- **The one mechanism with a real prior** — astrology as a **belief/attention proxy** (self-fulfilling retail behavior): **untested at full depth** (the only ~10% residual; see §6 the future dive).
- **Live-honest alt-signals** (funding, fear&greed, VIX, geomag, xsec-momentum) tested as a control: **also 0 deflated edges.** funding-contrarian is *genuinely causal* (lead-lag asymmetric, unlike astro's symmetric artifact) but too weak standalone → a defensive overlay only.
- **The only real edge in the system** is the **equity TAA cohort (DAA/VAA/ADM)** — real prices, not astro — now deployed to paper.

## 2. How we did it (methodology — the honesty stack)
Every test applied, in order: **PIT** (trade t→t+1 on the value known at t; astro is deterministic-knowable-in-advance, so zero look-ahead) → **a PROPER null** (phase-shuffle / IAAFT / circular-shift that *preserves autocorrelation*, never iid fake-random — a weak null manufactured a false positive once) → **OOS holdout** → **BH-FDR + |t|>3** (multiple testing) → **Deflated Sharpe at the TRUE trial count** (Bailey–López de Prado) → **economic** (net of ~10bps, beat a *positive* benchmark). The single most diagnostic check: **train→OOS rank consistency** — astro's best-in-sample was its worst-out-of-sample (the fingerprint of noise).

## 3. The 10 dimensions tested (a top quant/physicist/astronomer's full battery)
| Dimension | Tool | Result |
|---|---|---|
| Single-signal IC | Spearman/Kruskal + BH-FDR | 0/4,092 survive |
| Deep + real baseline | pooled walk-forward AUC + incremental test (Modal) | 0/32,372; astro **degrades** the real model |
| 152k strategy lab | configs × assets × segments, Deflated Sharpe | raw best 1.85 → 0 survive |
| Composite + natal | train/test, group×regime×segment | train→OOS inverts |
| Event study | vol/turnover vs fake-date null | 3/76 (candidate) … |
| Lunar-vol vetting | **phase-shuffle null** | …→ p=0.33, **artifact** |
| Spectral / Lomb-Scargle | periodogram vs AR/IAAFT surrogates | trend artifact (synthetic control matched) |
| Info-theoretic | MI / transfer entropy | 0 survive BH/Bonferroni |
| Tail / extreme | within-year permutation | clustering dies |
| Named systems | Bradley/Gann/Merriman vs shifted-curve | near-saturation, not economic |
| Hierarchical-Bayes | DerSimonian-Laird pooling | z=6.6 but cross-correlation-inflated artifact |
| Physics features | solar inertial motion / angular momentum / declination | null |
| Geomagnetic (K-R) | post-storm returns vs proper nulls | −25bps right sign but p≈0.10 + decays |
| SAD / daylight | daylight-slope + HAC | FDR-fail |

## 4. The stack (what ran it)
- **Engine:** `apps/engine/` (Python). **Compute:** local M2 for light/daily; **Modal** (`cosmu-astro-research` app) for parallel permutation nulls (`scripts/research/astro_deep/modal_sweep.py`). **Storage:** Cloudflare **R2** (`cosmu-lake`) via a DuckDB-native R2 secret (`scripts/research/astro_strategy_lab/lab_store.py`).
- **Ephemeris:** deterministic, `ephem` + a closed-form fallback (`scripts/research/astro_deep/astro_features_deep.py` — 126 features; `cosmu/data/sources/astro_ephemeris.py`).
- **Data loaders:** `scripts/research/astro_deep/real_panel.py` (Binance klines + Yahoo + the PIT join onto prod `alt_data`).
- **Honest stats:** `cosmu/master/scorer.py` (Deflated Sharpe), `cosmu/master/cpcv.py` (combinatorial-purged CV), `cosmu/master/fdr.py` (BH), `cosmu/research/gate.py` (the gate). **These — not any external tool — are the moat.**

## 5. The data & raw artifacts (links)
- **Prices:** Binance public klines (crypto daily to 2017) + Yahoo ETFs (to 2016). **Real alt-data:** prod Postgres `alt_data` (13.6M rows; `DATABASE_URL`). **Space-weather:** GFZ Kp/sunspots since 1932.
- **Raw trial data (R2, DuckDB-queryable, droppable):**
  - `r2://cosmu-lake/astro_lab/run_*/` — the 152,166 strategy trials (parquet)
  - `r2://cosmu-lake/astro_lab/composite|event_study|lunar_vol|audits/` — per-experiment results
  - `r2://cosmu-lake/research_registry/exp/*.parquet` — **the registry (one record per experiment)**
  - local mirrors under `apps/engine/.cosmu/astro_lab/` + `.cosmu/research_registry/`
- **Reports:** `docs/research/astro_vs_markets{,_deep}.md`, `astro_strategy_lab.md`, `astro_composite.md`, `astro_event_study.md`, `astro_lunar_vol.md`, `alt_data_pit_audit.md`, `RESEARCH_LESSONS.md`, `RESEARCH_PREVIEW.md`.
- **DB verdicts:** the autonomous finder's ~130 astro/alt attempts are all `status=killed` in `strategy_versions` (the gate working). 0 astro strategies reached paper.

## 6. The standardized format (how future explorations look like this one)
Every study ends with **one registry record** so the body of work is never lost and stays sortable:
```python
from research_registry import ResearchExperiment, record
record(ResearchExperiment(id=..., date=..., family=..., title=..., hypothesis=..., method=...,  # method = test + NULL
       verdict=...,  # one of NO_EDGE | CANDIDATE | KILLED | ARTIFACT | EDGE | INFRA
       tradeable=..., headline=..., universe=..., data_sources=[...], key_numbers={...},
       lessons=[...], disconfirmer=..., artifacts=[...R2/docs...], provenance="astro|quant|vibe"))
```
`generate_preview()` rebuilds `RESEARCH_PREVIEW.md` from the registry. **Future contract:** same data loaders, same R2 store, same proper-null discipline, same registry record. A new exploration = a new `family` + new records, never a new ad-hoc format.

## 7. The honest expectation for the NEXT (deepest) astro dive
~95% a documented null. The only place a non-zero probability sits is the **belief/attention channel** (astrology as a self-fulfilling retail signal — the Mercury-retrograde belief paper template). The deep dive (PREPARED, awaiting approval — see `docs/research/astro_final_deepdive_PLAN.md` + the heavy web-research plan) must put its probability mass there: **quantify the belief** (Google-Trends astro terms, social astro sentiment, named practitioners' calls vs outcomes, decans/"faces") crossed with the deterministic event calendar — NOT in the planets. Everything deterministic is already, definitively, zero.

## 8. v2 update — the BELIEF channel is now closed too
The one residual channel (astrology-as-belief/attention) was tested end-to-end (`scripts/research/astro_belief/belief_study.py`, ported from Qi-Wang-Zhang 'Long Live Hermes'): Mercury-retrograde dummy × **Wikipedia-pageview belief intensity** (real instrument — the retrograde page spikes **2.4×** during retro, Welch t=25.6; PIT-clean, non-revised). **Verdict: NO_EDGE, the 'least dead' astro candidate but still null.** The retrograde return drop is real in-window (−22bps, t=−2.68) BUT: the **retail-interaction test (most diagnostic) FAILS** (drop not retail-concentrated, t=−0.32), there is **no Ma-Kou reversal** (post-window −1.2bps → not belief mispricing), the **Monte-Carlo placebo** gives p=0.094 (not <0.05), and the tradeable rule's **Deflated Sharpe is 0.69 << 0.95**. So astrology is now definitively closed across deterministic AND behavioral channels. Reusable residue: the PIT-clean Wikipedia-pageview belief loader (`astro_belief/wiki_pageviews.py`) — valuable for NON-astro retail-sentiment strategies. Registry: `astro_belief_hermes` (R2 cosmu-lake/research_registry/).

## 9. How to RESUME / review later (the exact recipe — verified)
A future session (even in a fresh worktree) picks up the entire astro effort:
1. **READ** this file + `docs/research/RESEARCH_PREVIEW.md` (auto-scoreboard of all 19 experiments) + `docs/research/RESEARCH_LESSONS.md`.
2. **THE INDEX:** `cd apps/engine; set -a; . <repo>/.env.local; set +a; python3 scripts/research/research_registry.py list` → every experiment + verdict + artifacts. `python3 scripts/research/research_registry.py` rebuilds the preview.
3. **THE RAW DATA (two durable homes):**
   - **R2** (big data): DuckDB → `SELECT * FROM read_parquet('r2://cosmu-lake/astro_lab/run_*/*.parquet')` (152,166 trials), + `composite|event_study|lunar_vol|belief/`, + `research_registry/exp/`. Creds: the DuckDB-native R2 secret in `scripts/research/astro_strategy_lab/lab_store.py` (reads R2_* from .env.local).
   - **GIT/main** (versioned): the edge-hunt result CSVs (`apps/engine/scripts/research/astro_deep/*.csv`), all reports (`docs/research/*.md`), all scripts.
4. **RE-RUN any experiment** — the scripts are self-contained: `python3 scripts/research/astro_strategy_lab/run_lab.py` (152k sweep), `.../lunar_vol.py`, `.../astro_belief/belief_study.py`, `scripts/research/astro_deep/*_study.py`. Heavy sweeps → Modal via `scripts/research/astro_deepdive_modal.py` (harness fixed).
5. **KEEP GOING** — add a new `ResearchExperiment` record (§6); the format is locked. The PREPARED next dive is `docs/research/astro_ULTIMATE_dive_PLAN.md` (run on approval).
**Durability rule:** R2 `cosmu-lake` = durable big data; git/main = durable code + reports + CSVs + index code. The local `.cosmu/` mirror is convenience-only (gitignored, temp-worktree) — never rely on it. Note: `.env.local` lives at `<repo>/.env.local` (repo root, persists across worktrees), NOT inside the worktree.
