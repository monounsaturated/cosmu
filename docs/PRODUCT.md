# Cosmu — Product Definition (the web surfaces)

> Grounds the web app in product, from first principles. The contract for *what ships and why*.
> Anchored to `VISION.md` §1 (what the user experiences) and §11 (UX/UI). If this doc and the
> code disagree, fix one of them on purpose.

**The rule that governs every page:** *if a page doesn't help you decide or earn, it doesn't ship.*
Heavy/rare operations (authoring, migrations, research spelunking) live in Claude Code + `docs/`,
never as new pages. Customization is config, not clutter.

**Canonical shipped nav** (source of truth: `apps/web/components/nav/app-nav.tsx` — desktop icon-rail
sidebar + mobile bottom-tab bar). Eight primary surfaces + three secondary under "More":

| | Route | Label | Decision it serves |
|---|---|---|---|
| 1 | `/` | **Overview** | Are we making money / is the machine healthy? |
| 2 | `/lab` | **Lab** | Idea → spec → verdict (authoring + screening) |
| 3 | `/verdicts` | **Theories** | Every theory tested + its honest Gate verdict |
| 4 | `/strategies` | **Strategies** | Backtest · Simulation · Live (the faceted leaderboard + detail) |
| 5 | `/explorer` | **Explorer** | Pick · chart · compare |
| 6 | `/mind` | **Mind** | What the agent knows, thinks, and has learned (the committee) |
| 7 | `/costs` | **Costs** | What is it costing? |
| 8 | `/console` | **Console** | Decide · steer · arm |
| More | `/live` | **Live** (gated) | Positions · caps (dimmed until armed) |
| More | `/settings` | **Settings** | Keys · universe · data |
| More | `/commands` | **Commands** | Run from Claude Code |

There is **no `/paper` "wallet" route** — the Overview is a read-out (Σ of standalone tracks), not a pooled
wallet. Strategy detail lives under `/strategies/{id}` (and `/strategy/{id}`), not as a separate nav item.

---

## 1. Persona — the operator

**You are a one-person fund.** Not a day-trader, not an engineer babysitting a script. You allocate
capital and carry the P&L; the machine does the research, backtesting, and 24/7 forward-testing. Your
scarce resource is **attention** and your only privileged action is **moving real money** (flip live,
raise caps). Everything else runs unattended and pings you when it needs a decision.

What you actually do in a session, in order of frequency:
1. **Glance** — are we making money, net of every cost, and is the machine healthy? *(Dashboard)*
2. **Triage** — clear the inbox of decisions only a human may make. *(Console)*
3. **Judge** — which strategies are winning, on what edge, and is it real? *(Strategies → detail)*
4. **Understand** — what does the committee believe right now, and why? *(Mind)*

You are needed to move real money. The deterministic master owns the scorer and the money; no LLM and
no UI ever fires a live order — the UI only *reports* and *proposes* (VISION §0).

---

## 2. The core surfaces, and the single decision each serves

(See the canonical nav table above for the full shipped route list. The epics below detail the surfaces
that carry the primary decisions; the others — Lab, Theories, Explorer, Costs, Settings, Commands — are
authoring/inspection surfaces that compose the same endpoints.)

| Surface | The one decision it serves | Source of truth |
|---|---|---|
| **Overview** (`/`) | *Are we making money — should I keep the machine running / spending as is?* | `/overview`, `/costs`, `/mind`, `/intelligence`, `/autonomy/status` |
| **Strategies** (`/strategies`, Leaderboard) | *Which strategies deserve my attention / capital, on what edge?* | `/leaderboard` (faceted, real fields) |
| **Strategy detail** (`/strategies/{id}`) | *Is this one strategy's edge real and live-ready?* | `/strategies/{id}` |
| **Console** (`/console`) | *What needs my call right now, and how do I steer / arm?* | `/recommendations`, `/console/command`, `/toggle/live`, `/autonomy/*` |
| **Mind** (`/mind`, monitoring) | *What does the committee believe, what does it know, what has it learned?* | `/mind`, `/scores`, `/mind/source-trust` |

Every number on every surface carries a **money-state** (SIM / LIVE) and an **honest empty/offline state**:
when the engine is unreachable we say so; when it is connected but empty we say *that*. **Synthetic numbers
never ship** — the product has no demo money state.

---

## 3. Epics → user stories → acceptance

### Epic A — Dashboard: the fund read-out
*Goal: in one glance, know if we're making money and if the machine is healthy.*

- **A1.** *As the operator, I see aggregate equity (Σ of all standalone tracks, SIM + live) so I know the book's shape.*
  - **Accept:** equity curve renders from `/overview.equity_curve`; labeled "Σ of standalone tracks — a read-out, not a pooled wallet"; honest empty when no tracks.
- **A2.** *I see P&L net of all costs so the number isn't a vanity gross figure.*
  - **Accept:** headline P&L = `/overview.pnl_net` (already net of fees/slippage/funding); the Costs strip nets LLM/infra/data opex; tooltip names what's included.
- **A3.** *I see an opex-vs-alpha gauge so I know if R&D spend is justified by yield.*
  - **Accept:** gauge reads `/overview.opex_vs_alpha`; green when alpha ≫ opex, warn when opex approaches/exceeds alpha; links to the cost breakdown.
- **A4.** *I see a data-freshness + Mind-consensus banner so I trust (or distrust) the read.*
  - **Accept:** banner shows count of fresh vs stale sources (`/intelligence.data_freshness`) and the committee's current consensus + conviction (`/mind`); stale data is flagged, not hidden.
- **A5.** *I can flip the global live toggle (off by default) here.*
  - **Accept:** toggle posts `/toggle/live`; two-click confirm; defaults OFF; never arms without an explicit confirm and an engine-side gate pass.

### Epic B — Strategies: the unified, faceted leaderboard
*Goal: rank every strategy-version honestly and slice the population by how it makes money.*

- **B1.** *I see every version on its own standalone track (default $1,000, `sim_track_capital`), ranked by risk-adjusted % (deflated OOS Sharpe), with net %.*
  - **Accept:** rows from `/leaderboard`, default sort = `deflated_sharpe` desc; net % shown prominently; no pooled-wallet framing.
- **B2.** *I filter by signal-family as the primary lens — {Social · News/Events · Math/Price · Macro/Positioning · On-chain/Flow}.*
  - **Accept:** `signal_family` is **derived from the features the spec references** (`cosmu/strategy/taxonomy.py`), never hand-tagged; selecting a family filters the table and the counts update.
- **B3.** *I refine with orthogonal facets: asset class · venue · timeframe · status · origin · edge-type.*
  - **Accept:** each facet reads a **real field** on the leaderboard row (`asset_class`, `venue`, `timeframe`, `status`, `origin`, `edge_type`); facets compose (AND across facets, OR within a facet); active filters are visible and clearable.
- **B4.** *Status reflects the lifecycle: lab → screened → forward → live → killed.*
  - **Accept:** the `status` facet maps engine statuses to the lifecycle stages; counts per stage are honest (empty stages shown, not hidden).
- **B5.** *A row tells me its edge at a glance and links to detail.*
  - **Accept:** each row shows its signal-family + edge-type chips and the referenced features; click → `/strategy/{id}`.

### Epic C — Strategy detail: is this edge real?
*Goal: enough evidence to decide whether one strategy deserves live capital.*

- **C1.** *I see backtest + SIM equity, the trade blotter with fees/slippage, and OOS-vs-holdout evidence.*
  - **Accept:** sim equity from real fills; per-fold OOS bars; the seen-once holdout; fee column on every fill — all from `/strategies/{id}`, honest empty throughout.
- **C2.** *I read the authored spec (named features, fitted params, no magic numbers) and the agent's notes.*
  - **Accept:** typed spec view + compiled code + agent post-mortem; the strategy's derived facets (family, edge-type) are shown.
- **C3.** *I can launch it live only when it has passed the gate.*
  - **Accept:** the launch-live control appears only when a backtest `passed_gates`; arming is a separate, explicit two-click confirm.

### Epic D — Console: the control surface (the star)
*Goal: do the only things a human must — decide, steer, and arm.*

- **D1.** *I work a recommendation/approval inbox — the machine proposes, I dispose.*
  - **Accept:** open `/recommendations` with Approve/Dismiss (`/recommendations/{id}/approve|dismiss`); approving never itself moves money; optimistic UI; honest empty.
- **D2.** *I steer in plain language; money-adjacent changes are recorded but need approval.*
  - **Accept:** `/console/command` returns applied / recorded / approval-required; the deterministic gate still disposes.
- **D3.** *I flip the global live toggle and see what the autonomous loop is doing.*
  - **Accept:** the same `/toggle/live` two-click control; autonomy status (running/paused, last/next, cycle counts) from `/autonomy/status` with pause/resume/run-a-cycle.

### Epic E — Mind: the 24/7 committee
*Goal: an auditable, honest read of what the machine believes and knows.*

- **E1.** *I see 6 analyst pillars + ML-survival + Memory, each with a score, a one-line rationale, and abstain-when-no-data, debating a consensus.*
  - **Accept:** stances from `/mind` (market pillars + process pillars); abstaining pillars render as abstaining, never as a forced lean; the consensus card shows conviction, panel agreement, contested flag, bull/bear cases. **The railguard is shown: the Mind reasons; it never funds.**
- **E2.** *Scores are first-class: index scores (e.g. reg_risk, risk_on_off) + per-source LLM "what this means" reviews, with freshness.*
  - **Accept:** the scores cockpit renders `/scores` composite + per-category index + per-source reviews; key-gated sources without a key are greyed (not faked); PIT history renders as a sparkline where the engine returns it.
- **E3.** *I see source trust (freshness × realized gate contribution) and recent scored news/events.*
  - **Accept:** `/mind/source-trust` and `/mind/news-intel`; sources with no data read "no data", never fabricated.

---

## 4. Cross-cutting invariants (apply to every surface)

- **Honesty over completeness.** Empty states say *why* they're empty (offline vs no-data-yet). Never a synthetic curve, row, or score (VISION §0, `apps/web/app/data.ts`).
- **Contracts, not hand-typing.** Every field is consumed from `@cosmu/contracts-ts`, generated from the engine's Pydantic → OpenAPI. New UI fields are added on the engine model first (VISION §17 "Schema drift").
- **Derived, not tagged.** A strategy's signal-family and edge-type are *computed* from the features its spec references — there is no manual taxonomy to drift (`cosmu/strategy/taxonomy.py`).
- **The UI never moves money.** It reports and proposes; arming live is an explicit two-click confirm and the deterministic gate is the only thing that lets capital flow.
- **Lean, finance-grade, dark.** shadcn-style primitives + Tremor-equivalent charts (Recharts) + dense tables. Desktop-first, mobile bottom-nav. No page exists that doesn't help you decide or earn.

---

## 5. What is explicitly NOT a surface

Authoring strategies, migrations, deep research, data backfills, and source onboarding are **Claude Code +
`docs/` skills**, not app pages (VISION §1). The app is a clean *monitoring + steering* surface. The lifecycle
(lab → forward → live) is a **filter inside Strategies**, not a set of tabs. Costs and Scores are **folded into**
Dashboard and Mind respectively — they inform a decision there; they are not standalone destinations.
