# N11 — Attention-acceleration breakout (2026-06-27)

**Scope:** EXPERIMENT ONLY — the slate's #3 pick, run after [N1 (UMA pre-settlement)](n1-uma-presettlement-2026-06-27.md)
and [N5 (token-unlock drift)](n5-token-unlock-2026-06-27.md) were killed. From
[edge-hypothesis slate v2](edge-hypothesis-slate-v2-2026-06-26.md). Zero production impact: keyless, persists
NOTHING to prod, NO Gate constant touched, NO behaviour change, docs-only. Output = this report + a disposable
HTML table (`docs/reports/n11-attention-accel-table-2026-06-27.html`) + the harness
(`apps/engine/scripts/research/n11_attention_accel.py`, with an offline `--selftest`). Do NOT merge code into a
runtime path.

**Thesis (N11):** a SUDDEN ACCELERATION in public attention precedes a price move (attention onset → flow). Trade
the **second derivative** of attention (the change-in-change), NOT the level (which lags/coincides and is a beta).
The PIT-clean redemption of the killed social lane: that signal was **LunarCrush** (a revising / backfilling
source → a PIT mirage). **Wikipedia pageviews are immutable and T+1-stamped** — day-T views become knowable on day
T+1, and Wikimedia never rewrites history → there is no answer-key leakage. Niche / small-mid-cap tokens are the
moat: a few thousand new eyeballs move a small float, and the giants ignore them.

---

## TL;DR verdict — KILL

| | value |
|---|---:|
| Keyless tokens in the universe (canonical ENTITY_MAP crypto + verified niche extension) | 26 |
| …with both ≥300 immutable Wikipedia obs-days **and** a keyless USDT spot pair | **22** |
| **N attention-acceleration EVENTS** (z ≥ 2.5, contemporaneous price bar) | **298** |
| N shuffle-null events (20 time-shuffles / token) | 4,327 |
| **Forward 5d return (real)** | **−0.19%** / event (log) |
| **CONTROL 1 — shuffle-null** (real vs time-shuffled attention) | real **−0.19%** vs shuffle **−0.22%**, **p = 0.44** → does NOT beat the null |
| **CONTROL 2 — lead-lag reversal** (matched 1-day, the astro disconfirmer) | \|rev(−1d) −0.15%\| / \|fwd(+1d) +0.35%\| = **0.43**; per-day ratio **4.0** → symmetric / coincident |
| **Net spot-tradeable leg** (long, +5d, 50 bps round-trip) | **−0.69% / event**, t = −1.03, PSR ≈ 0.17 |

**One-line:** across **298 attention-acceleration spikes on 22 tokens**, the forward return is **statistically
indistinguishable from a time-shuffled null** (real −0.19% vs shuffle −0.22%, **p = 0.44**) — so what little move
exists is **price autocorrelation, not attention**. The lead-lag is **symmetric** (the price moves about as much in
the bar *before* the signal is tradeable as *after* it → attention is **coincident / lagging**, not predictive), and
the only spot-tradeable leg is **−0.69% per event** net of fees. The PIT story is genuinely clean (immutable T+1
Wikipedia, 0 look-ahead violations) — this is a **genuine-absence** death, not a leakage death. **KILL** on every
pre-registered criterion. The next slate survivor is N13 (delisted-survivorship reversion).

---

## What was pre-registered (BEFORE any result)

One rule, no sweep, declared in the harness header and the slate kill-experiment:

1. **Signal** := the **second derivative** of attention. `L_t = ln(pageviews_t)`; velocity `d_t = L_t − L_{t−1}`;
   **acceleration `a_t = d_t − d_{t−1}`**; z-score `z_t` over the trailing `Z_WINDOW = 60` obs-days, using ONLY
   acceleration points strictly **before** `t` (causal, no look-ahead).
2. **EVENT** := `z_t ≥ Z_THRESH = 2.5` (a clear attention-acceleration spike). One threshold, no sweep.
3. **PIT entry timing** := the acceleration through obs-day T is knowable at **T+1** (Wikipedia's ~1-day lag). The
   first bar a trader can act on is the close on/after T+1; the event's `available_at = obs_day + 1`. A spike whose
   availability day has **no contemporaneous price bar** within `MAX_ENTRY_GAP_DAYS = 4` is **dropped** (not mapped
   to the first bar — see "the stale-mapping guard" below).
4. **Forward** := close-to-close log return over `H_FWD = 5` trading days from the entry bar (long).
5. **Net of fees** := minus a conservative **50 bps** round-trip (20 bps taker + 30 bps small-cap slippage).
6. **DECISIVE CONTROL 1 — shuffle-null:** time-shuffle each token's attention series (same obs/avail-day calendar,
   same *unshuffled* price), recompute the acceleration + events, pool 20 shuffles / token. If the forward edge
   survives the shuffle it is **price autocorrelation, not attention** → KILL. The real forward mean must beat the
   shuffle band (bootstrap p < 0.05).
7. **DECISIVE CONTROL 2 — lead-lag time-reversal (the astro disconfirmer):** measure the effect at lead **+1d**
   (the bar *after* entry, predictive) vs lag **−1d** (the bar *before* entry, coincident). If the move is the same
   magnitude at −1d and +1d, attention travels **with** the price → **coincident, not predictive** → KILL. A real
   predictive edge is asymmetric (symmetry ratio < 0.5).
8. **Pre-registered GO needs ALL of:** (i) N ≥ 30; (ii) the forward mean beats the shuffle-null (p < 0.05);
   (iii) the lead-lag is asymmetric (matched ratio < 0.5 / per-day ratio < 0.5); (iv) net of fees > 0.

---

## The stale-mapping guard (an honesty fix found mid-study)

The immutable Wikipedia series runs back to **2015**; the keyless price window is **~999 daily bars (~2.7 years)**.
A first, un-guarded pass produced **765 "events"** — but **467 of them were spikes from 2015–2022 that degenerately
mapped to the single first available price bar (2023-10-02)**, collapsing hundreds of distinct pre-coverage days onto
one entry and *fabricating* a forward edge (the un-guarded pass falsely "passed" the shuffle-null at p = 0.000). The
pre-registered `MAX_ENTRY_GAP_DAYS = 4` guard drops any spike with no contemporaneous price bar. **After the guard:
298 events, max entry-obs gap = 1 day, 0 stale events.** Every number below is the guarded, contemporaneous pool —
and the guard makes the result *more* honest, not less: the spurious shuffle-null "pass" vanished.

---

## Results (every number)

Full per-token + per-event table:
[`docs/reports/n11-attention-accel-table-2026-06-27.html`](n11-attention-accel-table-2026-06-27.html).
Machine summary: `apps/engine/scripts/research/n11_attention_accel_results.json`.

### CONTROL 1 — forward edge vs the shuffle-null

| leg | value |
|---|---:|
| real forward mean (5d, log) | **−0.0019** (−0.19%) |
| shuffle-null forward mean | −0.0022 (−0.22%) |
| shuffle bootstrap p (real > null) | **0.44** |
| net forward leg (after 50 bps) | **−0.0069** (−0.69%) |
| t-stat / sharpe-per-event / PSR-vs-0 | −1.03 / −0.059 / **0.17** |

The real attention-acceleration forward return (−0.19%) sits **inside** the band a *time-shuffled* attention series
produces on the same prices (−0.22%, p = 0.44). The spike does not pick a better-than-random day — there is **no
attention-specific forward signal** once you strip out price autocorrelation.

### CONTROL 2 — lead-lag time-reversal (the astro disconfirmer)

| leg | value |
|---|---:|
| forward **+1d** move (the bar AFTER entry) | +0.0035 (+0.35%) |
| reverse **−1d** move (the bar BEFORE entry) | −0.0015 (−0.15%) |
| **matched symmetry ratio** \|rev(−1)\| / \|fwd(+1)\| | **0.43** |
| forward per-day move (real_mean / 5) | −0.0004 (−0.04%) |
| per-day symmetry ratio \|rev(−1)\| / \|fwd-per-day\| | **4.0** |

The price already moves ~0.15% in the bar *before* the signal is tradeable, comparable to the +1d move after it —
the attention spike is **coincident with**, not ahead of, the price. And the single +1d pop (+0.35%) is the *entire*
forward effect: the +5d return then drifts **negative** (−0.19%), so even the coincident pop is not harvestable on
the pre-registered horizon.

### The spot-tradeable leg (long the post-onset move), net of 50 bps

| metric | value |
|---|---:|
| mean net return / event | **−0.69%** |
| t-stat | −1.03 |
| Sharpe / event | −0.059 |
| PSR vs zero (production `probabilistic_sharpe`) | 0.17 |

Negative, and the production scorer puts P(true per-event Sharpe > 0) at 0.17 — nowhere near a Gate pass even before
the multiple-testing deflation the full DSR would apply.

### Per-token coverage (the outlier view, not a pooled mean)

19 of 22 tokens carry ≥10 events. The per-token mean forward returns are dispersed and mostly negative or
near-zero; a few are positive (EOS +8.9%, LINK +3.9%, UNI +2.7%, AVAX +1.8%) but these are sparse-event outliers
that do not survive the pooled shuffle-null. No token shows a clean, replicated, attention-specific lead. (Full
per-token table in the HTML.)

---

## Interpretation — why it dies

- **No attention-specific edge.** The forward return after an acceleration spike is **indistinguishable from a
  time-shuffled null** (p = 0.44). Whatever tiny move exists is the tokens' own price autocorrelation around an
  arbitrary day, not a response to attention onset. The shuffle-null — the control built to catch exactly this — is
  decisive.
- **Attention is coincident, not predictive.** The lead-lag reversal shows the price moves about as much *before*
  the signal is tradeable as *after* it (matched ratio 0.43; per-day 4.0). By the time day-T pageviews are knowable
  (T+1) and a trader can act, the move has already happened. This is the same death the astro round diagnosed:
  a symmetric lead-lag = a non-causal / coincident relationship.
- **Negative net of fees.** The only spot-tradeable leg is −0.69% / event after a conservative 50 bps — the +1d
  coincident pop reverses over the horizon, and fees finish it.
- **PIT is genuinely clean (and irrelevant to the kill).** Wikipedia pageviews are immutable and T+1-stamped; the
  harness logged **0 look-ahead violations** (entry always ≥ availability day). The thesis's central claim — that an
  immutable, T+1 attention source dodges the LunarCrush revising-backfill trap — **holds**. The signal still dies,
  but on **genuine absence of a predictive edge**, not on leakage. The "acceleration not level" framing was the
  right instinct (it strips the obvious beta), and yet even the second derivative is coincident.

In the ledger's framing, the wall is **genuine absence of an exploitable edge**, not cost or data-access: the data
was free, immutable, and abundant (22 tokens, back to 2015, 298 contemporaneous events), the PIT story was clean,
and *both* decisive controls fired. Public attention on a token is a **lagging/coincident** tell at daily
resolution — the price and the pageviews rise together, and the immutable T+1 stamp means the trader always arrives
after the move.

---

## Verdict

**KILL.** Pre-registered GO criteria (ii), (iii), (iv) all fail: the forward mean does **not** beat the shuffle-null
(p = 0.44), the lead-lag is **symmetric** (coincident not predictive), and the net spot leg is **negative**
(−0.69% / event). N = 298 ≥ 30 (criterion i passes), so this is a real, well-powered KILL, not a thin-data
non-event. Killed in one offline pass, no prod impact.

*Zero production impact. No Gate constant touched, no money path written, no source ingested. To promote any
remaining slate survivor (next up: N13 delisted-survivorship reversion), run its <1-day offline kill experiment
first; only a passing offline study earns a typed spec through the locked BRUT Gate.*
