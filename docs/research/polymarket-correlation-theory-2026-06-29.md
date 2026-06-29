# Polymarket event probabilities → correlated-asset moves: a literature-grounded theory & trading map (2026-06-29)

*Quantitative macro research note backing the **LLM/Conviction lane** (`apps/engine/cosmu/correlate/`). All
claims are sourced to academic, central-bank, multilateral, or professional-press material; course-sellers and
SEO content were screened out. This is a THEORY/MECHANISM map, **not** a backtested edge — the conviction lane it
feeds is propose-only and human-armed, and every (event × asset × venue) candidate must clear the deterministic
Gate on its own BRUT data before any capital.*

---

## TL;DR — the honest, mostly-skeptical decision

The mechanism map (§2) is well-supported and reliable as a *causal/directional* reference. The **trading edge**,
however, is narrow and mostly **negative**, and this note's most decision-relevant finding is a caution:

> **Prediction markets are accurate probability aggregators, but in liquid, public-information regimes they are
> roughly *co-incident* with — not a clean *leader* of — traditional asset markets. They even *underreact* to
> public signals (≈0.64-for-1; Angelini & De Angelis 2026). A tradeable PM *lead* exists mainly in two regimes:
> (a) genuinely private/insider geopolitical *timing* information, and (b) thin/illiquid PM micro-windows.**

This **converges with the project's prior internal verdict** (the Polymarket latency + smart-wedge lanes were
KILLed: median winner already at 0.9995 by ProposePrice; clean markets calibrated). The durable use of Polymarket
here is therefore **as a real-time, machine-readable macro-event NOWCAST that drives a trade in the *correlated
asset*** — with a mandatory disconfirmer from §6 — **not** as a thing to arbitrage against itself.

The honest Pareto front is small (§3): only **#1 geopolitical → oil/energy (as a nowcast)** and **#2 crypto-binary
→ proxy-equity (MSTR/COIN) lag** survive the skepticism filter. The events with the *cleanest* mechanism (Fed,
elections) are exactly the ones liquid markets price in seconds — **no PM lead, no edge**.

**Machine-readable form.** The watchlist, asset links, directions, lags, mechanisms, and named confounds in §2–§6
are encoded as typed data in [`correlation_map.py`](../../apps/engine/cosmu/correlate/correlation_map.py); the
event monitor that scans them is [`monitor.py`](../../apps/engine/cosmu/correlate/monitor.py); the resolution-date
/ probability-series normalizer is [`dates.py`](../../apps/engine/cosmu/correlate/dates.py); the conviction
proposal + deterministic caps are [`proposal.py`](../../apps/engine/cosmu/correlate/proposal.py) +
[`gate.py`](../../apps/engine/cosmu/correlate/gate.py).

---

## 1. Prediction markets as information signals

**Core finding: PMs are accurate aggregators but, in liquid/public-information regimes, roughly *co-incident*
with — not a clean *leader* of — traditional markets. The exploitable lead exists mainly where the PM carries
private/orthogonal information, or in thin micro-windows.**

| Claim | Evidence | Source & why credible |
|---|---|---|
| PMs forecast well, beating moderately sophisticated benchmarks | IEM beat the eventual outcome ~74% of the time vs 964 polls (1988–2004); election-eve mean absolute error ≈1.33pp | Berg et al. (IEM); **academic** |
| PM forecasts ≈ or beat polls | Over 13 candidacies 1988–2004, market MAE 1.6pp vs Gallup 1.9pp | **Wolfers & Zitzewitz, "Prediction Markets," *J. Econ. Perspectives* 18(2), 2004** — canonical peer-reviewed survey ([aeaweb](https://www.aeaweb.org/articles?id=10.1257%2F0895330041371321) · [PDF](https://jmvidal.cse.sc.edu/library/wolfers04a.pdf)) |
| IEM efficient at short horizons; no short-horizon longshot bias | Tested vs longshot & overconfidence biases | Peer-reviewed efficiency studies, *Int. J. Forecasting* ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0169207018300499)) |
| **PMs UNDERREACT to public signals (key for any edge claim)** | High-frequency Polymarket data: a 1-min change in a benchmark-model probability maps to only **≈0.64-for-1** contemporaneous price change; the missing adjustment predicts a few minutes of drift; underreaction is **worse when liquidity is low** | **Angelini & De Angelis (2026), "When Do Markets Fully Process Public Information? Evidence from Real-Time Prediction Markets,"** arXiv:2606.07811 ([arxiv](https://arxiv.org/abs/2606.07811)) |
| Sophisticated traders/bots, not retail, capture PM profits | Who-wins/loses empirical Polymarket study | **CEPR DP21615**, "Who Wins and Who Loses in Prediction Markets?" ([CEPR](https://cepr.org/publications/dp21615)) |
| **PMs DO lead news when traders hold private info** | 9 connected accounts won $2.4M at a **98% win rate over 80+ bets** on Iran-war timing, entering as low as 6% *before* announcements | **Bloomberg** ([graphic](https://www.bloomberg.com/graphics/2026-polymarket-bets-iran-war-insider-trading/)) & **CBS/60 Minutes** ([report](https://www.cbsnews.com/news/betting-on-iran-war-insider-trading-concerns-prediction-markets-60-minutes/)) — top-tier press |

**Interpretation for an autonomous fund — two regimes:**

1. **Public-information regime (most macro events):** the PM and the liquid asset (oil, Treasuries, SPX) read the
   *same* public wire. The PM is unlikely to lead a deep, fast futures market; underreaction (0.64-for-1) means it
   is, if anything, *slower*. Here the PM is a **confirmation/explanation instrument**, not alpha.
2. **Private-information regime (geopolitical event *timing*):** insider-style flow can move a PM *before* the wire
   (the Iran-war accounts). This is the only regime where the PM plausibly **leads** a liquid asset — and it is
   rare, legally fraught, and the asset (oil) often *also* gaps before you can act.

---

## 2. Cross-asset correlation MAP

Direction convention: **"↑ event probability"** = the named/"risk-rising" outcome becoming more likely (e.g.
P(Hormuz closes) rises). "Lag" = asset reaction speed vs a clean information arrival; for liquid futures this is
**seconds–minutes** (PM rarely leads). Magnitudes are event-study figures from the cited sources, not forecasts.

### 2A. Middle-East conflict / oil-supply shock (Hormuz, Iran/Israel, OPEC)

| Asset | Direction when P(shock)↑ | Lag | Mechanism | Source |
|---|---|---|---|---|
| Brent / WTI | **↑ (large, moves FIRST)** | seconds–minutes | Supply-disruption risk premium; Hormuz carries ~20% of seaborne oil | ECB: oil **+~50%** after a Middle-East conflict shock, elevated ~2 quarters ([ECB Bulletin 2026](https://www.ecb.europa.eu/press/economic-bulletin/focus/2026/html/ecb.ebbox202604_02~7d79ce3c90.en.html)); CFA: Brent $72→$100 on a Hormuz disruption ([CFA Institute](https://rpc.cfainstitute.org/blogs/enterprising-investor/2026/geopolitical-shocks-what-moves-first-why-matters)) |
| Energy equities (XLE) | ↑ | minutes–hours | Producers' margins rise with crude; energy beta | Energy-beta playbooks ([AllianceBernstein](https://www.alliancebernstein.com/americas/en/institutions/insights/investment-insights/equity-outlook-middle-east-war-energy-shock-test-fragile-markets.html)) |
| Airlines (JETS) | ↓ | hours–days | Jet fuel is a top cost; margin compression | ECB / AB (energy-intensive firms' costs rise) |
| Gold (GLD) | ↑ (steady, not spiky) | minutes–hours | Safe-haven + USD hedge; "held above pre-conflict levels through the most uncertain phase" | [CFA Institute](https://rpc.cfainstitute.org/blogs/enterprising-investor/2026/geopolitical-shocks-what-moves-first-why-matters) |
| USD (DXY) | ↑ | minutes–hours | Risk-aversion + oil-importer terms-of-trade; "USD appreciates continuously" | [ECB Bulletin](https://www.ecb.europa.eu/press/economic-bulletin/focus/2026/html/ecb.ebbox202604_02~7d79ce3c90.en.html) |
| Broad equities (SPX) | ↓ | minutes–hours | Growth/margin drag; calibrated **−10% SPX on impact, ~−20% by 2 quarters** | [ECB Bulletin](https://www.ecb.europa.eu/press/economic-bulletin/focus/2026/html/ecb.ebbox202604_02~7d79ce3c90.en.html) |
| Treasuries | yields **↓** (price ↑) | minutes | Safe-haven bid + expected easing as output contracts | [ECB Bulletin](https://www.ecb.europa.eu/press/economic-bulletin/focus/2026/html/ecb.ebbox202604_02~7d79ce3c90.en.html) |
| VIX | ↑ (substantial) | seconds–minutes | Realized + implied vol jump | [ECB Bulletin](https://www.ecb.europa.eu/press/economic-bulletin/focus/2026/html/ecb.ebbox202604_02~7d79ce3c90.en.html) |

**Key sequencing fact (CFA):** *"energy prices adjusted first, equity markets followed unevenly… If oil is moving
on supply risk, waiting for confirmation from equities is usually too late."* Cross-sectional dispersion is large:
same Hormuz shock, S&P 500 fell modestly while energy-import-dependent NIFTY 50 fell **~11%** — "energy-import
dependence is the primary determinant of drawdown severity."

### 2B. Fed monetary policy / rate decisions / CPI

| Asset | Direction on a **dovish** surprise (cut vs expected) | Lag | Mechanism | Source |
|---|---|---|---|---|
| Equities (SPX) | ↑ | seconds | A 25bp *unexpected* cut ≈ **+1% CRSP value-weighted**; intermeeting 50bp cuts gave +5.3% / +4.0% one-day | **Bernanke & Kuttner (2005), *J. Finance*** ([NBER w10402](https://www.nber.org/system/files/working_papers/w10402/w10402.pdf)) |
| Growth/tech vs value | growth outperforms | seconds | Long-duration cash flows + discount-rate channel; effect runs through *expected excess returns* | Bernanke–Kuttner |
| Rates (2y/10y, TLT) | yields ↓, TLT ↑ | seconds | "Path"/forward-guidance surprises move long yields more than the target change; a 2-factor model explains **>82%** of the asset-price response | **Gürkaynak, Sack & Swanson (2005)**, *Int. J. Central Banking* ([repec](https://ideas.repec.org/p/sce/scecf5/323.html)) |
| USD (DXY) | ↓ on dovish | seconds–minutes | Rate-differential / carry channel | iShares / US Bank macro notes ([iShares](https://www.ishares.com/us/insights/fed-rate-cut-and-your-portfolio)) |
| Gold | ↑ on dovish | minutes | Lower real rates ↓ the opportunity cost of non-yielding gold | USAGOLD / SSGA outlooks |
| BTC | ↑ on dovish (risk-on / liquidity) | seconds–minutes | Post-2024 BTC trades with risk assets (see §2F) | [FRL](https://www.sciencedirect.com/science/article/abs/pii/S1544612324011796) |

*CPI prints are the inputs:* a hot CPI ⇒ hawkish repricing ⇒ 2y yield ↑, equities ↓ (ECB notes an episode where
the 2y rose on higher inflation compensation and equities fell ~5%).

### 2C. US elections / policy-regime change (anchor: Trump 2024)

| Asset | Direction (Trump win) | Lag | Mechanism | Source |
|---|---|---|---|---|
| Broad equities | ↑ | day-of/+1 | Deregulation premium; **+1.39% CAR on day +1** | Event-study papers, *Economics Letters* / *Finance Research Letters* ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0165176525000072)) |
| Banks (KBE/XLF) | ↑↑ | day-of/+1 | Deregulation + M&A fee hopes; **JPMorgan +8.3%** | [NPR](https://www.npr.org/2024/11/06/nx-s1-5181315/stocks-bitcoin-crypto-truth-social-trump-election) |
| Energy (XLE) | ↑ | day-of | Pro-fossil-fuel regulatory shift | [The Conversation](https://theconversation.com/2024-presidential-election-u-s-equities-surged-then-retreated-after-trumps-victory-243778) |
| Solar / green (TAN) | ↓↓ | day-of | Subsidy/IRA risk; **First Solar −15.1%** | Wiley *Bus. Strategy & Env.* ([link](https://onlinelibrary.wiley.com/doi/full/10.1002/bse.4371)) |
| Defense (ITA) | ↑ (thesis) | days | Higher defense-spend expectation | US Funds — **buy-side piece, weaker tier** |
| USD (DXY) | ↑ (~107) | day-of | Tariff/inflation + growth premium | [NPR](https://www.npr.org/2024/11/06/nx-s1-5181315/stocks-bitcoin-crypto-truth-social-trump-election) |
| Treasuries | yields ↑ (price ↓) | day-of | Fiscal-deficit/inflation premium on an R sweep | press |
| BTC / COIN | ↑↑ | day-of | Pro-crypto policy; **BTC >$75k ATH, Coinbase +19.4%** | [NPR](https://www.npr.org/2024/11/06/nx-s1-5181315/stocks-bitcoin-crypto-truth-social-trump-election) |

### 2D. Government shutdown / debt-ceiling / fiscal

| Asset | Direction (crisis prob ↑) | Lag | Mechanism | Source |
|---|---|---|---|---|
| T-bills around the X-date | yield ↑ (cheapen) on specific maturities | days | Default-timing risk concentrates in bills maturing near the X-date | **Morgan Stanley** ([link](https://www.morganstanley.com/ideas/debt-ceiling-market-volatility-2023)); **Treasury TBAC** |
| Equities | ↓ | days | Risk-off ("markets respond by quickly dropping equities") | [Morgan Stanley](https://www.morganstanley.com/ideas/debt-ceiling-market-volatility-2023) |
| Longer Treasuries | yields ↑ broadly | days | Risk premium + ratings risk (Fitch negative watch, May 2023) | Morgan Stanley |
| USD (DXY) | ↓ | days | Confidence shock | press |
| Gold | ↑ | days | Safe haven as USD weakens & uncertainty rises | press |
| VIX | ↑ | days | Tail-risk hedging demand | Morgan Stanley |

*Note:* the effect is **non-linear/binary around the X-date** and largely resolves on a deal — see §6.

### 2E. Recession / macro-regime probability

| Asset | Direction (P(recession)↑) | Lag | Mechanism | Source |
|---|---|---|---|---|
| Equities | ↓ | weeks–months | Earnings/discount-rate; the Excess Bond Premium predicts equity declines | **Gilchrist & Zakrajšek (2012), *AER*** ([AEA](https://www.aeaweb.org/articles?id=10.1257%2Faer.102.4.1692)) |
| Credit (HYG ↓ / spreads ↑) | spreads widen | leads/coincident | EBP = spread component orthogonal to default risk; rises ⇒ credit-supply & activity contraction; the Fed publishes a monthly EBP recession-prob | Gilchrist & Zakrajšek; **Fed FEDS Notes** ([Fed](https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html)) |
| Treasuries | yields ↓ (price ↑) | weeks | Flight-to-quality + easing expectations; 10y–3m inversion is the classic lead | Fed; yield-curve literature |
| Gold | ↑ | weeks | Safe haven / lower real rates | (per §2B/2D) |
| Copper ("Dr. Copper") | ↓ | leads/coincident | Industrial-demand bellwether | **Practitioner heuristic — no top-tier peer-reviewed event study isolating copper's recession lead was found; lower-confidence.** |

### 2F. Crypto-specific events (ETF approval, regulation, halving)

| Asset | Direction | Lag | Mechanism | Source |
|---|---|---|---|---|
| BTC into approval | ↑ then **"sell the news" ↓** | run-up over weeks; reversal on the event | Spot BTC ETFs approved **Jan 10 2024**; BTC ran to ~$49k then fell **−16% to <$39k** post-approval | **SEC statement** ([SEC](https://www.sec.gov/newsroom/speeches-statements/gensler-statement-spot-bitcoin-011023)); [CoinDesk](https://www.coindesk.com/markets/2024/01/23/bitcoin-under-39k-as-etf-debut-continues-to-be-a-sell-the-news-event) |
| BTC ↔ equities correlation | structural ↑ post-ETF | persistent | ETF turned BTC into an asset moving *with* equities — **raises confound risk, kills the diversification thesis** | *Finance Research Letters* ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1544612324011796)) |
| MSTR / COIN | high-beta BTC proxies | coincident | MSTR ≈ leveraged BTC; MSTR–IBIT 90d corr **~82%** | CoinGlass — data vendor, indicative |

### 2G. Russia/Ukraine & European energy

| Asset | Direction (escalation prob ↑) | Lag | Mechanism | Source |
|---|---|---|---|---|
| European gas (TTF; UNG proxy) | ↑↑ | hours–days | Supply weaponization; **TTF peaked >€345/MWh Aug 2022** | **IEA** ([link](https://www.iea.org/commentaries/what-drives-natural-gas-price-volatility-in-europe-and-beyond)); **EIA** ([link](https://www.eia.gov/todayinenergy/detail.php?id=55059)) |
| Wheat / ags (WEAT) | ↑ | hours–days | Ukraine = 5th-largest wheat exporter; prices ~+⅔ by Apr 2022 | **CEPR** ([link](https://cepr.org/voxeu/columns/battlefield-market-how-disruptions-ukraine-affected-grain-price-trends)); **Chicago Fed** ([link](https://www.chicagofed.org/publications/chicago-fed-letter/2024/492)) |
| EUR/USD | ↓ | days–weeks | Energy-import terms-of-trade shock; EUR **>4%** weaker vs USD post-invasion | **CEPR** ([link](https://cepr.org/voxeu/columns/euro-weakness-2022)); ECB |
| European equities (VGK) | ↓ | days | Energy-cost margin shock + growth drag | IEA/CEPR |

---

## 3. Pareto-ranked watchlist of highest-ROI Polymarket event-TYPES

Ranking weights: **(a) linkage cleanliness** (one event → one dominant asset), **(b) PM liquidity/volume**,
**(c) PM lead vs lag** (edge needs PM-first OR orthogonal info), **(d) confound risk**. The binding hurdle is (c):
for liquid macro assets the PM rarely *leads*, so the ranking favors event-types where the **asset is slow/illiquid**
(PM can lead it) or the **PM carries orthogonal/private resolution info**.

**Tier 1 — best risk-adjusted (clean linkage + PM may lead the asset)**

1. **Middle-East escalation / Hormuz / Iran-strike timing → oil (Brent/WTI), then XLE, gold.** Cleanest linkage on
   the board (energy moves first, unambiguously). High PM liquidity (Iran-war markets saw ~$45M flagged flow). The
   *only* documented regime where PMs verifiably led (98%-win insider accounts). **Skeptic flag:** that lead is
   *private timing* info and oil futures often gap *with/before* you act → realistic edge is PM as a fast nowcast to
   size an oil/energy position, not PM-vs-oil arbitrage (the internal latency-lane KILL applies).

2. **Crypto regulatory/ETF binaries → BTC/ETH, and the lagging proxies COIN/MSTR.** Clean, high-beta linkage
   (MSTR–BTC ~82%); high PM liquidity; PM resolution can front-run slow proxy equities intraday. **Skeptic flag:**
   the BTC ETF was a textbook **"buy the rumor, sell the news"** (−16% post-approval) — P(approval) rising can
   coincide with BTC *topping*. Trade the *proxy lag* (MSTR/COIN catching up), not the headline.

**Tier 2 — strong linkage but the asset has likely already priced it (thin edge)**

3. **Fed decision / CPI binaries → rates, USD, gold, growth-vs-value.** The most rigorously documented mechanism in
   finance (Bernanke–Kuttner; GSS) — *and that is exactly why there's no edge*: rates futures and SPX react in
   *seconds* to the same public print the PM reads; the PM cannot lead Fed-funds futures. Use as *explanation*.

4. **Russia/Ukraine & European energy → TTF gas, EUR, wheat.** Clean linkage but TTF/wheat futures are themselves
   liquid and headline-driven; PM lead is doubtful except on *negotiation/ceasefire* binaries (orthogonal political
   info). Medium confound (weather/storage).

**Tier 3 — regime context, not a trigger**

5. **Recession-probability → equities/HYG/copper/gold.** Slow, multi-month; PM lags the EBP/yield-curve signal the
   Fed already publishes. No timing edge; high confound.

6. **Elections → sector rotation.** Huge, clean *event-day* moves (banks +8%, solar −15%) but **scheduled, binary,
   pre-positioned** — the PM and assets converge together as results print. Edge only in the bot-dominated count
   window.

**Tier 4 — avoid as a primary trigger**

7. **Debt-ceiling / shutdown.** Binary, deal-resolved, non-linear; the asset response concentrates in specific
   T-bill maturities (microstructure) and reverses on the deal. High whipsaw.

**Bottom line:** the cleanest-mechanism events (Fed, elections) are *already priced* (no edge); the possible-lead
events (geopolitical timing, crypto-proxy lag) carry the most confound and legal hair. The honest Pareto front is
**#1 and #2 only**, and both must clear a per-(event × asset × venue) Gate before any capital.

---

## 4. event→asset playbook (PM moves first)

Rule: a Polymarket probability **jump of ≥+10pp in ≤24h** on event-type X ⇒ a *candidate* trade on the correlated
asset. *All are hypotheses for the conviction lane; sizes are illustrative and human-armed.*

| PM signal (≥+10pp/day) | Trade | Direction | Horizon | Key risk / disconfirmer |
|---|---|---|---|---|
| P(Hormuz closure / Iran-strike) ↑ | Long Brent/WTI (or long XLE if futures already gapped) | Long oil/energy | hours–days | **Is front-month crude already +X%? If yes, you're late — skip.** De-escalation reverses fast. |
| Same, secondary leg | Long gold, short SPX / long VIX | per §2A | hours–days | A dovish Fed could lift SPX *into* the shock |
| P(new crypto ETF approval) ↑ but BTC already up | Long the **lagging proxy** (MSTR/COIN) vs BTC — not BTC | Long proxy | hours | **"Sell the news"** — do NOT chase BTC into the event |
| P(hawkish Fed / hot CPI) ↑ intraday before print | (Tier-2, low edge) fade growth / long USD | per §2B | minutes–hours | Print is seconds away; futures lead the PM → likely no edge |
| P(Russia–Ukraine escalation) ↑ | Long TTF/UNG gas / short EUR / long wheat | per §2G | days | Weather/storage confound; negotiation headlines whipsaw |
| P(US default/no-deal) ↑ near X-date | Long gold, long VIX (avoid the bill-curve microstructure trade) | per §2D | days | Resolves violently on a deal → asymmetric reversal |
| P(recession) ↑ (sustained, not 1-day) | Trim equities, add Treasuries/gold; watch HYG | weeks | Slow; no timing edge; size small |

**Sizing logic:** the cleaner the linkage and the more the PM *leads* (geopolitical timing), the larger/faster the
trade. The more the event is *scheduled/priced* (Fed, election), the smaller/slower — confirmation, not signal.

---

## 5. asset→event playbook (asset moves first; use PM to explain/confirm)

| Asset move you observe | Polymarket markets to check | What it tells you |
|---|---|---|
| Brent/WTI gaps **up** | Hormuz / Iran-strike / OPEC-cut / Middle-East-conflict | Concurrent geopolitical-PM jump → supply-risk driver, **hold/extend** the energy long. PMs flat → likely an **inventory/EIA print or OPEC-supply** move → mean-reverting, fade. |
| SPX **down** + gold/Treasuries **up** | recession-prob, geopolitical, Fed-hike | Sorts a *growth-scare* (recession PM up → durable) from a *geopolitical risk-off* (conflict PM up → may snap back on de-escalation). |
| USD (DXY) **up** | Fed-hawkish, election, geopolitical, EU-energy | Sorts a *rate-differential* USD move (Fed PM) from a *safe-haven* USD move (conflict PM) — different durations. |
| BTC **up** sharply | crypto-ETF/regulation, Fed-dovish, election-crypto | Regulatory PM jump = idiosyncratic crypto catalyst (proxy-equity follow-through likely). Fed-dovish PM jump = risk-on macro (correlated to SPX, less crypto-specific edge). |
| European gas (TTF/UNG) **up** | Ukraine-escalation/ceasefire | PM-confirmed escalation = supply-driven, durable; PM-flat = weather/storage, mean-reverting. |
| Defense/bank/solar sectors diverge | election / policy-regime | Confirms a **policy-rotation** driver (durable) vs a one-off earnings move (transient). |

**Conviction rule:** asset-move + concurrent PM-move in the *mechanistically correct direction* = high conviction
(two independent instruments agree). Asset-move with *no* corroborating PM = low conviction → assume a confounder
and apply §6.

---

## 6. Confounds & disconfirmers

The **named alternative explanation** a conviction proposal must rule out before attributing the asset move to the
PM event. Each is a concrete disconfirmer wired into the proposal's mandatory `disconfirmer` field.

| Link | Named confounder (NOT the event) | Disconfirmer to carry |
|---|---|---|
| Hormuz/Iran ↑ → oil ↑ | **Weekly EIA/API inventory print** or an **OPEC+ supply/quota decision** moving oil that day | Did oil move on an *inventory/OPEC* calendar day? Is the Brent–WTI spread / term structure moving like a *supply* (not *risk*) shock? If the geopolitical PM is *flat*, it's not the event. |
| Conflict ↑ → SPX ↓ | **Coincident Fed/CPI surprise** or **earnings season** | Strip scheduled Fed/CPI/earnings days; require gold + VIX to corroborate the risk-off pattern, not just SPX |
| Fed-dovish → equities ↑ | The move was the **"path"/forward-guidance, not the target** — or the cut was *expected* (no surprise) | Use the *surprise* (futures-implied), not the headline; GSS: target vs path; B-K: only the *unanticipated* component moves stocks |
| Recession-PM ↑ → equities ↓ | The EBP/credit move was **orthogonal risk-appetite** or a one-off liquidity event | Cross-check the Fed's published EBP recession-prob; require HYG to confirm, not just equities |
| ETF-PM ↑ → BTC ↑ | **"Sell the news"** — the run-up *was* the trade; approval = the top | Did BTC already rally into the event? If so, expect reversal, not continuation |
| BTC ↑ → "crypto catalyst" | **Post-2024 BTC≈equities correlation** — BTC moved because SPX/Nasdaq did (macro), not crypto news | Check SPX/Nasdaq concurrently; if they moved together, it's macro beta, not a crypto edge |
| Debt-ceiling-PM ↑ → risk-off | A **deal headline** reverses everything; stress is only in **specific X-date T-bills** | Don't generalize bill-curve microstructure to a macro directional trade; expect violent reversion on resolution |
| Ukraine-PM ↑ → TTF gas ↑ | **Weather / storage / LNG-import flows** drive European gas independently | Require a concurrent escalation-PM move; check storage & temperature anomalies |
| Election-PM ↑ → rotation | The rotation is **scheduled & pre-positioned**; the "move" is convergence, not new info | No timing edge once results print; only the bot-dominated count window is tradeable |
| ANY PM-leads-asset claim | The PM **underreacts** (0.64-for-1) and is worse in thin markets — your "lead" may be illusory PM lag or a thin-market artifact | Require the PM signal to be in a *liquid* market and to *precede* the public wire, else assume no lead |

---

## Closing assessment

The mechanism map (§2) is well-supported and reliable as a directional reference. The **trading edge** is narrow and
mostly **negative**: the cleanest-mechanism events (Fed, elections) are priced in seconds (no PM lead); the only
plausible-lead regimes are **(i) geopolitical event-timing** carried by private flow (rare, confounded, legally
sensitive) and **(ii) slow proxy equities (MSTR/COIN) lagging a crypto-binary resolution**. This converges with the
project's prior internal conclusion (Polymarket latency/wedge lanes KILLed; equity-TAA the surviving edge):
**use Polymarket as a real-time, machine-readable macro-event NOWCAST to inform a trade in the correlated *asset*,
with a mandatory disconfirmer from §6 — not as a thing to arbitrage against itself.** Every (event × asset × venue)
candidate in §3–§4 must clear the deterministic Gate on its own BRUT data before any capital. The conviction lane
this note backs is therefore **propose-only and human-armed by construction**.

---

*Source-quality note: peer-reviewed / central-bank sources anchor every §2 mechanism (ECB, Fed/NBER, AER, JoF, JEP,
CEPR, IEA, EIA, Chicago Fed). Financial-press sources (Bloomberg, CBS/60 Minutes, NPR, CoinDesk, Morgan Stanley,
CFA Institute) carry event-specific magnitudes and the insider-trading evidence, flagged where they assert a claim a
peer-reviewed source does not. Asset-manager / data-vendor sources (US Funds, CoinGlass, AllianceBernstein) are
down-weighted. The single weakest claim — copper's recession lead — is flagged as a practitioner heuristic.*
