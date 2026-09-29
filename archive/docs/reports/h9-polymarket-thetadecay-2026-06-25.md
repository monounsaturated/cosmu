# H9 — Polymarket resolution-convergence theta-decay (2026-06-25)

**Scope:** EXPERIMENT ONLY — research slate #4. Zero production impact: offline, keyless, persists
NOTHING to prod, NO Gate constant touched, NO behaviour change, docs-only. Output = this report + a
disposable HTML table (`docs/reports/h9-polymarket-thetadecay-table-2026-06-25.html`) + the harness
(`apps/engine/scripts/research/h9_polymarket_thetadecay.py`). Do NOT merge code into a runtime path.

**Thesis (H9):** a long-shot YES on a dated binary *theta-decays toward 0* as the deadline nears,
because retail lottery-buyers don't time-decay probability. The trade = **short the long-shot YES (=
buy NO)** at some days-to-deadline, hold to resolution.

---

## TL;DR verdict — KILL (both categories)

| | geopolitics (0% fee) | sports (3% fee) |
|---|---:|---:|
| N closed trades | **235** | **59** |
| YES-resolvers (the tail) | 26 (11.1%) | 12 (20.3%) |
| mean entry YES | 0.109 | 0.142 |
| **mean decay** (entry−terminal) | **−0.0012** | **−0.0617** |
| win rate (short profitable) | 88.9% | 79.7% |
| **mean NET P&L /$1** (after tail + fee) | **−0.0012** | **−0.0917** |
| YES-resolver tail cost (Σ) | **−22.60** | **−9.99** |
| NO-resolver harvest (Σ) | +22.32 | +6.35 |
| **DSR** (gate ≥ 0.95) | 0.476 | 0.017 |
| min-trades (gate ≥ 30) | PASS (235) | PASS (59) |
| **Gate verdict** | **FAIL** | **FAIL** |

**One-line:** N = 294 closed trades (235 geo / 59 sports), net-of-fee-and-tail edge = **−0.0012/$1
geopolitics, −0.092/$1 sports** → **KILL**. The thesis is false on an honest, survivorship-complete
sample: the long-shot YES does **not** decay toward 0 (mean decay is ≈0 / negative), and the rare
YES-resolvers cost *more than every lottery-ticket gain combined*. The 80–89% win rate is a mirage —
this is the survivorship trap the pre-registration warned about, and it is exactly what eats the edge.

---

## Method

**Data (keyless, free — the SAME endpoints `cosmu/data/sources/polymarket.py` already calls):**

- **Discovery / resolution:** Gamma `/events?closed=true&order=volume` → resolved markets, with per-event
  **tag labels** (the reliable category route — the `/markets?order=` path strips tags and the
  `tag=<label>` filter is silently ignored by the API), `endDate` (the deadline, **fixed at
  `createdAt`**), and `outcomePrices = [YES, NO]` (the UMA-settled terminal price, the resolution label).
- **Odds history:** CLOB `/prices-history?market={YES_token}&fidelity=1440&interval=max` → daily YES-odds.
  Daily granularity is sufficient here because H9 is **one trade per market** (enter once, hold to
  resolution), unlike the intraday fade spec `g2-prediction-prob-overextension-fade-short` whose
  3–10-day-hold needs hourly bars (the granularity wall in
  `docs/reports/polymarket-trust-experiment-2026-06-25.md`).

**Category fee bands (on TODAY's schedule):** geopolitics = **0%**, sports = **3%**. The **crypto 7.2%
band is EXCLUDED outright** — any market whose event touches a crypto tag is dropped, so the high fee
never flatters or distorts the result.

**Pre-registered entry rule (ONE config, NO sweep):**
- long-shot YES = entry-bar odds in **[0.05, 0.25]**;
- entry bar = the daily bar **closest to 14 days before the deadline** (±7d tolerance, else skip);
- **SHORT YES** (= buy NO) at that price, **hold to resolution**;
- P&L per $1 short = `entry_YES − terminal_YES`, minus the round-trip category fee.

**Sample (survivorship-complete):** every cleanly-resolved binary market in each discovered event is
sampled — both the many long-shots that resolved NO **and** the rare long-shots that resolved YES.
Multi-outcome events (NBA-champion, election-winner) are taken in full, which is exactly where the
YES-resolvers live. To spend the per-market odds-fetch budget across the *whole* resolved history (not
just top-volume), each category is **seeded-shuffled** (seed 7) and capped at 1,800 markets; the shuffle
does **not** condition on outcome, so the YES/NO ratio is preserved in expectation. 28,399 resolved
binaries were discovered (6,648 geo + 21,751 sports); 3,600 were sampled and fetched; **294 produced a
qualifying entry** (long-shot band × days-to-deadline filter).

---

## The two disconfirmers (these decide it)

### (1) Survivorship — the core risk, and it is what kills H9

A naive "sell lottery tickets" study that drops the YES-resolvers shows a glittering ~85% win rate and
a tiny positive average. **This study deliberately keeps every YES-resolver**, and the result inverts:

| | geopolitics | sports |
|---|---:|---:|
| NO-resolvers (lottery expires) | 209 trades, **+22.32** total | 47 trades, **+6.35** total |
| YES-resolvers (the favourite wins) | 26 trades, **−22.60** total | 12 trades, **−9.99** total |
| **net** | **−0.29** | **−3.64 gross / −5.41 net of fee** |

The asymmetry is **structural**, not a small-sample accident: a short YES capped its max gain at the
entry price (≤ 0.25) but its max loss is `1 − entry` (≥ 0.75). So **one YES-resolver erases ~3–4
NO-resolver wins**, and at an 11–20% YES-resolve rate the longshot bias simply doesn't pay. Worst
single tails (from the HTML table): "Will Biden pardon Adam Schiff?" entered 0.053 → resolved YES →
**−0.947**; "Will Israel or the US target an Iranian nuclear facility?" entered 0.074 → YES → **−0.926**.
A handful of these wipe out hundreds of expiring lottery tickets.

### (2) PIT-safe — verified clean

- The deadline (`endDate`) is fixed at `createdAt`; the entry bar is selected purely from days-to-
  deadline, with no reference to the outcome.
- The outcome (`outcomePrices`) only labels the trade **post-hoc** (the terminal payoff), never the entry.
- The harness **asserts on every trade** `created_at ≤ entry_ts < deadline` (fail-loud, no silent
  look-ahead). The full 294-trade run completed with **zero assertion failures** → no look-ahead.
- This matches the independent PIT audit in the trust experiment (midnight buckets are backward-honest,
  immutable, resolution-true).

---

## Why the thesis is false (mechanism)

The premise — "long-shot YES decays toward 0 because retail won't time-decay" — assumes the long-shot
is *over-priced* and bleeds out. The survivorship-complete data says otherwise:

- **mean decay ≈ 0 (geo −0.0012) / negative (sports −0.0617).** On average the long-shot YES did **not**
  drift down toward 0; in sports it drifted **up** (favourites firming as the event nears). Polymarket
  long-shot odds at 14 days out are, on this sample, **roughly fair-to-slightly-cheap**, not richly
  over-priced — there is no systematic theta to harvest.
- Even where most tickets do expire worthless (the 80–89% win rate), the price you collect for shorting
  a 0.05–0.25 YES is *exactly the fair compensation* for the tail you're short. Net of nothing it's a
  wash (geo), and net of the 3% sports fee it's a clear loss.

This is the **favourite-longshot bias pointing the *wrong way* for a naive fade** — the same conclusion
the trust experiment's toy backtest reached on the *rich* (favourite) side, now confirmed on a proper
survivorship-complete *longshot* sample with N well above the gate's min-trades.

---

## Gate stats (BRUT per category, via the production scorer)

Computed with the real `cosmu/master/scorer.py` (`deflated_sharpe_prob`, `sample_moments`) and the live
`GateSettings` (min_trades=30, DSR≥0.95) — nothing re-implemented. Single pre-registered rule = 1 config,
so CSCV-PBO (which needs ≥2 configs) is N/A; the binding bars are min-trades and DSR.

| category | N | mean net | sd | per-obs Sharpe | skew | kurtosis | DSR | min-trades | **verdict** |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| geopolitics | 235 | −0.0012 | 0.309 | −0.0040 | −2.40 | 7.00 | **0.476** | PASS | **FAIL (DSR)** |
| sports | 59 | −0.0917 | 0.394 | −0.2326 | −1.41 | 3.12 | **0.017** | PASS | **FAIL (DSR)** |

Both clear min-trades (the sample is real and deep enough) and both fail DSR hard. The heavy **negative
skew + high kurtosis** is the statistical fingerprint of the survivorship tail: a pile of small wins and
a few catastrophic losses. A non-deflated Sharpe would *also* be near-zero/negative — this is not a
multiple-testing rejection, the raw edge is simply absent (geo) or negative (sports).

---

## Honest verdict

**KILL, both categories.** The thesis fails on its own pre-registered terms:

1. **Net edge < fee.** Geopolitics nets **−0.0012/$1 at 0% fee** (a loss before any fee); sports nets
   **−0.092/$1** (−0.062 gross, then −0.03 fee). Neither clears, and geo doesn't even clear breakeven.
2. **The tail eats it.** The YES-resolver tail cost (−22.60 geo, −9.99 sports) exceeds the entire
   NO-resolver harvest (+22.32 geo, +6.35 sports). This is the decisive failure mode and it is *only*
   visible because the YES-resolvers were kept.
3. **Decay is absent.** Mean decay ≈ 0 / negative — the long-shot YES does not theta-decay toward 0, so
   there is no mispricing to short.

Trade count is **not** the problem (235 / 59, both > 30); granularity is **not** the problem (daily is
correct for a hold-to-resolution trade). The edge is genuinely absent. **Do not author an H9
prediction-fade spec.** This also independently re-confirms the project's standing read that the
prediction-fade lane's only plausible edge is *intraday* over-extension that reverts *before*
resolution (needs the hourly windowed CLOB path + a UMA resolution join), **not** a
hold-to-resolution longshot short — which this study has now closed.

---

## Provenance / reproducibility

- **Harness:** `apps/engine/scripts/research/h9_polymarket_thetadecay.py` (committed, offline, keyless,
  read-only; seeded → deterministic). Run:
  `python3 apps/engine/scripts/research/h9_polymarket_thetadecay.py --max-events 1500 --per-cat-budget 1800 --workers 12`
- **HTML (every one of the 294 trades, survivorship-complete):**
  `docs/reports/h9-polymarket-thetadecay-table-2026-06-25.html`
- **Endpoints:** `gamma-api.polymarket.com/events` (discovery + resolution),
  `clob.polymarket.com/prices-history` (daily odds). Keyless, free.
- **Gate:** production `cosmu/master/scorer.py` + `cosmu/config/settings.py::GateSettings`, imported
  unchanged (min_trades=30, DSR≥0.95).
- **Prior art read:** `docs/reports/polymarket-trust-experiment-2026-06-25.md` (PIT honesty + the keyless
  windowed fetch), `strategies/inbox/g2-prediction-prob-overextension-fade-short.json` (the flagship
  fade spec and its Disconfirmer 2, which this study directly tested).
- **Run:** live, 2026-06-25, 186.5 s for 3,600 markets. **Zero production impact** — no DB writes, no
  `alt_data` rows, no cron, no Gate run, no runtime code path touched. Docs-only.
