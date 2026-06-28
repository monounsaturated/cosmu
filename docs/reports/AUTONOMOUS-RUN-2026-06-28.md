# 🤖 Autonomous Run — 2026-06-28 (master log + QA guide)

> **READ THIS FIRST when you come back.** This is the single entry point for everything done while you were away.
> It has 4 parts: **(1)** what shipped in this chat (already merged — QA in prod), **(2)** the autonomous-run log
> (branches/PRs created but **NOT merged** — your review + approval needed), **(3)** the live roadmap, **(4)** a QA checklist.
>
> **Rules I am operating under this run (12:30 → ~18:30):** full autonomy · no merges to `main` · no irreversible
> changes · no questions asked · no `spawn_task` chips · I launch all sub-agents myself · everything reversible &
> reviewable · North Star = **autonomous profit, net of fees** · the Gate is the moat (never loosened).

---

## PART 1 — Shipped in this chat (ALREADY MERGED to `main`, deployed Modal v23) → QA in prod

Repo: `github.com/monounsaturated/cosmu`. Main tip at run start: `95370be2` (through PR #456).

### The cross-disciplinary "honesty instruments" wave (all merged)
| PR | What | Live/Dormant | QA hook |
|----|------|--------------|---------|
| [#442](https://github.com/monounsaturated/cosmu/pull/442) | Placebo empirical-null panel (Gate self-validation) | Offline-audit | `research/placebo_panel.py` — 0/50 placebos clear; beat-B&H is load-bearing |
| [#453](https://github.com/monounsaturated/cosmu/pull/453) | Trial-count honesty ledger (deflate DSR on TRUE N) | Write live / recompute offline | `master/trial_ledger.py` — counts looks, never averages perfs |
| [#452](https://github.com/monounsaturated/cosmu/pull/452) | Blinding-commit (hidden-box holdout) | **Live** (refuses graduation on recipe drift) | `master/blinding.py` |
| [#450](https://github.com/monounsaturated/cosmu/pull/450) | Replication cohort (R3) + sequential paper test | Dormant (additive) | `research/replication_cohort.py` — quorum by symbol |
| [#448](https://github.com/monounsaturated/cosmu/pull/448) | Crowding clamp (Kelly × signal-corr, T2) | Dormant (propose-only) | `master/signal_crowding.py` |
| [#445](https://github.com/monounsaturated/cosmu/pull/445) | Decay monitor (pheromone-evaporation study) | Dormant (design-only) | `research/decay_monitor.py` |
| [#444](https://github.com/monounsaturated/cosmu/pull/444) | Worst-regime + LTCM forced-exit stress (TAA) | Dormant (informs) | `research/equity_taa_stress.py` |
| [#441](https://github.com/monounsaturated/cosmu/pull/441) | Lean front read-outs (voice scoreboard · holdout-OOS · provenance) | Read-only | `/mind` page + strategy sheet |
| [#437](https://github.com/monounsaturated/cosmu/pull/437)/[#446](https://github.com/monounsaturated/cosmu/pull/446) | LLM voices/authority lane template (keyless, mock-default, $0) | Mock/observe-only | `config/voices.py` |

### Edge experiments run this chat (all KILLED/NO-GO honestly — public-data price/calendar/attention signals exhausted)
- [#443](https://github.com/monounsaturated/cosmu/pull/443) N1 UMA pre-settlement — KILL · [#447](https://github.com/monounsaturated/cosmu/pull/447) N5 token-unlock — KILL · [#451](https://github.com/monounsaturated/cosmu/pull/451) N11 attention-acceleration — KILL · [#439](https://github.com/monounsaturated/cosmu/pull/439) Polymarket×Kalshi arb — NO-GO
- Post-run (already on main): [#455](https://github.com/monounsaturated/cosmu/pull/455)/[#456](https://github.com/monounsaturated/cosmu/pull/456) per-combo visibility + opt-in deep/timeframe screen axis; timeframe re-screen 0/8 (crypto-price exhausted holds across 1h/4h/1d).

### The BRUT-integrity audit (this chat — verification only, NO code change)
**Your question:** did the trial-count ledger / any instrument reintroduce the per-strategy-averaged deflated Sharpe
(mean-of-OOS + mean-of-%-perf across a strategy's combos) that you had removed from the Gate?
**Answer: NO — verified in code.**
- Live verdict = `promote_brut` ([cohort.py:196]) judges each combo on its OWN streams, `TrialStats(count=1)`, no sibling deflation, no per-strategy mean. `loop.py:561` "NO RE-POOLING"; `loop.py:77` the pooled metric is explicitly "POOLED display metrics".
- #453 counts ESSAIS (looks) + decorrelates by ρ̄; never averages perfs; its `effective_n` is "Audit-only; never a gate input" → consumed only by the offline `scripts/research/recompute_survivor_dsr.py`.
- The pooled `fmean(total_return across symbols)` at `backtest.py:1093` survives only as a **display** metric; the `promote_cohort` path that consumes it is the **research-cohort lane** (1 basket strategy = 1 blended book = legit), which **interprets, does not fund**.
- **Verdict: per-combo BRUT model intact.** One optional hardening proposed: a regression tripwire asserting pooled-oos never becomes a verdict input (see Part 3).

---

## PART 2 — Autonomous-run log (branches/PRs created — NOT merged; review needed)

> Each entry: branch · what · status · how to review. **Nothing here is on `main`.** All draft PRs.

_(updated continuously as waves complete)_

- **WAVE 0 (setup):** this doc, on branch `claude/autonomous-run-2026-06-28` (draft PR). Living document.
- **WAVE 1 (in flight):** clean-state verification + deep bottleneck analysis + autonomous roadmap synthesis.

---

## PART 3 — Live roadmap (what I'm working toward, ranked by leverage to the North Star)

Anchored on the backlog NOW/NEXT + the cross-disciplinary playbook + your stated priorities (backend > frontend,
engineering > polish, the human will help author strategies SOON → a standardized "railway" is needed).

**Candidate high-leverage workstreams (WAVE 1 will re-rank adversarially):**
1. **Leakage tripwire UPSTREAM of the Gate** `[P0]` — the #1 blow-up vector; the Gate validates edge, not pipeline honesty. Feature-side PIT/`available_at` audit + permutation/shuffle null + ticker-anonymization disconfirmer.
2. **Strategy-creation railway** `[P1]` — standardized typed-spec intake + validation + `/generate-strategies` scaffolding so the human's strategies are uniform & reviewable (explicitly requested).
3. **Pooled-oos regression tripwire** `[S]` — freeze the BRUT-integrity guarantee you just had me verify.
4. **Edge hypothesis diversity / new data axes** — the binding constraint is the DATA WALL, not method.
5. **Backtest provenance + source≠venue + fees-per-venue** + **USDC liquidity-first base-currency module** (operator requests).
6. **Wire dormant instruments** (placebo/replication/crowding/decay/worst-regime) into the live verdict/sizing where it helps.

---

## PART 4 — QA checklist (for when you're back)

**Already-merged (prod) — spot-check:**
- [ ] `/mind` page renders the voice scoreboard (untested voices show "untested", not 0).
- [ ] Strategy sheet shows holdout/OOS evidence + data provenance.
- [ ] Modal v23 healthy (`modal app history`); the 5 crons stepping.
- [ ] Gate constants byte-identical (DSR 0.95 / FDR / PBO / min-trades / holdout / beat-B&H).

**Autonomous-run branches — review before any merge:** _(filled in as PRs are created)_

---

_Last updated: WAVE 0 (run start)._
