#!/usr/bin/env python3
# intent: the STANDARDIZED RESEARCH REGISTRY — one canonical, queryable, frontend-displayable record per research
# experiment (hypothesis → method → verdict → lessons → artifacts), so the body of work is never lost in scattered
# parquet/markdown and EVERY future exploration is logged in the SAME shape. This is the "display these + standardize
# the format" layer. Persisted to R2 (cosmu-lake/research_registry/) + a local mirror via the LabStore DuckDB-R2 path.
# Read-only to the money path. Run: `python3 research_registry.py backfill|preview|list`.
#
# THE CONTRACT for future research: at the end of any study, call record(ResearchExperiment(...)). The verdict
# vocabulary is fixed (NO_EDGE | CANDIDATE | KILLED | ARTIFACT | EDGE | INFRA) so the registry stays sortable.

from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "scripts/research/astro_strategy_lab"))

VERDICTS = ("NO_EDGE", "CANDIDATE", "KILLED", "ARTIFACT", "EDGE", "INFRA")  # fixed vocabulary → sortable


@dataclass
class ResearchExperiment:
    id: str                              # stable slug
    date: str                            # ISO date the experiment ran
    family: str                          # astro · real-signal · calendar · geomag · cross-asset · infra · ...
    title: str
    hypothesis: str                      # what we thought might be true (the prior)
    method: str                          # the test + the NULL used (the most important honesty field)
    verdict: str                         # one of VERDICTS
    tradeable: bool                      # could this make money net of fees, live?
    headline: str                        # the one-line result with key numbers
    universe: str = ""                   # assets/classes tested
    data_sources: list[str] = field(default_factory=list)
    key_numbers: dict = field(default_factory=dict)
    lessons: list[str] = field(default_factory=list)
    disconfirmer: str = ""               # what killed it / what would
    artifacts: list[str] = field(default_factory=list)  # R2 prefixes + docs/research/*.md + scripts
    provenance: str = "quant"            # quant · vibe · astro (matches the strategy provenance facet)

    def __post_init__(self):
        assert self.verdict in VERDICTS, f"verdict must be one of {VERDICTS}, got {self.verdict}"

    def flat(self) -> dict:
        d = dataclasses.asdict(self)
        for k in ("data_sources", "key_numbers", "lessons", "artifacts"):
            d[k] = json.dumps(d[k])  # parquet-friendly
        return d


def _store():
    from lab_store import LabStore
    return LabStore(prefix="research_registry", local_dir=".cosmu/research_registry")


def record(exp: ResearchExperiment) -> dict:
    """Append ONE experiment to the registry (R2 + local). Idempotent by id (one file per id, overwrite)."""
    import pandas as pd
    return _store().save_batch(pd.DataFrame([exp.flat()]), f"exp/{exp.id}")


def read_all():
    import pandas as pd
    s = _store(); con = s._conn()
    try:
        glob = (f"r2://{s.bucket}/{s.prefix}/exp/*.parquet" if s.r2_ready else str(s.local / "exp" / "*.parquet"))
        df = con.execute(f"SELECT * FROM read_parquet('{glob}')").df()
        for k in ("data_sources", "key_numbers", "lessons", "artifacts"):
            if k in df:
                df[k] = df[k].map(lambda x: json.loads(x) if isinstance(x, str) and x else x)
        return df.sort_values("date")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    finally:
        con.close()


# ── the backfill: every experiment this body of work produced, in the standardized format ────────
def _known() -> list[ResearchExperiment]:
    A = "astro"; R = ["Binance daily bars", "Yahoo ETFs"]; RA = R + ["prod alt_data (13.6M rows)"]
    return [
        ResearchExperiment("astro_round1_ic", "2026-06-14", A, "Astrology vs markets — single-signal IC",
            "Deterministic ephemeris/calendar features predict forward returns.",
            "Spearman/Kruskal IC across 32 assets × horizons × bull/bear, BH-FDR + Harvey-Liu-Zhu |t|>3.",
            "NO_EDGE", False, "0 / 4,092 IC tests survive BH-FDR; astro-only weekly p≈0.72.",
            "32 assets (crypto+ETF)", R, {"tests": 4092, "survive_fdr": 0},
            ["Only calendar (turn-of-month/Halloween) is literature-durable; lunar weak; planets folklore."],
            "BH-FDR + |t|>3 → 0 survive.", ["docs/research/astro_vs_markets.md", "scripts/research/astro_market_study.py"], A),
        ResearchExperiment("astro_round2_deep", "2026-06-14", A, "Deep astro vs the REAL alt-data baseline",
            "126 deep astro features add predictive info on top of real signals (funding/social/macro/on-chain).",
            "Pooled walk-forward OOS AUC vs label-permutation null; the INCREMENTAL test (astro on top of real); Modal.",
            "NO_EDGE", False, "IC 0/32,372 survive FDR; astro DEGRADES OOS AUC by -0.015 (h1)/-0.042 (h5), p=1.0.",
            "32 assets", RA, {"ic_tests": 32372, "survive_fdr": 0, "incremental_lift_h1": -0.0148, "p": 1.0},
            ["Adding a known-null feature block to a real model DILUTES it — incremental test is the cleanest question."],
            "Incremental lift ≤ 0, p=1.0.", ["docs/research/astro_vs_markets_deep.md", "scripts/research/astro_deep/"], A),
        ResearchExperiment("astro_strategy_lab_152k", "2026-06-15", A, "152k astro strategy trials (all schools/segments)",
            "Some configuration among thousands (schools × transforms × mechanics × assets) yields a tradeable edge.",
            "4,444 configs × 35 assets = 152,166 backtests, 6 segments incl small-cap; Deflated Sharpe at the TRUE trial count.",
            "NO_EDGE", False, "Raw best Sharpe 1.85 → 0 survive Deflated-Sharpe (expected best-of-N noise = sqrt(2 ln N)/sqrt(T)).",
            "35 assets × 6 segments", R, {"trials": 152166, "raw_best_sharpe": 1.85, "survive_dsr": 0},
            ["More search DEFLATES harder, never 'finds' the edge. Raw Sharpe alone is the false-positive machine."],
            "Deflated Sharpe at N=152,166 → 0 > 0.95.", ["astro_lab/run_*/", "docs/research/astro_strategy_lab.md"], A),
        ResearchExperiment("astro_composite", "2026-06-15", A, "Multi-signal composite + cross-sectional natal",
            "Blending astro + events + real + space-weather + per-coin natal into one score beats the parts.",
            "Honest train(60%)/test(40%) split; signal directions fixed on train; decomposed by group × regime × segment.",
            "NO_EDGE", False, "train→OOS ranking INVERTS (best-train group = worst-OOS) — the fingerprint of noise; astro dilutes.",
            "35 assets", RA, {"real_oos_sharpe": -0.59, "astro_oos_sharpe": -0.15},
            ["train→OOS rank consistency is THE single most diagnostic check; inversion = noise."],
            "OOS ranking inverts the train ranking.", ["astro_lab/composite/", "docs/research/astro_composite.md"], A),
        ResearchExperiment("astro_event_study", "2026-06-15", A, "Vol/turnover around named astro events",
            "A self-fulfilling attention effect shows up as a VOLATILITY bump around named events (full moon/eclipse).",
            "Realized-vol/|ret|/volume-z in ±3d windows vs a FAKE-RANDOM-DATE permutation null (B=2000) + BH-FDR.",
            "CANDIDATE", False, "Apparent full-moon/eclipse realized-VOL effect: 3/76 survive BH-FDR — flagged as candidate.",
            "crypto large/mid", ["Binance daily"], {"tests": 76, "survive_fdr": 3, "fullmoon_effect_sigma": 3.73},
            ["A fake-RANDOM-date null is TOO WEAK for autocorrelated vol — it manufactured these 3 'hits'."],
            "Needed the harder phase-shuffle null (see lunar_vol).", ["astro_lab/event_study/", "docs/research/astro_event_study.md"], A),
        ResearchExperiment("astro_lunar_vol", "2026-06-15", A, "Lunar realized-vol candidate — decisive vetting",
            "The event-study full-moon vol effect is real lunar structure.",
            "8-bin synodic profile + PHASE-SHUFFLE null (preserve the vol series, scramble only phase labels) + outlier-robustness + era stability.",
            "ARTIFACT", False, "phase-shuffle p=0.33, flat profile (contrast 1.011), outlier-driven (drop top-2% → 0.98) → artifact.",
            "23 crypto", ["Binance daily"], {"phase_shuffle_p": 0.33, "contrast": 1.011, "robust_contrast": 0.98},
            ["The proper null (phase-shuffle) KILLED what the weak null passed. Chase a candidate, then try HARD to break it."],
            "Phase-shuffle null p=0.33.", ["astro_lab/lunar_vol/", "docs/research/astro_lunar_vol.md"], A),
        ResearchExperiment("edge_hunt_spectral", "2026-06-15", A, "Spectral / Lomb-Scargle (returns + vol)",
            "Excess power at exact astronomical frequencies (synodic/draconic/planetary) in returns or vol.",
            "Lomb-Scargle periodogram vs AR(1)/IAAFT phase-randomized surrogates preserving autocorrelation.",
            "NO_EDGE", False, "Slow planetary features correlate with vol — but a SYNTHETIC control scored equally → trend artifact.",
            "crypto+equity", R, {"beats_both_nulls": 0}, ["A planted synthetic slow control matching the 'signal' = it's trend, not astronomy."],
            "Synthetic control matches → artifact.", ["scripts/research/astro_deep/spectral_returns.py", "astro_strategy_lab/spectral_vol*.py"], A),
        ResearchExperiment("edge_hunt_info_theoretic", "2026-06-15", A, "Mutual information / transfer entropy",
            "Nonlinear dependence (MI/TE) between astro states and forward returns/vol that Spearman/AUC miss.",
            "KSG mutual information + conditional transfer entropy vs circular-shift surrogate; BH + Bonferroni.",
            "NO_EDGE", False, "A few raw-significant (z up to 5.2) but 0 survive BH/Bonferroni across the grid.",
            "crypto+equity", R, {"max_z": 5.2, "survive_bh": 0}, ["Nonlinear estimators still need multiple-testing correction; raw z lies."],
            "0 survive BH/Bonferroni.", ["scripts/research/astro_deep/info_theoretic_study.py", "transfer_entropy_study.py"], A),
        ResearchExperiment("edge_hunt_tail", "2026-06-15", A, "Tail / extreme-event clustering",
            "Astro configurations cluster crashes/jumps (fat-tail events) rather than mean returns.",
            "Jump/crash-onset dates vs astro states, within-YEAR permutation null (preserves regime-scale clustering).",
            "NO_EDGE", False, "Clustering dies under the within-year permutation null (low-freq masks need the right null).",
            "crypto+equity", R, {}, ["A circular-shift null on a low-frequency mask UNDER-estimates variance; use within-year."],
            "Within-year permutation null.", ["scripts/research/astro_tail_decisive.py"], A),
        ResearchExperiment("edge_hunt_named_systems", "2026-06-15", A, "Bradley / Gann / Merriman turn-dates",
            "Named financial-astrology systems predict market TURNING POINTS (their actual claim is timing).",
            "Hit-rate of swing extrema within ±k days of predicted turns vs circularly-shifted-curve null + a multiple-testing charge.",
            "NO_EDGE", False, "Merriman CRD +1.0pp hit-rate (97.6 vs 96.6%) p=0.001→Bonf 0.048: near-saturation, NOT economic.",
            "crypto+equity", R, {"merriman_uplift_pp": 1.0, "bonferroni_p": 0.048},
            ["A +1pp uplift on a 97% saturated base is statistically marginal and economically meaningless."],
            "Near-saturation + not economic.", ["scripts/research/verify_merriman_crd.py", "named_systems_turndates.py"], A),
        ResearchExperiment("edge_hunt_hier_bayes", "2026-06-15", A, "Hierarchical-Bayes partial pooling",
            "A weak COMMON astro effect, invisible per-asset, is detectable by pooling across assets.",
            "DerSimonian-Laird random-effects meta-analysis of per-asset IC + permutation; vs lead-lag/OOS disconfirmers.",
            "NO_EDGE", False, "jupiter-saturn pooled z=6.6 — but it's the cross-asset-CORRELATION-inflated pooling artifact (DL SE wrong).",
            "27 assets", R, {"jupsat_z": 6.6}, ["Pooling assumes independent studies; correlated crypto returns inflate the pooled z — spurious."],
            "Dies under lead-lag symmetry + OOS split.", ["scripts/research/astro_deep/hier_bayes_meta.py"], A),
        ResearchExperiment("edge_hunt_geomag", "2026-06-15", "geomag", "Geomagnetic storms (Krivelyova-Robotti)",
            "High geomagnetic (Kp) storm days precede lower crypto returns (the K-R behavioral channel).",
            "Post-storm forward return vs circular/AR/IAAFT nulls + OOS split + economic test.",
            "NO_EDGE", False, "-25bps post-storm (RIGHT sign!) but p≈0.10 under proper nulls and DECAYS OOS (-43→-8bps).",
            "crypto EW", ["Binance daily", "GFZ Kp"], {"obs_bps": -24.97, "p_iaaft": 0.108, "first_half_bps": -43.4, "second_half_bps": -7.6},
            ["The 'least dead' candidate: right sign + a real mechanism, but not significant + decays. Worth a forward watch, not capital."],
            "p≈0.10 + OOS decay.", ["scripts/research/astro_deep/geomag_kr_study.py", "geomag_kr_adversarial_verify_results.json"], "quant"),
        ResearchExperiment("edge_hunt_sad", "2026-06-15", "calendar", "SAD / daylight seasonality",
            "Seasonal-affective daylight cycles drive a risk-appetite seasonality in returns.",
            "Daylight-slope regression with HAC t-stats + permutation null + BH-FDR across latitude classes.",
            "NO_EDGE", False, "p≈0.10, FDR-fail (slopes look big in bps but not significant).",
            "crypto+GLD", ["Binance daily", "Yahoo"], {"min_p": 0.086}, ["Big-looking annualized bps ≠ significant; FDR over latitude classes kills it."],
            "FDR-fail.", ["scripts/research/astro_deep/sad_daylight_study.py"], "quant"),
        ResearchExperiment("real_signal_pit_audit", "2026-06-15", "real-signal", "PIT honesty audit of the real signals",
            "The real alt-data signals are live-tradeable (knowable + identical live vs backtest).",
            "Per-metric availability lag, backfill detection (ingest lag), revision detection (same ts → multiple available_at/value).",
            "INFRA", True, "fear_greed/funding/vix/dxy/fed_funds = LIVE-TRADEABLE; LunarCrush social = backfilled+revised → LOOK-AHEAD trap.",
            "all real metrics", ["prod alt_data"], {"immutable_safe": 5, "revising_suspect": 3},
            ["A predictor is usable only if knowable BEFORE the move AND identical live vs backtest. Backfilled+revising = mirage."],
            "Backfilled + vendor-revises → not live-usable.", ["astro_lab/audits/", "docs/research/alt_data_pit_audit.md"], "quant"),
    ]


def backfill() -> int:
    n = 0
    for exp in _known():
        record(exp); n += 1
    print(f"backfilled {n} experiments → R2 research_registry/ + local")
    return n


def generate_preview(out: str | None = None) -> str:
    df = read_all()
    out = out or str(ENGINE_ROOT.parent.parent / "docs/research/RESEARCH_PREVIEW.md")
    if df.empty:
        Path(out).write_text("# Research preview — registry empty (run `backfill` first)\n"); return out
    nov = (df.verdict == "NO_EDGE").sum() + (df.verdict == "ARTIFACT").sum() + (df.verdict == "KILLED").sum()
    L = ["# Research preview — everything we tested, and the smart stuff we learned\n",
         f"_Auto-generated from the standardized Research Registry ({len(df)} experiments). Every future exploration "
         "logs here in the SAME format — `research_registry.record(ResearchExperiment(...))`. Source of truth: "
         "R2 `cosmu-lake/research_registry/`._\n",
         f"## Scoreboard — {len(df)} experiments\n",
         f"- **Tradeable edges found:** {int(df.tradeable.sum())} "
         f"({'none — every hypothesis falsified' if df.tradeable.sum()==0 else 'see EDGE rows'}).",
         f"- **Verdicts:** " + " · ".join(f"{v}={int((df.verdict==v).sum())}" for v in VERDICTS if (df.verdict==v).any()),
         f"- **By family:** " + " · ".join(f"{f}={int((df.family==f).sum())}" for f in sorted(df.family.unique())) + "\n",
         "## Every experiment (sortable)\n",
         "| date | family | experiment | verdict | tradeable | headline |",
         "|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        L.append(f"| {r.date} | {r.family} | {r.title} | **{r.verdict}** | {'✅' if r.tradeable else '—'} | {r.headline} |")
    L.append("\n## The smart lessons (distilled across all experiments)\n")
    seen = set()
    for _, r in df.iterrows():
        for les in (r.lessons or []):
            if les not in seen:
                seen.add(les); L.append(f"- **[{r.family}]** {les}")
    L.append("\n## The honest bottom line\n")
    L.append("Across every experiment, **0 tradeable edges** survived an honest gate (proper null + OOS + economic + "
             "deflation). The closest was the geomagnetic −25bps (right sign, but p≈0.10 + decays). The value produced is "
             "(a) a *definitive* falsification of astro across every dimension a top quant/physicist/astronomer would check, "
             "(b) the live-honest data + R2 infra, and (c) the reusable honesty pipeline + these lessons. The next lucrative "
             "move is NOT astro — it is the real-signal / funding / cross-sectional-momentum directions the gate already "
             "half-believes, ingested live-forward.\n")
    Path(out).write_text("\n".join(str(x) for x in L) + "\n")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "backfill":
        backfill()
    elif cmd == "list":
        df = read_all()
        print(df[["date", "family", "id", "verdict", "tradeable"]].to_string(index=False) if not df.empty else "(empty)")
    else:
        backfill()
        p = generate_preview()
        print(f"preview → {p}")
