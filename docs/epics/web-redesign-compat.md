# Web redesign — compatibility audit: `cosmu-uf-1` mockup vs the current engine/app

> Written 2026-06-12 for the implementation session. Verdict up front: **~90 % of the design
> binds to contracts that already exist.** Four real gaps, all small or already in BACKLOG.
> Nothing in the design contradicts the invariants (no synthetic display, gate out of LLM path,
> signal/fill separation, killed visible).

## 1. What binds directly to existing endpoints

| Mockup surface | Existing source | Note |
|---|---|---|
| Strategies table (stage, days, P&L %, DSR, PBO, OOS, venue, lifecycle, kill reasons) | `GET /leaderboard` (`LeaderboardRow`: status, `paper_age_days`, `paper_return_pct`, `divergence_status`, deflated_sharpe, pbo, net_pct, venue, kill data) | rename wave already aligned field names to `paper_*` |
| Drift column / sheet banner (plus-1) | `LeaderboardRow.divergence_status` ("tracking"/"diverging"/"insufficient") — already computed by `master/divergence.py` | zero backend work |
| Launch readiness (plus-2) | `paper_age_days` + `PAPER_MIN_DAYS` + net>0 (`master/paper_maturity.py`), launch via `POST /live/activate` (budget/caps/confirm) | zero backend work |
| Edge-intel blocks panel (plus-3) | `GET /blocks` + `GET /blocks/version/{id}` (built this branch) | needs the strategy_blocks migration applied |
| Sheet: gate chips, spec, notes | `GET /strategy/{id}` (backtests, holdout, spec, notes) | exists |
| Sheet: trades + See-all | `GET /strategy/{id}` trades (executions) | exists; full history = paginate |
| Sheet: data feeds | `GET /mind/sources` + `alt_data_provider_summary` | exists |
| Sheet: activity timeline | `events` by ref (`track_opened`, `paper_stepped`, `live_override_launch`…) | exists |
| Paper dashboard cohort curve + per-track rows | `tracks` marks (Σ + per-version) | exists |
| Liquidate-all 2-click | `POST /live/defund {scope:"all"}` + `POST /toggle/live` | ⚠ see gap 3 |
| Running-dot heartbeat | events recency (`cohort_started`, `paper_stepped` ts) or `/autonomy/status` | trivial derive |
| Costs page (fees table, subs, LLM line) | `GET /costs` (vendor actuals, llm_calls, per-fill fees) | exists |
| Settings entry in sidebar | real `/settings` page (universe/legality + keys status) — kept from prod | exists |

## 2. The four real gaps (work before the design is fully honest)

1. **Live vs paper money split** — the ribbon's `LIVE $9,000 · Free · Invested · P&L` and the
   live-only dashboard require the first-class `mode` split (BACKLOG: "Live/sim split in the
   backend" + `/portfolio/summary`). Until it lands, the live numbers must render the honest
   empty/`—` state — never SIM capital labelled live (the old `/live` bug we're killing).
2. **`value_usd` / `invested_usd` on LeaderboardRow** — the Value $ column and the sheet money
   band need track `starting_capital` + `equity` surfaced per row. Small additive contract
   change (data already in `tracks`). Fees-paid per strategy = Σ `executions.fee` (exists).
3. **Liquidate-all really sells** — `/live/defund` today zeroes `positions.qty` in DB; the
   button's promise ("market-sold to USDC") needs the real adapter sell path (BACKLOG item).
   Until then the modal copy must say what it does, honestly.
4. **"Pause all paper"** — no endpoint. Closest existing control is autonomy pause (whole loop).
   Either add a tiny `paper_paused` flag the executor checks, or scope v1 to the autonomy pause
   with honest copy. (Small engine PR.)

Plus one freshness caveat: the Δ24h sub-values and "marked now" depend on hourly marks —
Tier 1 of the realtime epic (other session). Render "—" until marks are fresh enough.

## 3. What the redesign stops displaying (data all kept in backend)

- **Verdicts/Theories ledger, Correlations IC heatmap, Mind panel/scores, Lab funnel detail,
  Console (ARM/DECIDE/STEER), Explorer page** — folded. The data keeps accruing
  (gate_verdicts, correlation_findings, mind_reflections, events). Key facts resurface inside
  the new UI: graveyard = Killed rows + kill reasons (+ plus-3 histogram); funnel = ribbon
  counts (+ plus-3/ship-5 funnel strip); explorer = the sheet's phase chart; data freshness =
  sheet feeds + running dot.
- ⚠ **One control needs a new home: the GLOBAL live arm/disarm (2-step) from Console.**
  The design has per-strategy Launch and Liquidate-all (which disarms), but no global "arm
  live" affordance. Decision for implementation: put the global arm toggle on the Live page
  header (same 2-step `/toggle/live` flow). Do not lose it.

## 4. Technical port notes

- Tokens are already Obsidian Iris — the mockup's CSS vars map ~1:1 onto `globals.css`; light
  theme = the existing `html.light` block (mockup values match closely).
- Table/sheet → React: the screener becomes a client component over `/leaderboard` (one fetch);
  the overlay sheet = a client panel fed by `/strategy/{id}` lazy-loaded on row click — matches
  the "one aggregate call per page" speed goal. Sorting/filtering stays client-side (12–200 rows).
- `zoom:1.1` is a mockup trick — in the real app use a 110 % type/spacing scale via tokens
  (rem-based), NOT CSS zoom (Firefox + fixed-position quirks; we hit one already).
- Routes: keep `/strategies` (new home), `/paper`, `/live`, `/costs`, `/commands`; redirect the
  folded pages (`/lab`, `/mind`, `/verdicts`, `/correlations`, `/explorer`, `/console`, `/`→`/strategies`).
- Contracts: regen after the LeaderboardRow additions; never hand-type.
