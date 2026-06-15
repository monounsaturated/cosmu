# Research lessons — notes for later (false positives, false negatives, predictability)

_Distilled from the astro investigation. The point of these is to make the NEXT search faster and harder to fool._

## 1. The asymmetry that should drive every gate decision
- **False positive (Type I):** you think there's an edge, there isn't → you trade it → **you LOSE real money** (live ≠ backtest).
- **False negative (Type II):** there is an edge, you reject it → you **miss** money (you don't lose it).
- In markets the base rate of a real tradeable edge is **low**, so by Bayes a "significant" backtest is *more likely a false positive than a real edge* unless the bar is strict. That asymmetry — losing > missing, low base rate — is WHY the strict gate is correct, and why **loosening it loses money on average.**

## 2. But strictness has a real cost we currently DON'T measure
- A strict false-positive filter unavoidably creates false negatives (rejects real-but-weak edges).
- **We never measure our false-negative rate** because we never forward-test the REJECTS. So "is the gate too strict?" is currently a faith question, not a number.
- **Fix (cheap, high-value):** a second lane — a *rejects watch-list* that paper-trades gate-rejected-but-promising candidates with zero capital. After N months it tells you, empirically, whether the gate is throwing away money. **Don't loosen the gate; MEASURE its Type-II rate.** (Refines [[gate_calibration_locked]]: never loosen, route — and now, measure.)
- Secondary: charge Deflated Sharpe the **TRUE trial count**, not an inflated grid count, or you over-deflate well-motivated hypotheses (the round-2 study charged 32k when the real count was ~3k).

## 3. How to tell a real pattern from noise (the checklist)
1. **Mechanism / prior** — is there a reason it should work, before you saw the data? (No mechanism = treat as noise.)
2. **Train→OOS rank consistency** — does the in-sample ranking predict the out-of-sample ranking? If the best-train thing is the worst-OOS thing (as astro was), it's noise. THE single most diagnostic check.
3. **Proper null, not a lenient one** — for a cyclic feature use a PHASE/LABEL-shuffle (preserve the series), not fake-random dates. A weak null manufactures false positives (the lunar-vol candidate "survived" a fake-date null and DIED under phase-shuffle, p=0.33).
4. **Economic, not just statistical** — AUC 0.512 at N=83k is statistically real and economically dead. Net-of-fees ≤ 0 kills it.
5. **Deflation at the true trial count**, then **OOS holdout**, then a **forward (paper) test** before any real capital.

## 4. THE predictability lesson — backfilled vs live data (this is the big one)
**A predictor is only usable if it satisfies BOTH: (a) available BEFORE the price move, and (b) the value is IDENTICAL live and in backtest.**
- **Backfilled history from a REVISING source fails (b)** → useless for prediction. At trade time (live) you did NOT have the value that now sits in your DB; the source rewrote it later. Backtesting on it = look-ahead; the "edge" evaporates live. **LunarCrush social is exactly this** — high backtest IC, but back-filled + vendor-revised → NOT tradeable. (PIT audit: `docs/research/alt_data_pit_audit.md`.)
- **Backfilled history from an IMMUTABLE source is fine** — fear_greed (alternative.me), funding (Binance settlement), VIX/DXY/fed-funds (prices/policy rates), and **deterministic astro** (knowable years ahead) all satisfy (b): the back-filled value = the live value.
- **So "can we predict price from indexes?"** — yes, the DATA for immutable indexes is honest and live-usable; the limitation is that the *relationships are weak and decay*, not that the data is unavailable. For revising sources (social/TVL) you MUST ingest **live-forward** (stamp available_at = fetch time, append-only) and **exclude/discount the back-filled history** in backtests, or you are trading a mirage.
- **Rule of thumb:** before trusting any signal, ask "would the value in my database have been knowable, and the SAME, at that bar, live?" If the answer needs the source to not-revise and you can't prove it — discount it.

## 5. Astro-specific verdict (for the record)
Pure astro (planets/aspects/lunar/eclipse/natal) is genuinely noise — not a gate-strictness artifact. Raw AUC ~0.50–0.51, train→OOS inverted, the one candidate died under the correct null. It was given EXTRA chances (152k configs, a candidate chase) and still found nothing. The gate is not "too strict" here; there is nothing to find. The deterministic-knowable-in-advance property of astro is its one virtue — and it's wasted on a non-signal.
