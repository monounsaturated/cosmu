# Cross-Disciplinary Playbook — inspiration, known flaws, alternatives (2026-06-26)

> Output of an open-minded multi-agent research sweep (7 lenses: biomimicry · rigorous-evidence fields · forecasting/decision science · winning quant shops · known failure modes · alternative paradigms · how small players win → 47 bridges, 35 alternatives). Findings-only; a playbook to act on in the NEXT chat.

## BLUF
- **Most promising:** a standing **negative-control empirical-null panel** (from pharmaco-epidemiology / GWAS — Schuemie/OHDSI). Run shuffled / random-entry **placebo** specs through the exact finder→Gate every cohort; a real survivor is only credible if it sits in the right tail of an *empirically measured* null. This turns the #1 unmeasurable fear (Gate-invisible upstream leakage) into a **continuously-monitored instrument**, near-zero cost.
- **Scariest flaw:** **trial-count undercounting in DSR deflation.** If the N fed into expected-max-Sharpe excludes the seeder sweep, exit-envelope sweep, and every (strategy×symbol×venue) cell ever replayed, the Gate is rigorously strict on a *dishonest* N — the single most likely way an honest-looking machine self-deceives at scale. The look-elsewhere scan over ~40 symbols × venues is the same bug.

## Top 8 cross-domain bridges (ranked by leverage)
| # | Borrowed idea | From field | Concrete COSMU experiment | Effort |
|---|---|---|---|---|
| 1 | **Negative-control empirical null** — measure where placebos land, recalibrate every p-value | Pharmaco-epi / GWAS | Author 10 negative-control specs (5 time-shuffled, 5 random-entry matched-turnover), run finder→Gate each cohort; survivor DSR vs the placebo null. Any placebo clears → leak caught | Low |
| 2 | **Cumulative / effective trial-count deflation** | HEP look-elsewhere (Gross-Vitells) + Harvey-Liu-Zhu | Persistent trials ledger (every backtest + every symbol×param cell); recompute a survivor's DSR at N = effective independent cells scanned | Low-Med |
| 3 | **Blinding commit on the holdout** — freeze the recipe hash before first holdout touch | Particle physics (hidden-box) | `blinding_commit(version_id, recipe_hash, committed_at)`; Gate refuses to score if recipe_hash changed after first holdout read | Low |
| 4 | **Purge + embargo + sample-uniqueness audit** of CPCV/CSCV | López de Prado | Re-run a survivor's CPCV with purge + k-bar embargo; recompute PBO; uniqueness weights → recheck effective-N vs the 30-trade floor | Low |
| 5 | **Independent cross-asset/venue replication cohort** — replication is the final arbiter, not FDR | GWAS | Re-run a survivor's FROZEN spec (no refit) on 3-5 held-out symbols/venues it was NOT discovered on. No replication = single-cell overfit | Low |
| 6 | **Polymarket structural arb + domain×horizon recalibration fade** | Prediction-market microstructure | Price-signal-FREE lane: (a) scan multi-outcome groups for Σ(YES) < $1 net fee; (b) fit calibration slope per (domain, days-to-resolution), fade when recalibrated−market > spread+fee | Med |
| 7 | **Portfolio-Kelly correlation clamp** tied to the *deflated* edge | Bet-sizing / Khandani-Lo crowding | `master/sizing.py`: fractional-Kelly per cell from deflated edge + pairwise corr matrix, scale down crowded clusters. Ships the long-backlogged crowding detector (T2) | Med |
| 8 | **Pheromone-evaporation allocation decay** — size decays on a half-life unless re-confirmed forward | Swarm / ACO | Replay applying `exp(−Δt/τ)` to each track's size since its last forward confirmation (τ = edge half-life); decayed vs hold-until-fail | Low-Med |

## Red-team list (the 12 failure modes COSMU is most exposed to)
1. **Trial-count undercounting** (DSR un-deflated) — inject a known-null spec, "tune" it like a human, check the N reflects the true number of looks (incl. abandoned + sweeps + cross-symbol replays).
2. **Look-elsewhere on the symbol/venue axis** — scan a pure-noise spec over ~40 symbols×venues; if family-wise FP ≫ alpha, deflate by effective-N.
3. **Leakage upstream of the Gate** (Kapoor-Narayanan 8-type) — forward-window feature defs, global normalization over full history, revision-unsafe alt-data, non-purged fold contamination. Feature Info Sheet per source.
4. **Holdout blind by convention, not construction** — grep any path where params change after first holdout read with no blinding commit (→ bridge #3).
5. **Theoretical null assumed correct** — verified by the negative-control panel (#1): if placebos clear, the null is miscalibrated.
6. **Self-crowding via the evolve lane** — pairwise SIGNAL correlation across funded combos; cluster > ~0.7 = one trade under stress.
7. **Worst-regime fragility** — Gate judges AVERAGE edge; red-team every survivor (esp. TAA) for the MINIMUM Sharpe split by vol regime.
8. **Effective-N inflation from overlapping labels** — 30 overlapping trades may be ~8 independent bets; recheck the floor + DSR at effective-N.
9. **Adverse selection / toxic flow on thin venues** — log post-fill mark-outs 2wk; negative → toxicity haircut → re-Gate. (Concentrated in our niche moat.)
10. **Stress-liquidity / forced-exit** (LTCM) — re-price exits at 3-5× calm slippage one-sided; confirm exitable within K bars; correlations under STRESS not calm.
11. **Residualization over-subtracts** (predictive-coding trap) — if shipping a surprise/residual feature, prove the baseline is PIT + deliberately weak.
12. **Prediction-market oracle/resolution risk** (fat left tail) — a UMA whale falsely resolved a $7M market; exclude thin-UMA/ambiguous contracts; discount resolution-dispute risk; never size as if resolution is risk-free.

## Alternative paradigms (small tests next)
1. **Prediction markets as a whole new edge space** (escapes the exhausted crypto tape) — cross-market: Polymarket × **Kalshi** with matching resolution language; log `YES_poly + NO_kalshi` net fees; persistent <$1 → build `structural_arb`. Price-signal-free, market-neutral, desk-invisible.
2. **Causal event-study / synthetic-control alpha** — edge conditioned on an exogenous CAUSE (e.g. new listings), synthetic control from matched non-listed peers, CAR at h=+1/+3/+7. Confounding check: if donors drift the same, it's re-labeled momentum → reject.
3. **Transfer-entropy lead-lag on slow-syncing small alts** — effective-TE per ordered pair + 1000-permutation null; keep only those that are significant, asymmetric, AND collapse under time-reversal (the astro disconfirmer).
4. **Meta-labeling the graveyard** — reuse sunk research: triple-barrier-label a dead spec's entries, train a light regime classifier, route only predicted-true trades back through the Gate. Guard: trial count must include BOTH searches.

## What the winners + other fields AGREE on (the convergent meta-lessons)
Across immunology, particle physics, clinical trials, GWAS, poker, sharp betting, and the quant shops — the same four lessons converge, and they are about **honesty, not cleverness**:
1. **Validation lives on data the discovery never touched.** COSMU's forward/paper lane *is* that replication cohort → elevate it from a 30-day time-wait to a **formal sequential test**.
2. **The null is empirical and the trial count is almost always undercounted.** The honest hurdle rises with how hard you searched (incl. abandoned searches); the only trustworthy null is one measured with placebos.
3. **WHERE you play beats how well you play.** A solo's moat is small/niche/desk-invisible markets → make **capacity a first-class ranked feature**, not a disqualifier.
4. **The killers are all downstream of the backtest** — leakage upstream of the gate, crowding/correlation collapse under stress, post-discovery decay, adverse selection on thin books — none visible to a single-snapshot Sharpe gate.

> **THE UNIFYING DIRECTIVE:** COSMU's Gate is correctly the **discovery** filter. The next phase = building the **time-axis and portfolio-axis instruments** (empirical null · replication cohort · decay monitor · crowding clamp · capacity model) that watch what the Gate structurally cannot.
