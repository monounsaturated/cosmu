# Cross-Asset Correlation & Event→Asset Library

**Date:** 2026-06-29 · **Type:** durable reference (not a strategy) · **Consumers:** the LLM/Polymarket conviction lane (`cosmu/correlate/`, `cosmu/conviction/`) and the operator.

**What this is.** A stored, cited lookup of well-established, *predictable* cross-asset correlations and event→asset linkages — the substrate the LLM strategies reason over when a trigger fires. Each linkage carries **direction · typical lead/lag · magnitude · reliability · regime caveats**. This is read-heavy reference knowledge; it does **not** author or arm strategies.

**Trust filter applied.** Every load-bearing number is sourced to a *reputation-to-lose* source: peer-reviewed finance (AER, JF, JFE, QJE, RFS, JFQA…), NBER/SSRN working papers by named academics, or central-bank/IMF/BIS/Fed research. Practitioner sources (AQR, J.P. Morgan, ING, CME, LPL) are used only as **corroboration** and flagged inline. Finfluencer / course-seller content was searched and **discarded**. A handful of primary PDFs (some IMF/BIS/SSRN) return 403 to automated fetch; those figures were taken from the same documents' indexed abstracts or the publishers' snippets and cross-checked — landing-page URLs given for manual verification.

---

## 0. How to use this library (read first)

The conviction lane has **no latency edge** — it trades hours-to-days. Two rules follow directly from the literature and govern everything below:

1. **The headline/most-liquid asset prices an event in seconds-to-minutes. That reaction is NOT capturable.** The exploitable drift lives in the **economically-linked, less-salient, less-liquid second-order asset** that requires a *mental model* to connect to the trigger. This is the precise shape of the Polymarket→correlated-asset thesis (Hong & Stein 1999; Cohen & Frazzini 2008; Andersen-Bollerslev-Diebold-Vega 2003).

2. **Sign is regime-dependent for several headline linkages. Never assume a fixed sign — condition on the regime first.** Three documented sign/strength breaks are load-bearing:
   - **Stock ↔ bond correlation** flipped negative→positive in mid-2021/2022 (inflation shocks now dominate growth shocks). Whether "risk-off" means bonds *rally* or *sell off* is itself regime-dependent.
   - **Crypto ↔ equity correlation** flipped ≈0 → strongly positive in 2020 (COVID/liquidity regime).
   - **Gold ↔ real-rates** did not flip sign but its *strength collapsed* 2022–2024 (central-bank buying overrode the real-rate model).

**Three durability filters** before the lane sizes any linkage (Shleifer-Vishny 1997 + McLean-Pontiff 2016):
(a) does it require a *cross-domain inference* most participants won't make? (b) does the lagging leg sit in a *less-liquid / segmented* asset? (c) is there a *structural flow/attention mechanism*, not just a statistical correlation? If yes to all three the drift is durable — then **haircut any published in-sample alpha by ~50%** (post-publication decay) and re-check it clears current fees out-of-sample.

---

## 1. MASTER LOOKUP TABLE — trigger → asset → direction · lag · magnitude · reliability

Reliability grades reflect *capturability by a no-latency, hours-to-days trader as of the mid-2020s*: **A** robust/structural/alive · **B** real but decayed or regime-conditional · **C** efficient/latency-dominated/not capturable (shown for context — these tell the lane where **not** to fish, and help sanity-check where Polymarket-implied levels should sit).

### 1a. Geopolitical & supply shocks

| Trigger | Asset | Dir | Lead/Lag | Magnitude | Reliability | Regime caveat |
|---|---|---|---|---|---|---|
| Genuine Hormuz / physical oil-supply disruption | Brent/WTI | ↑ | mins-hrs to price; premium **persists days-weeks while strait impaired** | Hormuz ≈ 20 mbd (~20% of liquids, >25% seaborne oil). 2026 episode: Brent +55% over ~4 wks | **B+** (one-directional when supply genuinely removed) | premium decays fast on de-escalation; *threat* ≠ *closure* |
| Oil ↑ | Energy equities (XLE) | ↑ | near-contemporaneous + some multi-day underreaction | high beta; energy CARs positive while broad equities fell (R-U 2022) | **B** (cleanest 2nd-order link) | refiners diverge (crack spreads); demand-destruction narrative caps it |
| Oil ↑ | 5y/10y inflation breakevens | ↑ | **contemporaneous, daily** | corr ≈ 0.65 | **C** (efficient, too fast) | decouples on recession/real-rate narrative |
| Geopolitical *risk/fear* (GPR index, no supply hit) | Oil | **↓** | mins-hrs | 1-SD GPR → oil ~−7% (trough ~3mo) | B | **SIGN TRAP: fear lowers oil; only physical disruption raises it** |
| Geopolitical threat / war onset | Broad equities (SPX) | ↓ then **mean-reverts** | selloff days; **recovery weeks-months** | S&P ~−3% impact, back to baseline ~3mo; "threats > acts" (act often a local bottom) | **A** (the fade is the most robust GPR result) | extends only if shock is systemic / physical-supply / recession-trigger |
| War / escalation | Gold | ↑ | mins-hrs | episodic safe-haven, conditional | B | not a monthly-dependable haven; fast to price |
| Surprise OPEC+ **cut** | Oil | ↑ | announcement day **+ documented day-AFTER drift** | only the *surprise* moves price; asymmetric | **B+** (day-after drift = rare capturable hrs-days edge) | a widely-expected cut is a non-event |
| OPEC+ **hike**/quota increase | Oil | ↓ | announcement day | much weaker / often insignificant | C+ | asymmetry: hikes underwhelm vs cuts |
| Sanctions on high-share producer | That commodity (palladium ~40%, nickel, wheat ~28-30%, crude) | ↑ | impact + **persistent** (supply physically removed) | palladium ATH $3,442; nickel +60% 1-day; wheat +>50% in 3wk | **B+** directional | **two killers:** exchange intervention can cancel fills (LME nickel 2022); rerouting mean-reverts spikes over months (wheat) |

### 1b. Macro events / data surprises (surprise = actual − consensus)

| Trigger | Asset | Dir | Lead/Lag | Magnitude | Reliability | Regime caveat |
|---|---|---|---|---|---|---|
| FOMC dovish surprise (−25bp unanticipated) | S&P 500 | ↑ | instant + drift | **~+1% per 25bp surprise** (mostly via risk premium) | **A** (cleanest single number) | sign/size stable |
| FOMC hawkish | 2y / 10y UST | ↑ | instant (≤30 min) | target factor drives 2y; path/guidance factor drives 10y & equities | A | — |
| FOMC hawkish (real rate ↑) | Gold | ↓ | instant + drift | ~−3.4% real gold per +1pp expected 10y real-rate shock | B+ | inverse-real-rate is the anchor |
| **Pre-FOMC** (no news) | S&P 500 | ↑ | **−24h to 0 (ex-ante)** | **~+49bp in the 24h before** scheduled FOMC (1994-2011) | **B** (partly faded post-2011 publication) | calendar-timed, not event-reaction |
| Post-FOMC target change | 10y UST | drift toward eventual move | **day-1 ~1.7bp → ~14bp by ~50 days** | flow-driven (funds slowly sell duration) | **B+** (near-ideal slow-trader linkage) | — |
| CPI hot (inflation ↑ surprise) | 2y/10y UST | ↑ | instant | 10y can jump >10bp; **sensitivity rose sharply 2021-23** | A | — |
| CPI hot | S&P 500 | ↓ | instant | asymmetric: disinflation rallies > inflation sells off | B (regime) | "good news = bad news" flips with cycle |
| NFP strong (jobs ↑ surprise) | 10y UST (real rates) | ↑ | instant | employment report a top mover; >10bp possible | A | — |
| NFP strong | S&P 500 | regime-dependent | instant | — | **C (regime-flipping)** | expansion: good=good; late-cycle/inflation: good=bad |
| ECB hawkish | EUR/USD, Bunds | ↑ | instant | two windows: decision vs press-conf; QE-surprise half-life ~1yr | A | Fed→world ≫ ECB→US (ECB is 2nd-order for US assets) |
| Yield-curve inversion (10y-3m) | recession / fwd equity | recession ↑ | **12-18 month lead** | spread=0 → ~25% recession prob 12m out; >+1.2pp → <5% | **B** (strong but few obs, long lead, recent false positive) | a *prior*, not a timing trigger |
| Any single macro surprise | whole risk complex (equities/credit/EM-FX/carry vs USD/JPY/CHF/gold/UST/VIX) | risk-on/off co-move | instant | one "global factor" | A (co-movement); direction regime-set | — |

### 1c. Structural cross-asset linkages (commodity ↔ equity ↔ FX ↔ crypto)

| Linkage | Dir | Lead/Lag | Magnitude | Reliability | Regime caveat / SIGN FLIP |
|---|---|---|---|---|---|
| Oil → energy equities (XLE/XOM/CVX) | **+** | contemporaneous | oil-price beta ≈ **+0.31** (Sadorsky) | **A** (sign stable) | magnitude time-varies; sector sign never flips |
| Oil → airlines / transports | **−** | long-run/coincident; weak intraday | fuel ≈ 19-35% of opex | B | sign swamped when oil-up = demand-boom; hedging mutes |
| Gold → real rates (10y TIPS) | **−** | contemporaneous | corr ≈ **−0.82** (1997-2012, Erb-Harvey, *they warn it may be spurious*) | **WAS A, now BROKEN** | **strength collapsed 2022-24** (corr →~0.03-0.07) — central-bank buying |
| Gold → USD (DXY) | **−** | contemporaneous | corr ≈ −0.5 to −0.8 | B+ (mechanical) | both rally together in acute panic |
| Copper → global growth | **+** | copper **leads** (Granger) | corr to IP ≈ 0.65-0.75 | B | ~55-60% China demand → reads China stimulus, not "global" |
| Copper/gold ratio → 10y yield | **+** | mostly **coincident** | corr up to ~0.85 (2000-21) | **B-, DECOUPLED post-2020** | "Gundlach signal" stopped working; dollar now stronger 10y driver |
| DXY → EM equities/FX | **−** | coincident; $ leads in stress | +1% broad-$ → EM equities **−0.21 to −0.28%/wk** (BIS) | **A** (priced global-risk factor) | beta *more* negative in stress; use broad $ not bilateral |
| DXY → commodities | **−** | $ leads ~18-24 days | index corr ≈ −0.56 | B | **SIGN FLIPPED 2021-22** ($ and commodities rose together) |
| DXY → Bitcoin | − (loose) | time-varying | 30d corr hit −0.90 but also flipped + | **C (weak/unstable)** | frequently decouples; do not over-size |
| BTC → risk assets (SPX/Nasdaq) | **+ (post-2020)** | coincident (common macro factor) | corr **0.01 (2017-19) → 0.36 (2020-21)** (IMF), peaks ~0.9 | **B** (regime-dependent) | **SIGN FLIP ≈0→+ in 2020** |
| BTC → global liquidity / real rates | + liquidity / − real rates | **liquidity LEADS BTC by weeks** | high-beta to M2 | B (conditional) | strongest in macro-dominated regimes |
| **Stock ↔ bond returns** | **SIGN-FLIPPING** | coincident; *driver* is the state var | −0.3 to −0.5 (2000s-10s) → **+0.5 (2022)** | **A as a state-conditional relation** | **FLIP negative→positive mid-2021/22** (inflation shocks dominate) |
| VIX ↔ equities | **−** | **contemporaneous** | daily corr ≈ −0.73 to −0.80, asymmetric | **A (most stable in finance)** | tightens to −0.85+ in stress; ~never flips |
| Credit spreads ↔ equities | **−** | credit leads on bad news/macro (GZ); equity leads CDS daily | GZ excess-bond-premium leads activity months-1yr | B (regime-conditional) | single-name CDS lead **weakened post-2009** |

### 1d. Event-study reliability — which diffusion is slow enough to capture

| Linkage / event → asset | Diffusion speed | Capturable by slow (hrs-days) trader? | Reliability | Citation |
|---|---|---|---|---|
| Macro surprise → most-liquid FX/rate future | seconds-~1 min | **NO** | C | ABDV (2003) |
| Earnings surprise → the announcing **large-cap** (PEAD) | now intraday/day-1 (since ~2006) | **NO** for large caps | C (B− microcap only) | Bernard-Thomas (1989); Martineau (2022) |
| News on a **customer** firm → its **supplier** stock | **~1 month** drift | **YES** (canonical slow-trader edge) | B+ (decayed ~50%) | Cohen-Frazzini (2008); Menzly-Ozbas (2010) |
| Shock to an **industry** → broad market / linked industries | **up to ~2 months** | **YES** | B | Hong-Torous-Valkanov (2007) |
| Commodity move → **non-direct-exposure** equities | **~1 month** | **YES** | B | Driesprong-Jacobsen-Maat (2008) |
| Fed target change → **long-end Treasuries** (post-FOMC drift) | day-1 ~1.7bp → ~14bp by ~50d | **YES** (flow-driven) | B+ | Brooks-Katz-Lustig (2018/19) |
| Big/liquid stocks → small/illiquid (size lead-lag) | ~1 week | partial (microstructure, decayed) | C+ | Lo-MacKinlay (1990) |
| Cross-sectional momentum (3-12m) | months | **YES** (position-horizon, not fast) | B+ | Jegadeesh-Titman (1993) |
| Long-horizon overreaction → reversal | 3-5 years | **NO** (wrong horizon) | C for this lane | De Bondt-Thaler (1985) |
| Any published anomaly, generically | — | assume **~58% weaker post-publication** | discount all | McLean-Pontiff (2016) |

### 1e. The reverse — asset/macro move → prediction-market contract

| Trigger / asset move | Related PM contract | PM leads or lags? | Exploitable for slow trader? | Reliability | Citation |
|---|---|---|---|---|---|
| Spot BTC moves on 24/7 CEX | PM short-term crypto-price contract | **PM LAGS** spot (secs-mins) | **LOW for us** — HFT turf + Polymarket fee-walled (~3.15% near 50c) | lag real but captured by faster players | Finance Magnates 2026; CoinDesk 2026 |
| Referendum/election count overnight | PM outcome contract vs FX/futures | **PM LEADS** financial markets by mins-~1hr | MODERATE in principle (window minutes; needs both venues live) | high (cointegrated: Scottish'14, Brexit'16, US'16) | Auld & Linton (2019, 2022) |
| News/poll shock to election odds | IEM / vote-share contract | **PM LEADS polls** (days-wks) | LOW direct (no liquid correlated asset); clean nowcast | high (IEM beat polls 74% of 964 polls) | Berg-Nelson-Rietz (2008) |
| Macro release (NFP, ISM, claims) | economic-indicator PM contract | ~coincident; rivals pro forecasters | LOW as arb; useful as forecast input | mod-high | Snowberg-Wolfers-Zitzewitz (2012) |
| New public info hits a **fresh/early-life** contract | any PM contract early in lifecycle | **PM LAGS — underreacts** | **HIGH (our lane)** — mispricing concentrated at contract birth | good (478M Polymarket trades) | Reichenbach & Walther (2025) |
| Cross-venue divergence (Polymarket vs Betfair/Kalshi) | duplicate event contracts | one venue LAGS the other (24c vs ~50c, "hours to catch up") | **MOD-HIGH (our lane)** — slow enough for non-HFT | good (~$40M realized cross-market arb) | CoinDesk 2026; Saguillo et al. (2025) |
| Weekend/overnight while crypto trades 24/7 | thin PM contracts | PM **stale/thin** | **MODERATE (our lane)** | structural (quant desks target it) | CoinDesk 2026; Dubach (2026) |
| Large whale enters a thin contract | targeted PM contract | PM **distorts**, usually mean-reverts | **NEGATIVE/RISK** — don't read whale price as signal | manipulation usually transient & costly | Rothschild & Sethi (2016) |
| Disputed resolution / oracle vote | Polymarket UMA-resolved contract | N/A — **settlement risk** | **NEGATIVE** — resolution can be contested even when price was right | known failure mode | CoinDesk 2025 (Zelenskyy-suit) |

---

## 2. Cited notes by theme

### 2.1 Geopolitical & supply shocks

**The master caveat — a SUPPLY shock and a RISK shock move oil OPPOSITE ways.** Generic geopolitical fear is *deflationary* for oil and risk-off for equities; an actual physical supply disruption is *inflationary* for oil. A 1-SD rise in the GPR index lowers stocks ~3% on impact **and lowers oil ~7%** by a 3-month trough — explicitly against the naïve "geopolitics → oil up" view (Caldara & Iacoviello, *Measuring Geopolitical Risk*, AER 2022 / Fed IFDP 1222, https://www.federalreserve.gov/econres/ifdp/files/ifdp1222.pdf). The oil↔equity sign depends on the *shock type*: supply-shock effect on stocks is weak/insignificant; precautionary/speculative-demand shocks push oil up while stocks fall (Kilian & Park, *The Impact of Oil Price Shocks on the U.S. Stock Market*, Int. Econ. Review 2009, https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-2354.2009.00568.x). **Before trading any "geopolitics" thesis, classify the trigger: physical supply hit (→ long oil/energy) vs generic fear (→ oil can FALL; the reliable trade is the equity *fade*).**

**The equity selloff mean-reverts ("buy the invasion").** This is the single most robust GPR finding and the cleanest geopolitical edge for a slow trader. S&P ~−3% on impact, back to baseline in ~3 months; the adverse effect is driven by **threats, not acts** — so the selloff peaks at/before onset and the act itself is frequently a local bottom (Caldara & Iacoviello 2022; Salisu et al., *Finance Research Letters* 2022, https://www.sciencedirect.com/science/article/abs/pii/S1544612322004160). Severity-graded: international military conflict is the worst sub-type — EM equities ~−5pp monthly, sovereign spreads +30bp (AE) / +45bp (EM) (IMF GFSR Apr 2025 Ch.2, https://www.imf.org/en/publications/gfsr/issues/2025/04/22/global-financial-stability-report-april-2025). Russia-Ukraine cross-asset event study (Feb 21-28 2022): crude & palladium +~10%, equities −~5%, energy-firm CARs positive (St. Louis Fed *Review* Oct 2022, https://www.stlouisfed.org/publications/review/2022/10/21/financial-market-reactions-to-the-russian-invasion-of-ukraine). Practitioner corroboration: post-WWII conflicts, S&P avg drawdown −4.7%, bottom ~19 days, recovery ~42 days (LPL Financial — corroborating only).

**Gold safe-haven** on war/escalation is real but *episodic/conditional*, not a monthly-dependable haven; futures show a stronger effect than spot (Baur & Smales 2020; *Resources Policy* 2021, https://ideas.repec.org/a/eee/jrpoli/v70y2021ics030142072030903x.html).

**OPEC** is one of the cleaner setups: only the *surprise vs expected* component moves price (exactly what a "will OPEC+ cut?" PM prices), cut announcements are the statistically significant ones (asymmetry — hikes underwhelm), and there is a documented **day-after drift** — a genuine hours-to-days underreaction (Energy Economics/Policy event studies, https://www.sciencedirect.com/science/article/abs/pii/S0301421515302007; IMF WP 2022/183, https://www.elibrary.imf.org/view/journals/001/2022/183/article-A001-en.xml).

**Sanctions** are physical-supply shocks targeted at specific commodities — the most one-directional and *persistent* chain (a sanctioned barrel/ton doesn't return on a ceasefire rumor). Match the commodity to the producer's actual share: palladium (Russia ~40% — ATH $3,442/oz Mar 2022), nickel (+60% one day, briefly >$100k/t), wheat (Russia+Ukraine ~28-30% of exports, +>50% in 3 weeks). **Two killers:** exchange intervention can *cancel* your fill (LME suspended and annulled nickel trades Mar 2022 — https://www.lme.com/en/news/russian-sanctions), and rerouting/substitution mean-reverts even sanction spikes over months (wheat returned to ~2-3% above pre-war within months; Chicago Fed Letter 2024/492, https://www.chicagofed.org/publications/chicago-fed-letter/2024/492).

**EIA chokepoint facts:** Strait of Hormuz carries ~20 mbd (~20% of global liquids, >25% of seaborne oil, ~1/5 of LNG) — https://www.eia.gov/todayinenergy/detail.php?id=61002.

### 2.2 Macro events / data surprises

**The bulk of the announcement reaction is uncapturable.** High-frequency identification shows the price adjustment to a surprise completes within a 30-minute window, often seconds (Kuttner, *Monetary policy surprises and interest rates*, JME 2001, https://www.sciencedirect.com/science/article/abs/pii/S0304393201000551; ABDV 2003 below). Asset prices need **two FOMC factors** — a "target" (decision) factor driving the short end and a "path"/forward-guidance factor (the statement) driving longer yields and most of the equity reaction (Gürkaynak, Sack & Swanson, *Do Actions Speak Louder Than Words?*, IJCB 2005, https://conference.nber.org/confer/2005/mes05/sack.pdf). The cleanest single equity number: an unanticipated **−25bp → ~+1% on broad indexes**, mostly via the equity risk premium (Bernanke & Kuttner, *What Explains the Stock Market's Reaction to Federal Reserve Policy?*, JF 2005, https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2005.00760.x). Caveat: a "Fed information effect" confounds pure-policy interpretation (Nakamura & Steinsson, QJE 2018, https://academic.oup.com/qje/article-abstract/133/3/1283/4828341), though Bauer & Swanson (2023) attribute much of it to both sides responding to prior public news.

**Capturable drift (the conviction-lane gold):**
- **Pre-FOMC drift** — equities earn ~+49bp in the 24h *before* scheduled FOMC announcements (1994-2011), ~80% of the period's equity premium (Lucca & Moench, *The Pre-FOMC Announcement Drift*, JF 2015, https://www.newyorkfed.org/research/staff_reports/sr512.html). **Decay flag:** weakened/reversed after the 2011 publication ("The disappearing pre-FOMC announcement drift," *Finance Research Letters* 2021, https://www.sciencedirect.com/science/article/abs/pii/S1544612320315956).
- **Monetary momentum** — directional drift begins ~25 days *before* the meeting and continues to ~+4-4.5% by ~15 days *after* (pre- and post-announcement underreaction); pre-meeting returns predict the surprise (Neuhierl & Weber, NBER w24748, https://www.nber.org/system/files/working_papers/w24748/w24748.pdf).
- **Post-FOMC bond drift** — after a target change the 10y moves only ~1.7bp day-1 of an eventual ~14bp move over ~50 days; mechanism is mutual-fund investors slowly selling duration while arbitrageurs absorb supply (Brooks, Katz & Lustig, NBER w25127, https://www.nber.org/papers/w25127). A near-ideal multi-week, no-latency linkage.

**CPI / NFP magnitude & method:** the canonical real-time framework finds surprises cause conditional-mean jumps *within minutes*, bad news > good news (Andersen, Bollerslev, Diebold & Vega, *Micro Effects of Macro Announcements*, AER 2003, https://www.aeaweb.org/articles?id=10.1257/000282803321455151). For real-activity news (NFP) the long-yield sensitivity is concentrated in *real* rates; an employment report can move the 10y >10bp (Gürkaynak, Sack & Swanson, *Sensitivity of Long-Term Interest Rates to Economic News*, AER 2005, https://www.aeaweb.org/articles?id=10.1257/0002828053828446). Equity sensitivity to CPI rose sharply 2021-23; the SPX response is asymmetric (disinflation rallies > inflation sells off).

**ECB** — the EA-MPD event-study database documents intraday EUR, Bund, periphery-spread and Euro Stoxx responses across a decision window and a press-conference window; QE-surprise effects are long-lived (~1yr half-life) (Altavilla et al., *Measuring Euro Area Monetary Policy*, JME 2019, https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2281~3303fd281b.en.pdf). **Fed→world dominates** (Rey's Global Financial Cycle); ECB is a second-order input for US assets — don't over-weight it in a US-asset thesis.

**Recession signal** — the 10y-3m spread is the best single recession forecaster ~12-18 months ahead; NY Fed probit: spread >+1.2pp → <5% prob, flat → ~25% 12m out (Estrella & Mishkin, NY Fed Current Issues 1996/98, SSRN mirror https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1001228; Fed FEDS note https://www.federalreserve.gov/econres/notes/feds-notes/predicting-recession-probabilities-using-the-slope-of-the-yield-curve-20180301.html). **Caveat:** 12-18m lead is far too long for short-dated PM contracts, few independent observations, and the 2022-24 inversion notably did *not* produce a near-term NBER recession on the historical lag. Use as a long-horizon *prior*, never a timing trigger.

**One global factor** — a single surprise propagates through one risk-on/risk-off factor across equities/credit/EM-FX/carry vs USD/JPY/CHF/gold/UST/VIX (KC Fed RORO index RWP24-12, https://www.kansascityfed.org/documents/10594/rwp24-12charistedmanlundblad.pdf; IMF WP/08/85, https://www.imf.org/external/pubs/ft/wp/2008/wp0885.pdf). **Beta is paid on announcement days:** >60% of the equity risk premium is earned on ~13% of days (Savor & Wilson, *Asset Pricing: A Tale of Two Days*, JFE 2013, https://www.sciencedirect.com/science/article/abs/pii/S0304405X14000890). **"Good news = bad news" flips with the regime** — rising-unemployment news is good for stocks in expansions, bad in contractions; condition the equity sign on the cycle before trading it (Boyd, Hu & Jagannathan, JF 2005, https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2005.00742.x).

**BTC is mostly noise at the print level** — only ~1-in-10 macro announcements produces a significant BTC response vs ~half for traditional assets; liquidity/real-yields matter more than the print (NY Fed *The Bitcoin-Macro Disconnect* SR1052, https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf).

### 2.3 Structural cross-asset linkages

**Lean-on (sign ~never flips):** VIX↔equities, energy-equities↔oil, gold↔USD, DXY↔EM-equities.
- **VIX ↔ S&P** — daily corr ≈ −0.73, contemporaneous, asymmetric (down-vol > up-vol); the most stable relation in finance. A coincident fear *gauge*, NOT a directional forecaster (Hibbert, Daigler & Dupoyet, JBF 2008, https://faculty.fiu.edu/~dupoyetb/return_vola.pdf; Whaley, *Understanding the VIX*, JPM 2009; theory: Bekaert & Wu, RFS 2000).
- **Oil → energy equities** — oil-price beta ≈ +0.31 (Sadorsky, *Risk factors in stock returns of Canadian oil and gas companies*, Energy Economics 2001, https://www.sciencedirect.com/science/article/abs/pii/S0140988300000724). The *broad market's* oil correlation flipped from ~0 pre-2008 to +0.39 post-2008 (financialization; Bernanke, Brookings 2016) — but **energy-sector stocks never flip** (they are long the commodity).
- **DXY as a global risk factor** — +1% broad-dollar → EM equities −0.21 to −0.28%/wk; the *broad* dollar dominates and knocks out bilateral-FX significance; betas more negative in stress (Bruno, Shim & Shin, BIS WP 1000, 2022, https://www.bis.org/publ/work1000.pdf). Dollar-appreciation shocks *predict* EMDE downturns (Obstfeld & Zhou, *The Global Dollar Cycle*, NBER w31004 / BPEA 2023, https://www.nber.org/system/files/working_papers/w31004/w31004.pdf). Mechanism: the dollar proxies the shadow price of global-bank leverage (Avdjiev, Du, Koch & Shin, BIS WP 592 / AER:Insights 2019, https://www.bis.org/publ/work592.pdf; Bruno & Shin, JME 2015).

**Regime-conditional — REQUIRE a regime check before signing:**
- **Stock ↔ bond — the big sign flip.** Growth/real shocks → negative correlation (bonds hedge); inflation/monetary shocks → positive (both fall together). The US equity-bond return correlation switched to positive in mid-2021 — "one has to go back to the 1980s" — driving a higher term premium and yields (Campbell, Pflueger & Viceira, *Macroeconomic Drivers of Bond and Equity Risks*, JPE 2020, https://www.nber.org/papers/w20070; BIS Quarterly Review Dec 2023, https://www.bis.org/publ/qtrpdf/r_qt2312v.htm). It's the *relative volatility of growth vs inflation shocks* — not the inflation level — that sets the sign; 2022 SPX-AGG corr spiked to +0.50 (AQR, *A Changing Stock-Bond Correlation*, JPM 2023 — corroborating, https://www.aqr.com/Insights/Research/Journal-Article/A-Changing-Stock-Bond-Correlation). **The state variable to watch is realized inflation-vs-growth shock volatility.**
- **Crypto ↔ equity — the documented level/sign jump.** BTC-S&P daily corr 0.01 (2017-19) → 0.36 (2020-21); BTC vol explained ~1/6 of S&P vol in the pandemic (Adrian, Iyer & Qureshi, IMF, *Crypto Prices Move More in Sync With Stocks*, Jan 2022, https://www.imf.org/en/blogs/articles/2022/01/11/crypto-prices-move-more-in-sync-with-stocks-posing-new-risks; IMF GFS Note 2022/01). The crypto cycle co-moves with risk assets, driven by US monetary policy (IMF WP/2023/163, https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023163-print-pdf.pdf). Range is ~0 to ~0.9 within 18 months — never assume a stable beta; **global liquidity LEADS BTC by weeks** (don't align contemporaneously).
- **Gold ↔ real rates — broke 2022-24.** The core real-rate model (corr ≈ −0.82, 1997-2012; Erb & Harvey, *The Golden Dilemma*, NBER w18706 / FAJ 2013, https://www.nber.org/system/files/working_papers/w18706/w18706.pdf — *the authors warn this may be spurious*) **broke**: rolling corr fell from ~0.84 (2005-21) to ~0.03-0.07 (2022+) as gold hit records despite high real yields, driven by record central-bank buying (>1,000 t/yr 2022-24). **Any gold model now needs a central-bank-demand / de-dollarization term** (Chicago Fed Letter 464, https://www.chicagofed.org/publications/chicago-fed-letter/2021/464; RBC/JPM PB on the regime change).
- **DXY → commodities** sign flipped 2021-22 ($ and commodities rose together; IMF WP 2023/215; BIS Bulletin 74, https://www.bis.org/publ/bisbull74.pdf). **Copper/gold → yields** decoupled post-2020 (CFA Institute 2023, https://rpc.cfainstitute.org/blogs/enterprising-investor/2023/is-the-copper-gold-ratio-a-leading-indicator-on-rates; academic: only short, largely coincident info — Parnes, NAJEF 2023). **Copper as "Dr. Copper"** is ~55-60% a China-demand read, not synchronized global growth (CME; J.P. Morgan — corroborating).

**Credit ↔ equity** — the highest-conviction form is the **aggregate excess-bond-premium / GZ spread as a slow macro leading indicator of equity-drawdown risk** (months-1yr lead; Gilchrist & Zakrajšek, *Credit Spreads and Business Cycle Fluctuations*, AER 2012, https://www.aeaweb.org/articles?id=10.1257%2Faer.102.4.1692), NOT single-name CDS as a fast equity signal (that lead weakened post-2009; OFR WP 24-04, https://www.financialresearch.gov/working-papers/2024/07/17/do-credit-default-swaps-still-lead/).

### 2.4 Event-study reliability — what a slow trader can actually capture

**Theory tying it together:** information diffuses *gradually* across boundedly-rational "newswatchers," so prices underreact short-run (→ momentum, capturable) and overreact long-run (→ reversal); diffusion is slowest where information is least salient and hardest to interpret — i.e. the second-order linked asset, not the headline (Hong & Stein, *A Unified Theory of Underreaction, Momentum Trading, and Overreaction*, JF 1999, https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00184). **This is the theoretical license for the Polymarket→correlated-asset lane.**

**The core literature for this lane — gradual diffusion across economically linked assets:**
- A shock to a **customer** firm predicts the **supplier** stock over the following month (>150bp/mo in-sample), because limited attention means investors don't connect linked firms (Cohen & Frazzini, *Economic Links and Predictable Returns*, JF 2008, http://www.econ.yale.edu/~shiller/behfin/2006-04/cohen-frazzini.pdf). Decay: replications find the spread roughly halved (~1.58%→~0.79%, https://arxiv.org/pdf/2301.11394). Generalized to supplier/customer *industries* via market segmentation (Menzly & Ozbas, JF 2010).
- Certain industries lead the broad market by **up to ~2 months** (Hong, Torous & Valkanov, *Do Industries Lead Stock Markets?*, JFE 2007, http://www.columbia.edu/~hh2679/industry-12-05-05.pdf).
- Oil predicts **next-month** returns in *non-oil* stocks only — oil stocks price the move immediately; the asset one inference away drifts (Driesprong, Jacobsen & Maat, *Striking Oil*, JFE 2008).

**What's dead / efficient (don't target):** large-cap PEAD has been non-existent since ~2006 (Martineau, *Rest in Peace Post-Earnings Announcement Drift*, Critical Finance Review 2022, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607); macro surprises price into FX/rate futures within ~1 min (ABDV 2003); long-horizon reversal is a 3-5yr horizon (De Bondt & Thaler, JF 1985).

**Why durable links stay durable:** mispricing persists exactly where arbitrage is hardest — illiquid names, high idiosyncratic vol, segmented markets, situations needing a non-obvious model (Shleifer & Vishny, *The Limits of Arbitrage*, JF 1997, https://web.stanford.edu/~piazzesi/Reading/ShleiferVishny1997.pdf). **Discount everything for publication:** returns 26% lower OOS, 58% lower post-publication — haircut any published alpha ~50% (McLean & Pontiff, *Does Academic Research Destroy Stock Return Predictability?*, JF 2016, https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365).

### 2.5 The reverse — asset/macro move → prediction market

**Prediction markets are well-calibrated, approximately efficient aggregators that beat polls — NOT a free lunch** (Wolfers & Zitzewitz, *Prediction Markets*, JEP 2004, https://www.nber.org/papers/w10504; Arrow et al., *The Promise of Prediction Markets*, Science 2008, https://eriksnowberg.com/papers/science.pdf; Snowberg, Wolfers & Zitzewitz, NBER w18222). IEM beat 964 polls 74% of the time over 5 elections (Berg, Nelson & Rietz, *Int. J. Forecasting* 2008, https://www.biz.uiowa.edu/faculty/trietz/papers/long%20run%20accuracy.pdf).

**Lead/lag is horizon-dependent:**
- **vs polls/media/FX (day-to-~1hr scale): PM LEADS.** Brexit night: Betfair moved to "Leave" ~3am, FX didn't fully adjust until ~4am, BBC called 4:40am — betting led FX by ~1hr, exploitable gap up to ~7% in sterling; cointegrated across Scottish'14/Brexit'16/US'16 (Auld & Linton, *Int. J. Forecasting* 2019; Cambridge WP 2022). PM prices reveal exactly when news was incorporated (Snowberg, Wolfers & Zitzewitz, *Partisan Impacts on the Economy*, QJE 2007, https://www.nber.org/papers/w12073).
- **vs its own fundamental value (sub-minute → 15-min): PM LAGS / underreacts** — Kalshi midpoint moves ~0.64-for-1 on a 1-min benchmark change; gap predicts ~2.0pp drift over 5 min, worse in low liquidity (Angelini & De Angelis, arXiv:2606.07811, 2026). **But this fast lane is HFT-contested and Polymarket fee-walls it** (dynamic taker fees ~3.15% near 50c; Finance Magnates 2026) — consistent with COSMU's earlier KILL of the fast-crypto latency lane.

**The defensible slow edge = segmentation, not speed.** Across 478M Polymarket trades, "inaccuracies primarily occur **early in a contract's lifecycle** and close to resolution — markets require time to incorporate new information" (Reichenbach & Walther, SSRN 5910522, 2025, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5910522). Cross-venue/cross-market lag is slow enough for a non-HFT trader (~$40M realized cross-market arb; Saguillo et al., arXiv:2508.03474; "Next UK PM" 24c on Polymarket vs ~50c on Betfair, "took hours to catch up" — CoinDesk, June 2026, https://www.coindesk.com/business/2026/06/06/a-massive-hiring-wave-reveals-trading-firms-are-no-longer-viewing-polymarket-as-a-niche-betting-tool). Weekend/overnight thinness is structural (Dubach, arXiv:2604.24366). **Liquid markets are the boundary** — in liquid in-play markets discrete shocks are incorporated promptly (Croxson & Reade, *Economic Journal* 2014).

**Library warnings (failure modes):**
- **Favorite-longshot bias** — longshots systematically overpriced (Snowberg & Wolfers, JPE 2010, https://www.nber.org/papers/w15923); reconfirmed on Kalshi where **takers lose ~32% net, makers ~10%** (Bürgi, Deng & Whelan, UCD WP 2025/19, https://www.karlwhelan.com/Papers/Kalshi.pdf). A hard warning for any taker-side PM strategy.
- **Whale-pushed prices ≠ signal** — a single 2012 Intrade trader held a visible distortion ~2 weeks but lost ~$4-7M; manipulation usually mean-reverts but is conditional on thinness (Rothschild & Sethi, *J. Prediction Markets* 2016, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2322420; Hansen-Schmidt-Strobel 2004 found real manipulation in *thin* markets).
- **Resolution/oracle-capture risk** — Polymarket UMA token-holders can flip a resolution even when the price was right (CoinDesk, Zelenskyy-suit $160M, Jul 2025, https://www.coindesk.com/markets/2025/07/07/polymarket-embroiled-in-usd160m-controversy-over-whether-zelensky-wore-a-suit-at-nato). The *resolution* can be contested independent of the *price*.
- **Venue regulatory split:** Polymarket = offshore, USDC, UMA-resolved, CFTC-fined $1.4M (2022); Kalshi = onshore CFTC-regulated DCM (won KalshiEX v. CFTC, D.C. Cir. 2024).

**Net:** treat PM as a **nowcast / co-incident underreaction signal**, not a leading oracle or clean arb — re-confirming the stored prior.

---

## 3. SHORTLIST — most predictable, highest-conviction linkages for the Polymarket/LLM lane

Filtered for: stable/known direction, a lead/lag long enough for a non-latency maker (hours-to-days), a structural (not merely statistical) mechanism, and a plausible Polymarket contract to express it. Ranked by conviction.

1. **OPEC+ surprise production CUT → crude oil ↑ (+ energy equities), with a day-AFTER drift.** The surprise-vs-expected decomposition is exactly what an "Will OPEC+ cut at the next meeting?" PM prices; the documented day-after underreaction is a rare hours-to-days capturable edge. Asymmetric (hikes underwhelm). *Mechanism: physical supply + announcement underreaction.*

2. **Genuine physical supply disruption (Hormuz closure / sanctions on a high-share producer) → that commodity ↑, persistently.** One-directional and *persistent* (supply physically removed, unlike fear spikes). Express via the commodity/energy-equity and via PM contracts on the disruption's continuation. *Guardrails: classify supply-hit vs generic-fear (opposite oil sign); size for exchange-intervention risk; expect mean-reversion of fear-only spikes.*

3. **Geopolitical war/escalation equity selloff → FADE it over days-weeks ("buy the invasion").** The most robust GPR finding: S&P ~−3% on impact, recovers in ~3 months; threats > acts, so the act is often a local bottom. Express by fading PM/equity risk-off once the *act* (not threat) is realized. *Exception: systemic / physical-supply / recession-trigger shocks extend the drawdown.*

4. **FOMC monetary-policy surprise → the broad risk complex, with pre- and post-meeting drift.** Dovish −25bp surprise → ~+1% equities; plus pre-FOMC drift (24h before) and post-FOMC bond drift (~50 days). Express by mapping a Polymarket "Fed cut at next meeting?" probability shift onto the correlated risk complex (equities/gold/UST). *Guardrail: condition the equity sign on the regime ("good news = bad news"); pre-FOMC drift partly faded post-2011.*

5. **Asset/correlated move already happened → a FRESH or CROSS-VENUE-stale Polymarket contract that hasn't repriced.** The defensible slow PM edge: mispricing concentrates early in a contract's life and across venues (Polymarket vs Betfair/Kalshi "hours to catch up"), and in thin weekend/overnight contracts. *Guardrails: avoid the fee-walled HFT short-crypto lane; beware favorite-longshot overpricing, whale distortion, and UMA resolution risk; use PM as nowcast, propose-only, human-armed.*

---

## 4. Operational rules baked in for the LLM lane

- **Classify the trigger before signing:** supply-hit vs generic-fear (opposite oil sign); inflation-shock vs growth-shock regime (sets stock-bond sign); Fed/liquidity-dominated vs crypto-native (sets crypto-equity correlation); central-bank-gold-buying regime (overrides gold-real-rate model).
- **Never trade the headline asset's instant reaction** — target the second-order, less-liquid, economically-linked asset with a slow drift.
- **Lead/lag discipline (avoid leakage):** global liquidity *leads* BTC (weeks); VIX, copper/gold, breakevens are *coincident* (not forecasters); credit leads equity only at the GZ-aggregate or on bad-news single names.
- **Haircut any published alpha ~50%** for post-publication decay and re-verify it clears *current* fees out-of-sample.
- **PM is a nowcast, not an oracle.** Edge = segmentation (early-life, thin, cross-venue), not speed. Propose-only; the deterministic Gate / human arms live.

---

*Sourcing caveat: load-bearing figures were captured from primary or reputation-bearing institutional sources (NBER/IMF/BIS/Fed/peer-reviewed journals) or the publishers' own snippets, not invented. Some primary PDFs return 403 to automated fetch; landing-page/DOI URLs are provided for manual verification. Practitioner sources (AQR, J.P. Morgan, ING, CME, LPL, RBC) are flagged inline and used only as corroboration, never as the sole source for a claim.*
