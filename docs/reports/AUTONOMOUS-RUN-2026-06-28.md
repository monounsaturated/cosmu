# 🤖 Autonomous Run — 2026-06-28 (master log + QA guide)

> **READ THIS FIRST when you come back.** Single entry point for everything done while you were away.
> 4 parts: **(1)** what shipped in this chat (already merged — QA in prod), **(2)** the autonomous-run log
> (branches/PRs created but **NOT merged** — your review + approval needed), **(3)** the live roadmap, **(4)** a QA checklist.
>
> **Rules this run (12:30 → ~18:30):** full autonomy · no merges to `main` · no irreversible changes · no questions ·
> no `spawn_task` chips · I launch all sub-agents myself · everything reversible & reviewable as **draft PRs** ·
> North Star = **autonomous profit, net of fees** · the Gate is the moat (never loosened).

---

## ⭐ RUN SUMMARY (executive — read this first)

A 6-hour fully-autonomous run produced **22 draft PRs (#457–#479)** — **all reversible, NONE merged, every code PR adversarially pre-reviewed clean, and the whole batch `git merge-tree`-verified safe to merge sequentially (zero conflicts).** Gate constants byte-identical throughout; per-combo BRUT preserved; money-path PRs explicitly verified they cannot over-arm / move money / loosen a fee; nothing deployed.

**🎯 The 3 things to do on return:**
1. **Review + merge the batch** — the verified merge order is in Part 4's **Merge Guide** (safe sequentially; strip each PR's "DO NOT MERGE" line on merge). Redeploy Modal after the money-path trio (#465/#471/#474).
2. **⚠️ DEPLOY the HL positioning logger ([#479](https://github.com/monounsaturated/cosmu/pull/479))** — it's the best remaining edge axis ($0/keyless/PIT-clean) and is **data-starved at birth**; every day un-deployed is a day later the Gate can rule (~2–3wk forward-hoard needed).
3. **Decide the deferred follow-ups** (Part 4 — funder re-key, etc.) + any **paid data** (the next-data-axis report says **$0 to start**; hold spend behind a proven free whiff).

**📦 What shipped, by theme:**
- **Honesty / moat:** leakage tripwire at the feature-door ([#458]), source-door ([#463]), + standing audit ([#466] — pipeline **LEAK-FREE**, 0/79); BRUT-integrity regression tripwire ([#459]); placebo cohort-rider ([#461]).
- **Strategy-authoring railway:** inbox-lint ([#460], 125 specs→119/6/26 dups) + wave-0 novelty-gate ([#470]).
- **Path to first live $:** live-arming dry-run proves the chain fires ([#467]) + 2 real gaps FIXED ([#471]) + capital_guard now scheduled every tick ([#465]).
- **Fee / data honesty:** paper-fee-parity ([#474] — fixed a real funding-gate bug: paper under-charged Polymarket/IBKR) · provenance+divergence surfacing ([#475]) · USDC liquidity-first module ([#469]) · pipeline integrity audit ([#472]).
- **Edge hunt (North Star):** intraday microstructure ×3 → KILL ([#468]/[#473]/[#476]); Polymarket Σ(YES)<$1 arb → KILL ([#477]); Aave money-market stress → KILL ([#478]); **→ forward lead: HL long-tail positioning logger BUILT** ([#479], deploy to hoard) + the next-data-axis recommendation report.

**📉 Honest bottom line:** **no edge survived the Gate this run — the binding constraint is the DATA WALL, not the method or the Gate** (which validated itself repeatedly). The run converted that reality into a **hardened moat, a de-risked live path, and a ready-to-deploy $0 forward bet** (HL positioning) whose verdict needs ~2–3 weeks of hoarded data. The single highest-leverage next action is mechanical: **deploy #479 and start the clock.**

---

## PART 1 — Shipped in this chat (ALREADY MERGED to `main`, deployed Modal v23) → QA in prod

Repo: `github.com/monounsaturated/cosmu`. Main tip at run start: `95370be2` (through PR #456).

### The cross-disciplinary "honesty instruments" wave (all merged)
| PR | What | Live/Dormant |
|----|------|--------------|
| [#442](https://github.com/monounsaturated/cosmu/pull/442) | Placebo empirical-null panel (Gate self-validation) | Offline-audit (0/50 placebos clear; beat-B&H load-bearing) |
| [#453](https://github.com/monounsaturated/cosmu/pull/453) | Trial-count honesty ledger | Write live / recompute offline (counts looks, never averages perfs) |
| [#452](https://github.com/monounsaturated/cosmu/pull/452) | Blinding-commit (hidden-box holdout) | **Live** (refuses graduation on recipe drift) |
| [#450](https://github.com/monounsaturated/cosmu/pull/450) | Replication cohort (R3) + sequential paper test | Dormant (additive) |
| [#448](https://github.com/monounsaturated/cosmu/pull/448) | Crowding clamp (Kelly × signal-corr) | Dormant (propose-only) |
| [#445](https://github.com/monounsaturated/cosmu/pull/445) | Decay monitor | Dormant (design-only) |
| [#444](https://github.com/monounsaturated/cosmu/pull/444) | Worst-regime + LTCM forced-exit stress (TAA) | Dormant (informs) |
| [#441](https://github.com/monounsaturated/cosmu/pull/441) | Lean front read-outs (voice scoreboard · holdout-OOS · provenance) | Read-only |
| [#437](https://github.com/monounsaturated/cosmu/pull/437)/[#446](https://github.com/monounsaturated/cosmu/pull/446) | LLM voices/authority lane template (keyless, mock-default, $0) | Mock/observe-only |

### Edge experiments (all KILLED/NO-GO honestly — public-data price/calendar/attention exhausted)
[#443](https://github.com/monounsaturated/cosmu/pull/443) N1 UMA · [#447](https://github.com/monounsaturated/cosmu/pull/447) N5 token-unlock · [#451](https://github.com/monounsaturated/cosmu/pull/451) N11 attention · [#439](https://github.com/monounsaturated/cosmu/pull/439) Polymarket×Kalshi · [#455](https://github.com/monounsaturated/cosmu/pull/455)/[#456](https://github.com/monounsaturated/cosmu/pull/456) per-combo visibility + deep/timeframe screen (0/8).

### BRUT-integrity audit (verification only — NO code change)
**Your question:** did #453 / any instrument reintroduce the per-strategy-averaged deflated Sharpe you removed? **Answer: NO.**
Live verdict = `promote_brut` ([cohort.py:196]) per-combo, `TrialStats(count=1)`, no sibling deflation; `loop.py:77` the pooled metric is "POOLED display metrics" only; #453 counts looks not perfs (offline recompute). The pooled `fmean` at `backtest.py:1093` survives only as display; the `promote_cohort` consumer is the research-cohort lane (1 basket = 1 book = legit, interprets-not-funds). **Per-combo BRUT model intact.** → frozen by WAVE 2 regression tripwire (Part 2).

---

## PART 2 — Autonomous-run log (branches/PRs — NOT merged; review needed)

> Everything here is on a branch. **Nothing is on `main`.** All draft PRs.

### WAVE 0 — setup ✅
- Master log + QA guide → branch `claude/autonomous-run-2026-06-28`, draft PR [#457](https://github.com/monounsaturated/cosmu/pull/457). Living document (this file).

### WAVE 1 — clean-state + bottleneck + roadmap ✅ (workflow, 7 agents, ~493k tokens)
- **Clean state: `nothing_lost = TRUE`.** All substantive work is on `origin/main`. Of 113 remote branches, ~106 are squash-merged duplicates (`git cherry` `+0 -1`); the 7 flagged were file-checked — all on main / superseded. `origin/wip/snapshot-2026-06-26` intact at `12875f33`, correctly NOT replayed.
- **Genuinely-unmerged (all dormant/trivial/superseded — nothing valuable stranded):** `claude/jolly-lamport-lncwph` (06-21 crowding-positioning data spike, dormant area), `claude/focused-fermat-w9ii8j` (trivial web route-guard), `claude/tender-turing-19c2dd` (2 superseded skill drafts: ingest-idea, research-review). 
- **Optional cleanup for you (low-pri, NOT done — needs your ok):** delete the ~106 squash-merged branches to declutter; keep `wip/snapshot-*` and this run's branch.
- **Ground-truth corrections found:** Alpaca equity execution is **already wired on main** (only `research/equity_daa_arm.py:42 VENUE="ibkr"` left to flip); `capital_guard.run_capital_guard()` exists but is **only API-reachable, never scheduled** (real safety gap); `authority_weighted_claim_signal` feature is registered but **0 specs enter on it**; `research/leakage_tripwire.py` (`audit_feature`) + `research/disconfirmers.py` (`symbol_anonymization_null`) **already exist but are wired to nothing**.

### WAVE 2 + leakage (build agents, isolated worktrees, each its own draft PR)
| Item | Branch / PR | Status |
|------|-------------|--------|
| Leakage tripwire — wired the missing **ticker-anonymization** disconfirmer into the `audit_feature` bundle (+ `--anon` CLI, 44 tests). Module already existed (#387); no duplication. | [#458](https://github.com/monounsaturated/cosmu/pull/458) | ✅ done |
| BRUT-integrity tripwire — 3 regression tests + 8-line per-cell guard in `loop.py::_score_cells` (pooled-oos can never rescue a per-cell verdict). | [#459](https://github.com/monounsaturated/cosmu/pull/459) | ✅ done |
| #1 Placebo panel → standing finder cohort-rider (flag default-OFF, observe-only; new `lab/placebo_rider.py`) | [#461](https://github.com/monounsaturated/cosmu/pull/461) | ✅ done |
| #7 Standing leakage-audit over ALL wired alt-features — **0 real leaks** (79 features: 2 PASS, 40 WARN=weak-signal, 0 FAIL, 37 SKIP=thin history); caught + corrected its own false-alarm (non-causal astro controls failed identically ⇒ recalibrated to \|IC\|≥0.30 & n≥60) | [#466](https://github.com/monounsaturated/cosmu/pull/466) | ✅ done |
| #2 inbox-lint CLI — strategy-authoring railway rung (verified on real inbox: **125 specs → 119 pass / 6 fail / 26 near-dup clusters**) | [#460](https://github.com/monounsaturated/cosmu/pull/460) | ✅ done |
| #3 Leakage tripwire → `profile_source` GO/REVIEW/NO-GO (behavioral `audit_feature` folds in; baked-in-alignment leak ⇒ NO-GO) | [#463](https://github.com/monounsaturated/cosmu/pull/463) | ✅ done |
| #5 capital_guard watchdog scheduled in every orchestrator tick (default-on, only REDUCES, never arms) + equity-arm VENUE→alpaca config-driven | [#465](https://github.com/monounsaturated/cosmu/pull/465) | ✅ done |
| #10 End-to-end live-arming dry-run — **full path FIRES** (eligible→arm→testnet order→fill→guard disarm, 7/7, no real money). Surfaced 2 real capital-path gaps ↓ | [#467](https://github.com/monounsaturated/cosmu/pull/467) | ✅ done |
| #10b **Capital-path gaps FIXED** (both, fail-safe verified): (1) cell-scoped arming eligibility + safe version-scope fallback (only when attribution-confirmed — widens PROVEN cells, never UNPROVEN); (2) `lot_size` rejection now LOUD (`arm_opened_nothing`), no silent no-op. **Follow-up surfaced:** funder writes forward-evidence version-only → re-key per-BRUT-cell to drop the fallback (larger, deferred). | [#471](https://github.com/monounsaturated/cosmu/pull/471) | ✅ done |
| **Polymarket Σ(YES)<$1 structural-arb** → **KILL** (58/150 liquid head scanned; 19 gross sub-$1 sets, 0 survive: 16 dust-quoted long-tail legs <$50 depth = unfillable mirage, 8 non-exhaustive binaries can pay $0). Where liquid+trustworthy, the vig removed the edge. No live test. | [#477](https://github.com/monounsaturated/cosmu/pull/477) | ✅ done |
| Cross-PR composition / merge-order review → **SAFE to merge sequentially, ZERO textual conflicts, no semantic collisions** (`git merge-tree`-verified). Only ordering: #463 & #466 after #458; #473 after #468 (stacked); shared files (loop.py, finder.py) auto-merge either order. Merge order ↓ in the Merge Guide. | `(isolated reviewer)` | ✅ done |
| #6 Voice-authority `event` specs → Gate — **wire PROVEN end-to-end, lane INERT in prod** (0 rows `social_authority`; voice tables absent). Unlock = populate panel + run `voices_pass` (operator-gated, next-chat — it's a prod mutation). | [#464](https://github.com/monounsaturated/cosmu/pull/464) | ✅ done |
| #12 Intraday order-flow / book-imbalance feasibility — **VERDICT: GO** (keyless PIT-honest historical aggTrades + direction-carrying `isBuyerMaker`; the new edge axis) | [#462](https://github.com/monounsaturated/cosmu/pull/462) | ✅ done |
| **H1 edge experiment** — aggressive-flow-imbalance fade (1m maker) → **KILL** (0/7; gross ≤2bps eaten by turnover×fee). **BUT shuffle-null confirms a REAL ~2bps order-flow signal EXISTS** (FIL p=0.04, OP p=0.075) — turnover-bound, NOT absent. Reusable keyless `data/intraday_aggtrades.py` fetcher shipped. | [#468](https://github.com/monounsaturated/cosmu/pull/468) | ✅ done |
| **H1b** — low-turnover order-flow fade → **KILL** (0/7; 0/7 beat shuffle-null). Turnover ↓7–14× but ~2bps/min × 6h = ~17–25bps gross < 30bps catalog maker RT. Closes the FADE family across cadences. **Near-miss:** at realistic ~14bps perp-maker, SEI/FIL turn marginally net-positive per-trade (still don't clear Gate) → perp-maker fee input may be over-conservative. | [#473](https://github.com/monounsaturated/cosmu/pull/473) | ✅ done |
| **H2** — book-depth imbalance (FOLLOW-the-wall, distinct from H1's fade) → **KILL** (0/7; mean gross **−0.53bps**, NO edge before any fee, indistinguishable from null). New keyless `data/intraday_bookdepth.py`. **CONCLUSION: reachable keyless intraday-microstructure axis EXHAUSTED for our maker/non-latency thesis** (flow + depth both killed) → next = cross-venue (needs 2nd source) or a NEW data axis. | [#476](https://github.com/monounsaturated/cosmu/pull/476) | ✅ done |
| **Next-data-axis deep research** → **recommendation: HL long-tail positioning** ($0, keyless, PIT-clean on-chain, desk-invisible; needs forward-hoard started ASAP). Cross-venue micro = confirmed dead-end; no paid vendor up-front. Report: `docs/reports/next-data-axis-recommendation-2026-06-28.md`. | ✅ done |
| **HL positioning hoard-logger** (axis #1) → **BUILT, ready to deploy** — keyless `/info` poller (20 long-tail perps) rides `alt_data`; NOT-applied migration; cron folded into hourly ingest (NOT deployed); 2 PIT features + disconfirmer-gated harness (refuses until ≥14d hoard); 16 tests; smoke-poll parses live HL. **⚠️ DEPLOY ASAP to start the hoard clock.** (curate per-account watchlist = top follow-up; no keyless leaderboard) | [#479](https://github.com/monounsaturated/cosmu/pull/479) | ✅ done |
| **Aave money-market stress** (axis #2) → **KILL** (no_signal): stress-z partial IC vs forward vol, residualizing trailing-vol+funding, ≈0 (BTC −0.046, ETH +0.015) — no forward-vol info, not even a vol proxy; clean nulls. (PIT caveat: block-timestamped subgraph needs a Graph API key; KILL holds on the recompute series.) | [#478](https://github.com/monounsaturated/cosmu/pull/478) | ✅ done |
| **Integration validation** — merge all 14 code branches into a scratch branch (merge-guide order) + run the FULL test suite (proves the batch works merged, not just individually) | `(isolated validator)` | 🔄 running |
| USDC liquidity-first base-currency decision module (trade=liquidity-wins, rest=USDC-default; propose-only, 3 new files, 18 tests) | [#469](https://github.com/monounsaturated/cosmu/pull/469) | ✅ done |
| #8 Inbox novelty-gate on wave-0 seeds (agent near-dup hard-skip · human near-dup kept+flagged; protects the FDR budget) — railway now solid w/ #460 | [#470](https://github.com/monounsaturated/cosmu/pull/470) | ✅ done |
| Pipeline integrity audit — **3 GAPs** (backtest CORRECT; **paper lane under-charges fees for Polymarket/IBKR** = the gate that funds; divergence-check write-only; USDC catalog `*USDT`-only). No leakage / no live mis-accounting (live reconciles to fills). | [#472](https://github.com/monounsaturated/cosmu/pull/472) | ✅ done |
| **Paper-lane fee-parity fix** — shared `effective_taker_bps`; paper now charges Polymarket per-category×(1−price) (~300bps@p0.40 vs ≈0) + IBKR per-share (==backtest); crypto byte-identical; TIGHTENS only; Gate untouched; 10/10 tests. **Closes the audit's headline finding.** | [#474](https://github.com/monounsaturated/cosmu/pull/474) | ✅ done |
| Pre-review batch 2 — newer code PRs (#467, #469, #470, #471, #474) → **all PASS, 0 blockers**; #471 & #474 money-path explicitly safe (cannot over-arm/move money/loosen fees; no rebate possible). All 14 code PRs now reviewed clean. | `(isolated reviewer)` | ✅ done |
| Backtest provenance + divergence surfacing — `CellProvenance` (source/interval/range/bars/holdout/fees) on result+log+event+API `GET /strategies/{id}/cell-provenance`; divergence now VISIBLE ("backtested on X → live Y" + corr/spread/fallback flag). Additive, Gate/numbers/money untouched, 14 tests. | [#475](https://github.com/monounsaturated/cosmu/pull/475) | ✅ done |

_(Dropped #4 token-unlock — memory shows N5 [#447](https://github.com/monounsaturated/cosmu/pull/447) already KILLED token-unlock drift; no new angle. M2 note: a 5-file batch pytest hung once under agent contention — agents bounded to own-file tests.)_

_(PR links + verdicts filled in as agents report.)_

---

## PART 3 — Roadmap (WAVE 1 synthesis — ranked, buildable, reversible)

| # | Title | Eff | Lev | First branch-step |
|---|-------|-----|-----|-------------------|
| 1 | **Placebo panel as standing cohort-rider** on the finder's real tape | M | 9 | hook `run_placebo_panel(finder market)`; assert `any_cleared==False`; per-survivor `compare_survivor_to_null`. Flag-gated. |
| 2 | **inbox-lint CLI** — validate-whole-directory manifest | M | 9 | `python -m cosmu.lab.inbox_lint`: validate_spec + derive_facets + pairwise structural_distance → manifest + dup-clusters. |
| 3 | **Leakage tripwire → profile_source verdict** | M | 8 | extend `ingest/profile_source.py` to call `audit_feature`; forward-shift fail = NO-GO. |
| 4 | **Token-unlock supply-shock drift event-study** (new axis) | M | 9 | keyless DefiLlama `/unlocks` → >5%-float unlocks → [-7d,+7d] returns by cap-tier vs random-date placebo. |
| 5 | **Schedule capital_guard watchdog + flip equity arm VENUE→alpaca** | M | 8 | capital_guard hook in scheduler tick + test auto-disarm on drawdown breach; config-driven VENUE. |
| 6 | **Voice-driven `event` specs → Gate** (unique edge lane) | M | 8 | generator → N typed specs entering on `authority_weighted_claim_signal` → batch-backtest → Gate. |
| 7 | **Standing leakage-audit over ALL wired alt features** | S | 7 | `python -m cosmu.research.leakage_audit_all` over feature_registry; exit non-zero on any forward-shift fail. |
| 8 | **Close inbox novelty hole** (wave-0 extra_seeds) | S | 8 | call `_novelty_ok` in the loop.py wave-0 seed path; agent near-dup rejected, human kept+flagged. |
| 9 | **UMA pre-settlement convergence study** (fix N1 data gap) | M | 8 | fetch UMA proposal event (`available_at`=proposal block) → offline study in-window CLOB vs return-to-$1 net fee. |
| 10 | **End-to-end live-arming dry-run harness** (testnet, synthetic matured TAA) | M | 7 | seeded pytest: paper-mature → eligible → armed → testnet order → guard disarm. Depends on #5. |
| 11 | **spec_digest + ticker-anonymization disconfirmer in finder** | S | 6 | pure `spec_digest(spec)` (feeds #2) + invoke `symbol_anonymization_null` as advisory finder field. |
| 12 | **Intraday order-flow / book-imbalance feasibility** (docs-only spike) | S | 6 | inventory keyless PIT-honest trade-tape/L2; 2-3 hypotheses + disconfirmers; go/no-go. |

**Build order (live):** WAVE 2 = #1, #2, #4, #6 + the two tripwires already running. WAVE 3 = #3/#7 (after leakage agent), #8, #5+#10 (safety/capital-path, careful). WAVE 4 = #9, #11, #12 + wiring dormant instruments.

**Deliberately NOT building:** IBKR adapter (Alpaca already covers equity live) · frontend polish (Claude Code is the front end) · voice-panel backfill (until #6 proves the wire non-inert) · new crypto price/calendar/attention hypotheses (0/96 exhausted) · anything touching a Gate constant · any merge or prod/data mutation.

---

## PART 4 — QA checklist (for when you're back)

**Already-merged (prod) — spot-check:** `/mind` voice scoreboard renders · strategy sheet shows holdout/OOS + provenance · Modal v23 healthy (`modal app history`) · Gate constants byte-identical.

**Autonomous-run branches — adversarial PRE-REVIEW (2 isolated reviewers, every test suite re-run):**
- ✅ **All 9 shipped PRs (#458–#466) = PASS, ZERO blockers.** No PR touches `master/scorer.py` / `master/cohort.py` scoring math (Gate constants byte-identical); per-combo BRUT preserved; fully reversible; money-path safe.
- 🔒 **#465 (money-path) explicit safety verdict:** cannot move money (reduce-only; SIM until you arm), cannot arm / flip the live interlock, cannot crash the tick (try/except-wrapped). Strictly *adds* protection.
- 📝 **Optional follow-ups (none block merge):** (a) ack #465's default-ON auto-guard; (b) #466's conservative leak-thresholds may degrade a *weak* real leak to WARN (re-run as history deepens); (c) strip the "DO NOT MERGE — POC" line on actual merge; (d) cosmetic: move #461's `survivor_dsrs` comprehension inside the OFF-gate.
- ✅ **Batch 2 reviewed (all PASS, 0 blockers):** #467, #469, #470, #471, #474 — money-path #471/#474 explicitly safe (cannot over-arm / move money / loosen a fee; no rebate possible). **All 14 code PRs pre-reviewed clean.** (#475 provenance additive/display-only; HL-logger + Aave launched after this review → review on finalize.)

### ✅ MERGE GUIDE — whole batch SAFE to merge sequentially (`git merge-tree`-verified: zero textual conflicts, no semantic collisions)
Recommended order (the only constraints are *dependencies*, not conflicts):
1. **#458** leakage_tripwire (new module — unblocks #463 + #466)
2. **#469** base_currency · **#460** inbox_lint (new files, additive)
3. **#463** profile_source — *after #458*
4. **#459** then **#470** (both `evolution/loop.py` — disjoint hunks, either order, back-to-back)
5. **#461** then **#475** (both `lab/finder.py` — disjoint hunks, back-to-back)
6. **Money-path — merge with care, REDEPLOY MODAL after:** #474 (fee parity) · #471 (capital-path gaps) · #465 (capital-guard schedule). Independent of each other; ack #465's default-ON guard.
7. **Experiments / docs (any order):** #462, #464, #466 *(after #458)*, #467, #472, #476, #477.
8. **#468 then #473** (stacked — #473 must follow #468).
- The two shared files (`evolution/loop.py`, `lab/finder.py`) auto-merge either order; no pair needs a manual rebase. Strip each PR's "DO NOT MERGE — POC" line on merge.

**Deferred follow-ups (documented, none block merge):** re-key the funder per-BRUT-cell to drop #471's temporary fallback · high-priced-ETF lot_size sizing (fractional shares) · DRY-point `research/gate.py`/`build_cost_context` at the shared `effective_taker_bps` · re-run leakage-audit as feature history deepens (37 SKIP) · perp-maker fee input may be over-conservative (30bps catalog vs ~14bps real).

**Housekeeping you may want:** delete ~106 squash-merged remote branches (verified safe); leave `wip/snapshot-*` + this run's branch.

---

_Last updated: edge probes concluded (intraday + Polymarket KILL); next-axis = HL long-tail positioning (logger building); all code PRs reviewed clean + merge guide written._
