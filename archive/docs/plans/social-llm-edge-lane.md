# Plan — The Social / LLM / Niche edge-research lane (priority 1)

> Status: **PLAN, ready to build.** This is the priority-1 lane for COSMU's next edge campaign. It
> ships propose-only on top of the existing **deterministic Gate** — which is **LOCKED and untouched**.
> The LLM and the social/unstructured ingest **propose**; the Gate alone funds.
>
> Anchors this plan is bound to (do not re-litigate):
> [[edge_thesis]] · [[vibe_coding_leakage_risk]] · [[llm_research_lane]] · `docs/epics/agentic-lane.md`
> (the Gate-B design, operator-validated 2026-06-17) · `docs/epics/realtime-data-lane.md`.

---

## 0. Why this lane, and why now (the verified premise)

**The numeric / free-data edge is empirically exhausted.** Six rigorous, pre-registered sweeps were run
through the **unchanged** Gate and every one is a *powered* FAIL, not an under-powered abstention:

| Sweep | Verdict | Evidence |
|---|---|---|
| Spot funding-**carry** | FALSIFIED (powered) | best deflated-Sharpe 0.43 vs 0.95 bar; cost not the killer; the funding cap (~+2.5%/yr gross) is structural (`docs/reports/phase0-carry-verdict.md`). |
| Funding-as-**crowding signal** (5-spec cohort) | FAIL | best dSR 0.71, PBO≤0.27 — not overfit, no edge (`phase0-funding-crowding-verdict.md`). |
| **Cross-market transfer** | FAIL (STOP) | 0/48 grid variants; every holdout dSR negative (`phase0-non-price-data-blocked-verdict.md`). |
| **Social-signal** cohort (LunarCrush, 186k PIT pts) | FAIL | 0 survived cohort BH-FDR; killed per-candidate before FDR even binds (`phase0-social-signal-verdict.md`). |
| **Astrology** (non-causal control) | 0/4092 IC | confirms the harness rejects spurious periodic signals (`docs/research/astro_vs_markets.md`). |
| **Crypto cross-sectional momentum** | RETIRED | long-only = uncancelled beta (dSR 0.009); L/S-neutral 0.25 ≪ 0.95, uneconomic after fees. |

The lesson is **not** "the machine is broken" — it is "**liquid + numeric markets are efficient/arbitraged**,
and a 7th numeric sweep on the same surfaces is a waste." The honest read (`strategy_research_direction`):
a FAIL on the *most-liquid, most-arbitraged majors* means "no edge **in liquid majors**," which is expected
and points straight at the pivot rule: **smaller/niche markets + unpriced data + reasoning**.

**The edge thesis ([[edge_thesis]]) says exactly where to go instead.** A solo+bots fund wins by being what
a big fund *can't* be:

1. Speed + no regulation + no LPs — ship/iterate fast, mistakes are cheap.
2. **Weak signals + small/illiquid markets** below a big fund's capacity (small-cap crypto, Polymarket,
   social catalysts) — their size is their constraint; our smallness is freedom.
3. **Many RISKY AUTONOMOUS agents, VC-style** — 1 win pays for 99 losses, diversified across many.
4. **Cheap/free SOCIAL + alt data** — operator-assisted scraping (Chrome/desktop), under-mined vs price.
5. **Frontier IP / smart code** — not best-practice consumer-investing.

This lane is the direct expression of edges **2, 3, 4**. It does **not** out-Wall-Street Wall Street with a
faster quant; it mines text and small markets the giants ignore.

---

## 1. The lane in one diagram

```
 SOCIAL / UNSTRUCTURED SOURCES                 LLM REASONING                 DETERMINISTIC DISPOSAL (LOCKED)
 ─────────────────────────────                ────────────────              ────────────────────────────────
 X/Grok timelines (pre-reg handles)  ┐
 Reddit / forums                     │                                      ┌── kind='quant' spec
 News / RSS / press                  ├──►  ingest → typed,  ──► LLM turns ──►│   → Gate A (DSR/PBO/BH-FDR,
 Polymarket events + odds            │     PIT-stamped       low-confidence  │      backtested, LOCKED)
 SEC EDGAR / OSINT (jet, Form-4)     │     SourceFeatures    findings into   │
 On-chain flows (mid-cap)            ┘     on the read-only  TYPED specs ────►├── kind='llm' AgentSpec
                                            research bus                      │   → Gate B (forward/anonymized,
                       ▲                          │                          │      NO naive replay, human-launch)
                       │                          ▼                          │
              LEAKAGE TRIPWIRE              PROPOSE-ONLY                      └── PAPER (= forward-test) → human
        (feature-side PIT + shuffle null,   the LLM never                        clicks LIVE per strategy
         ticker-anonymization)              scores/sizes/funds
```

Two non-negotiable invariants carried from [[vibe_coding_leakage_risk]] and [[llm_research_lane]]:

- **The LLM is permanently OUT of the numeric price-reasoning loop.** It reasons over *text/events* and
  *proposes structure*; it never scores in-window prices, never ranks, never sizes, never funds. (The
  Sarkar & Vafa "Memorization Problem": any LLM scoring in-window prices is leakage by construction.)
- **The Gate is the only thing that funds.** Volume of proposals cannot manufacture a winner — every
  candidate is a registered trial, deflated against the running count (deflated Sharpe + cohort BH-FDR).

---

## 2. The two strategy MODELS (this lane uses both, per `agentic-lane.md`)

COSMU already has the design for **two models sharing one lifecycle/status/caps/UI** (operator-validated):

| | **Quant** (`kind='quant'`) | **LLM** (`kind='llm'`) |
|---|---|---|
| Artifact | `StrategySpec` (typed rules, `param_space`) | `AgentSpec` (a reasoning loop → typed `Decision`) |
| Validated by | **Gate A** — DSR/PBO/BH-FDR, **backtested**, LOCKED | **Gate B** — forward/anonymized, **no backtest** (leaky), score+proofs |
| When this lane uses it | a social signal that becomes a *numeric, PIT-joinable feature* (e.g. social-volume, insider-buy ratio, Polymarket odds) → author a quant spec, let Gate A backtest it | a thesis that is *unstructured/probabilistic/fast-moving* (a journalist's call, a rumour, an event narrative) that **cannot** be backtested → AgentSpec, forward-prove only |

**Routing rule:** if the social finding can be reduced to a point-in-time numeric series with a clean
`available_at`, it is a **quant** spec and goes through the backtested Gate A (cheaper, stronger evidence).
Only when it genuinely cannot be backtested without leakage does it become an **LLM** AgentSpec on Gate B.
Most of the early wins should be **quant** — Gate A is the harder, more trustworthy test, and the social
sources below (insider-buy ratio, social-volume, Polymarket odds) are all numeric-reducible.

> The `kind` discriminator, the `AgentSpec`/`Decision` types, `open_agent_strategy(kind='llm')`, and the
> NL→AgentSpec authoring CLI **already exist** (`polymarket_llm_lane_2026-06-18`). What is *not* yet wired:
> a paper track for `kind='llm'` (the loop funds only `kind='quant'` today), and the autonomous observe-loop
> (Gate B's forward harness). Those are the build items in §5, not greenfield.

---

## 3. The open tension, RESOLVED — sequence social/LLM **before** a new paid data axis

Two recent directions compete for the next sprint:

- **(a) Build the social / LLM / niche lane** (this document) — ingest cheap unstructured data + reason
  over it + small markets.
- **(b) Buy a new PAID data axis** — a positioning/flow vendor, or a non-HFT intraday market-data
  subscription (the `realtime-data-lane` epic gestures at this).

### Recommendation: **(a) first, (b) only on a specific trigger.** Sequence and rationale:

**Phase 1 — social/LLM/niche, $0-to-cheap (do this now).** Three reasons it wins the ordering:

1. **Cost & runway.** Compute is effectively free (new Modal accounts), and the LLM authoring/research half
   runs on the **flat Claude Code sub** ($0 marginal — [[llm_research_lane]], `cost_architecture`). Runway,
   not compute, is the binding constraint. A paid data vendor is a *recurring* cash commitment **before**
   we have a single forward-confirmed edge to justify it. Spending on (b) first is buying a bigger haystack
   when we haven't proven we can find a needle in the free one.
2. **Edge-thesis fit.** (a) **is** the thesis (edges 2/3/4). A positioning vendor is closer to (b) =
   "out-Wall-Street Wall Street with better-priced data" — the giants already buy the *best* positioning
   data; we will never win that axis on data quality. Our advantage is **cheap text the giants don't bother
   with** + **small markets below their capacity**, not premium structured feeds.
3. **Build effort & evidence.** Most of (a) is *wiring*, not greenfield: the read-only research bus, the
   `add-data-source` skill, the alt-join PIT path, the AgentSpec types, and the Polymarket adapter all
   exist. (a) produces *backtestable* (Gate A) evidence quickly; (b) is a procurement + integration +
   trust-audit cycle that delivers no evidence until it's done.

**Phase 2 — paid data axis, gated on a trigger.** Buy a paid axis **only when** one of these fires:
   - a Phase-1 **forward survivor exists** and a specific paid feed would *measurably deepen or extend* it
     (e.g. the survivor rides a free proxy and the vendor offers the real series at lower lag); **or**
   - a Phase-1 thesis is **DATA-BLOCKED for free** (no PIT history endpoint) *and* the
     `profile-source`/`add-data-source` audit says the paid feed is PIT-honest and revision-safe; **or**
   - the **MM/execution lane** (Polymarket market-making, the one *proven* money lane per the
     `polymarket-master-plan`) needs an order-book/queue feed to size capacity.

   The first paid candidate, when triggered, is **non-HFT intraday Polymarket order-book / per-market
   hourly odds** (not a positioning vendor) — because it directly unblocks the niche-market lane we already
   have evidence for, rather than entering the crowded structured-data game.

**Net:** `(a) now, on the flat sub + free data → produce a forward survivor → THEN (b) buys depth for it.`
A paid axis bought before a survivor is spend without a thesis; bought after, it's leverage on a proven one.

---

## 4. The human strategy-creation loop, encoded for Claude Code

The operator's manual research process is a repeatable loop. Each step maps to an **existing skill**, so
Claude Code (flat sub) can drive it end-to-end. The loop is **propose-only up to the Gate**; the Gate
disposes; the human clicks LIVE.

```
   research ──► hypothesis + disconfirmer ──► spec ──► backtest ──► GATE ──► paper(forward) ──► [human] LIVE
      │                  │                      │         │           │           │                  │
   deep-research     scan-signals          create-       run-gate   (Gate A:    loop opens a     human-only
   (sub-agent)       /strategize           strategy /    /          deterministic,  paper track    launch;
   + the read-only   (each hypothesis      dump-idea     research-   LOCKED)      = forward-test    the Gate is
   research bus      MUST carry a          → inbox/      to-cohort                (paper ≡ forward, eligibility,
   (lab/tools/)      DISCONFIRMER)         *.json        (batch)                  one step)         human is launch
```

| Step | What happens | Skill(s) | Where it plugs in |
|---|---|---|---|
| **1. Research** | Fan out web + tweets + the *already-ingested* signals (funding, F&G, macro, on-chain, social, OSINT, Polymarket odds — $0, PIT-honest). | `deep-research` (in an Agent sub-agent, `run_in_background`), feeding `research-to-cohort` | The research bus is `cosmu/lab/tools/` — **read/propose-only**, execution is never on the bus. |
| **2. Hypothesis + disconfirmer** | Turn findings into `{signal, asset/class, direction, economic WHY, DISCONFIRMER}`. **A hypothesis you can't kill isn't a hypothesis.** Prefer *leading / cross-asset* signals (prediction-market odds → crypto; funding → equity) over same-asset price patterns. | `scan-signals` (unbiased sweep) → `strategize` (the one front door / router) | `scan-signals` proposes on the bus; `strategize`'s `classify_intent` routes `vibe`/`batch`/`pine`/`url`/`scan`/`evolve`. |
| **3. Spec** | Each thesis becomes a typed `StrategySpec` (`kind='quant'`) **or** `AgentSpec` (`kind='llm'`). Every spec must clear `validate_spec`: non-empty `rationale`, ≥1 entry, **no magic numbers** (thresholds are `ParamRef`s into `param_space`), registry features only, `universe.min_instruments ≥ 5`. | `create-strategy` (typed author) / `dump-idea` (loose NL → inbox) / `import-pine` (Pine → spec) | Writes `apps/engine/strategies/inbox/*.json`; records a `strategize_authored` event. |
| **4. Backtest** | Batch-screen the inbox through the honest cohort gate on the **alt-joined** feature space (not the exhausted bar-TA grid). Modal fan-out preferred (`pnpm modal:sweep`); local `matrix_search --sweep` for small N. | `research-to-cohort` (orchestrates author→backtest→Gate→report) | Verdicts land in `gate_verdicts` / `backtests`. **`kind='llm'` specs skip this** (backtest is leaky) → straight to forward. |
| **5. Gate** | The deterministic FDR Gate disposes. Gate A: deflated-Sharpe ≥ 0.95, CSCV-PBO < 0.50, ≥60% positive folds, holdout dSR > 0, maxDD ≤ 0.25, ≥30 trades, **and** survives cohort BH-FDR at q=0.10. A candidate that clears `score()` but fails FDR is **demoted** — that is the machine working. | `run-gate` (single/cross-asset ablation) | `cosmu/master/cohort.py:promote_cohort` + `fdr.py`. **LOCKED — never tune to manufacture a survivor.** |
| **6. Paper (= forward-test)** | A survivor opens an honest **paper track** (born with no backtest-OOS seed — paper ≡ forward, one step). This is the scan-immune gate. For `kind='llm'`, this is **Gate B**: forward/anonymized event-study + cross-verification, scored not pass/fail, the human reads the proofs. | (lifecycle; loop opens the track) — see `agentic-lane.md` §5 for Gate B | `master/tracks.open_paper_track`. **Gate B forward harness for `kind='llm'` is a build item (§5).** |
| **7. Live** | **Human-only.** The Gate is eligibility; a person clicks launch per strategy. Live is OFF by default; a deterministic, agent-unmodifiable execution envelope (hardcoded caps/kill-switch) sits in front of every venue. | (human action) | `live_toggle` / `live_caps`; `step_tracks` → exec adapters. |

**One command for the whole loop:** `research-to-cohort` already chains 1→5 ("from a theme to a Gate
verdict"). `strategize` is the single front door for ad-hoc intake of any input shape. For many themes at
once, fan out one Agent per theme (`isolation: "worktree"`, `run_in_background: true`), each authoring to
inbox on its own branch, then one Modal sweep over the merged inbox (`fan-out` runs the merge train). **One
branch per agent; never two agents in one working tree.**

### The leakage tripwire — the guard that wraps every step (highest priority)

The Gate validates **edge after costs**; it does **not** verify the **feature pipeline** that fed it was
point-in-time honest ([[vibe_coding_leakage_risk]]). A leakage bug upstream of the Gate produces a survivor
that is genuinely real on paper and zero/negative live — and the Gate cannot see it. This lane *amplifies*
that risk because the LLM is authoring research code and ingesting untrusted scraped text. The tripwire is
therefore a **standing guard on every social source**, not an afterthought:

1. **Feature-side point-in-time audit** — for every source+join, assert no value is used before its
   `available_at`. Scraped social/news is stamped `available_at = scrape time`, **never** backdated to post
   time; backfills are honest *event-study* inputs (measure the market *after* the event), never PIT trading
   features. Run `profile-source` (the data-trust audit: coverage · gaps · staleness · look-ahead · PIT-lag
   · revision safety → GO/REVIEW/NO-GO) on every new feed **before** it becomes a feature.
2. **Shuffle/permutation null + ticker-anonymization** as standard disconfirmers — a real signal's IC
   collapses under a time-shuffle (BlindTrade: IC 0.015 → 0.0004) and under ticker-anonymization. Any
   "signal" that survives a shuffle is leakage, not edge.
3. **Untrusted-text neutralization** — strip/neutralize instruction-like content from scraped
   X/Reddit/SEC/news text **before any agent sees it** (indirect prompt-injection defense).
4. **LLM out of the numeric loop** (codified) — text/events only; never scores in-window prices.
5. **Live-vs-backtest divergence circuit-breaker** on every funded track — a leaked survivor looks real
   until it trades; the breaker catches it the moment it does.

> Cross-reference: the known Polymarket lane has a *baked-in 1-bucket look-ahead* (`available_at == ts` in
> both fetch paths) and no authoritative resolved-outcome (`edge-sprint-plan` claim #3). The unlock there is
> the **PIT-lag fix + resolution join**, exactly the tripwire's job — not more ingestion. Treat it as the
> reference example of why this guard is load-bearing.

---

## 5. Build items (ranked; mostly wiring, not greenfield)

The lane is ~80% built. Ranked by leverage / lowest effort first:

1. **Leakage tripwire as a standing CI check (P0).** Turn the `profile-source` audit + the shuffle-null +
   ticker-anonymization disconfirmers into an **automated gate-adjacent check** that every new social source
   must pass before it can become a feature. This is the single highest-stakes item (Gate-invisible failure
   mode). *Effort: medium. Greenfield-ish (the audit exists as a skill; the standing/automated wrapper does
   not).*
2. **Social-source ingest, one feed at a time (P1).** Use `add-data-source` to wire each: X/Grok-LiveSearch
   timelines (pre-registered handle list, complete timelines — no pick-the-viral-tweet survivorship), then
   Reddit/news/RSS, each as a typed PIT `SourceFeature`. *Effort: small per feed (the pattern + the alt-join
   exist). Start with one, prove the loop, then widen.*
3. **Polymarket per-market hourly odds + authoritative resolution (P1).** The favorite-bias edge is real
   *cross-market* (+7–13% in the probe) but is ~1 trade/market on daily bars → the per-cell min-trades Gate
   correctly refuses it. The unlock is **hourly odds** (trade frequency) + **UMA `payoutNumerators`**
   (authoritative outcome, kills the leakage caveat) + a **panel/cross-market Gate evaluation** (each market
   = 1 obs, clustered SE, held-out markets). *Effort: medium (the one real data dependency; see the
   `polymarket-master-plan` E1–E5 experiments — build on Modal, sandbox-first).*
4. **Gate B forward harness + `kind='llm'` paper track (P2).** Today the loop funds only `kind='quant'`.
   Wire a paper track for `kind='llm'` and the forward/anonymized event-study evaluator (Gate B = score +
   proofs, human reads). Until then, **Claude Code IS the reasoning loop** — author an AgentSpec, emit
   Decisions on a schedule. *Effort: medium. Defer until item 2/3 produce a thesis that genuinely can't be
   backtested.*

**Out of scope / explicitly NOT to do:** re-run any exhausted surface (astro, spot funding-carry, crypto
xsec, regime) tweaked until it clears — that contaminates the holdout; loosen any Gate threshold; let an LLM
score, rank, size, or fund; backdate scraped-text `available_at`; or buy a paid positioning vendor before a
forward survivor exists (§3).

---

## 6. Success criterion

The POC for this lane is **one strategy that survives the honest Gate and then survives forward (paper)**,
sourced from cheap social/unstructured data or a niche market — net of every cost. Not a dashboard, not
breadth of sources, not "we built it." One forward-confirmed, net-of-fees edge from the axis the giants
ignore. That single survivor is what unlocks the Phase-2 paid-data spend (§3).

---

## 7. References

- `docs/epics/agentic-lane.md` — the two-model (Quant/LLM) Gate-B design, operator-validated.
- `docs/epics/realtime-data-lane.md` — the stream-shaped reaction lane + the Chrome social-collection lane.
- `docs/reports/phase0-*.md` — the powered FAILs that exhaust the numeric/free-data surfaces.
- `docs/research/idea_intake_2026-06-21.md` + the Polymarket research handoff — the niche-market evidence.
- Skills: `research-to-cohort`, `scan-signals`, `strategize`, `create-strategy`, `dump-idea`,
  `add-data-source`, `profile-source`, `run-gate`, `evolve-strategy`, `fan-out`, `deep-research`.
- Memory anchors: [[edge_thesis]], [[vibe_coding_leakage_risk]], [[llm_research_lane]],
  [[strategy_research_direction]], [[polymarket_llm_lane_2026-06-18]].
