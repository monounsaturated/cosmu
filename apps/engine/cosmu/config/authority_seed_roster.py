# intent: the SEED ROSTER for the Authority lane — a WIDE net of X/Twitter accounts that post DIRECTIONAL asset
# calls, ready for the (local, keyed) voices/authority pass to SCORE. inputs: none (this IS the candidate list);
# outputs: SEED_ROSTER_FULL (every candidate) + SEED_ROSTER_FIRST10 (the cost-managed first batch to score).
# invariants: these are CANDIDATES, never asserted to have skill — each `why` is a falsifiable HYPOTHESIS written
# at ADD time, before any outcome is scored (the same anti-survivorship discipline as VOICE_PANEL). The whole
# point is to let the price-anchored scoreboard (Brier-skill vs base rate, echo-disconfirmed) decide who is good;
# we deliberately include unproven / "stupid" accounts and let the data speak. Casting a WIDE net is correct here.
#
# COST + KEY: every X voice is fetched via Grok LiveSearch and needs XAI_API_KEY (~$0.066/account/pass). This file
# does NOT auto-run and is NOT in the keyless VOICE_PANEL — it is an OPT-IN list the local pass reads explicitly:
#
#     from cosmu.config.authority_seed_roster import SEED_ROSTER_FIRST10
#     voices_pass(store, panel=SEED_ROSTER_FIRST10)   # score the cheap first batch only
#
# RESOLVABILITY CAVEAT (read before scoring non-crypto): claims only resolve where the entity maps to a bar
# symbol in cosmu.config.voices.ENTITY_BARS_SYMBOL, which today is CRYPTO-ONLY (BTC/ETH/SOL/...). So equity,
# macro and commodity accounts below will score `no_data` until ENTITY_BARS_SYMBOL + a venue (EODHD equities,
# etc.) are extended. The FIRST-10 is therefore all CRYPTO — the accounts whose calls resolve against existing
# bars TODAY — so the first xAI spend buys real scores, not no_data. See docs/research/authority-seed-roster-2026-06-29.md.

from __future__ import annotations

from cosmu.config.voices import Voice

# --------------------------------------------------------------------------------------------------------------
# FIRST-10 — score THESE first. All CRYPTO (resolve against existing bars), all ORIGINAL callers, biased to HIGH
# call-frequency (more scoreable claims per $0.066 pass) with a deliberate spread: reputation-to-lose names +
# one very-high-volume unproven + one bold-specific perma-caller. The scoreboard ranks them; we do not pre-judge.
# --------------------------------------------------------------------------------------------------------------
SEED_ROSTER_FIRST10: tuple[Voice, ...] = (
    Voice("@il_capo_of_crypto", "x", "very high-frequency, SPECIFIC BTC/ETH price-target (often short) calls — maximally falsifiable, ideal first test of whether bold specificity carries skill or is just loud"),
    Voice("@CryptoMichNL", "x", "near-daily BTC + major-alt level calls (Michael van de Poppe) — high cadence gives many scoreable claims; test if a prolific daily caller beats the base rate"),
    Voice("@ali_charts", "x", "very high-volume BTC/ETH/SOL signal posts (Ali Martinez) — quality unproven and that is the point: high claim count at fixed cost, let the Brier score decide"),
    Voice("@Pentoshi", "x", "frequent original BTC/alt directional calls with a public reputation — test whether a respected caller's foresight survives the base-rate control"),
    Voice("@CryptoDonAlt", "x", "regular BTC/ETH technical calls (DonAlt), reputation-to-lose — a lead candidate; falsified if his calls merely track price"),
    Voice("@RektCapital", "x", "BTC/ETH cycle + level calls — structured, original; test whether the halving/cycle framing leads the tape or narrates it"),
    Voice("@CryptoTony__", "x", "daily BTC/ETH/alt TA with explicit invalidation levels — high cadence, clean falsifiability"),
    Voice("@intocryptoverse", "x", "quantitative, measured BTC/ETH risk-metric calls (Benjamin Cowen) — low-hype original; a calibration candidate that should score well if the metric rewards foresight"),
    Voice("@WClementeIII", "x", "on-chain-driven BTC directional reads (Will Clemente) — a potential LEAD-LAG leader; the tripwire confirms or refutes whether on-chain framing precedes price"),
    Voice("@CredibleCrypto", "x", "frequent BTC/ETH/XRP TA calls — original, specific; second on-chain+TA candidate to widen the first-batch spread"),
)

# --------------------------------------------------------------------------------------------------------------
# THE WIDE NET — the rest of the candidate roster. Grouped by domain. Crypto entries resolve TODAY; equities /
# macro / commodities entries need ENTITY_BARS_SYMBOL + a venue before they score (flagged in the doc). ECHO /
# aggregator / news-wire accounts are kept (they are the lead-lag ECHO controls) but are LOW PRIORITY to score.
# --------------------------------------------------------------------------------------------------------------
SEED_ROSTER_REST: tuple[Voice, ...] = (
    # --- CRYPTO (resolve now) ---
    Voice("@rovercrc", "x", "very high-frequency 'BREAKING' BTC hype posts (Crypto Rover) — likely momentum-chasing ECHO; falsified if a hype account scores real foresight"),
    Voice("@CryptoKaleo", "x", "frequent alt directional calls (Kaleo) — original narrative bets; test alt-call skill vs breadth"),
    Voice("@Trader_XO", "x", "BTC/alt swing TA with levels — original, regular cadence"),
    Voice("@AltcoinGordon", "x", "altcoin narrative + setup posts — more hype than levels; test whether narrative timing carries skill"),
    Voice("@SmartContracter", "x", "Elliott-Wave BTC/alt calls (Bluntz) — original, specific bottom/top calls; method-driven falsifiability"),
    Voice("@AltcoinPsycho", "x", "alt TA + market-structure calls — original, respected among traders"),
    Voice("@KoroushAK", "x", "BTC/alt TA + trade ideas — education-leaning but posts explicit calls"),
    Voice("@TheCryptoDog", "x", "sentiment + TA BTC/alt reads — mixed original/echo; test sentiment-as-signal"),
    Voice("@CryptoCred", "x", "TA educator (BTC/alts) — fewer explicit calls; lower claim density, original"),
    Voice("@woonomic", "x", "on-chain data-driven BTC reads (Willy Woo) — slow-cadence LEAD candidate; few but high-conviction directional claims"),
    Voice("@100trillionUSD", "x", "S2F-model BTC directional framing (PlanB) — model-anchored, low cadence; test whether the model leads or post-rationalizes"),
    Voice("@CryptoCobain", "x", "crypto sentiment / shitpost with occasional sharp calls — mostly noise CONTROL; falsified if noise scores skill"),
    Voice("@inversebrah", "x", "meme/aggregator reposter — ECHO control, LOW priority; should register no original foresight"),
    # --- EQUITIES / OPTIONS (need equity entity-map + venue before scoring) ---
    Voice("@ElonTrades", "x", "operator-seeded; active stock/options day-trader posting directional calls — flagship equities test once an equity bar map exists"),
    Voice("@unusual_whales", "x", "options-flow + unusual-activity data (~1.9M) — original DATA, very high frequency; strong equities candidate post entity-map"),
    Voice("@TheRoaringKitty", "x", "sporadic meme-stock catalyst posts (Keith Gill) — rare but high-impact; an event-driven, not high-cadence, candidate"),
    Voice("@markminervini", "x", "SEPA momentum stock setups (Mark Minervini) — original, lower cadence, reputation-to-lose"),
    Voice("@traderstewie", "x", "day-trading stock setups + levels — frequent original calls"),
    Voice("@alphatrends", "x", "VWAP / multi-timeframe stock TA (Brian Shannon) — original, disciplined process"),
    Voice("@hmeisler", "x", "short-term equity TA + sentiment (Helene Meisler) — original, contrarian"),
    Voice("@CitronResearch", "x", "activist SHORT calls (Andrew Left) — rare, high-impact, original event-driven"),
    Voice("@muddywatersre", "x", "forensic short reports (Muddy Waters) — rare, original, single-name catalysts"),
    Voice("@DeItaone", "x", "Walter Bloomberg headline relay — ECHO wire, LOW priority; the lead-lag negative control for equities"),
    Voice("@stockmktnewz", "x", "stock news relay (Evan) — ECHO, LOW priority; should not register as foresight"),
    # --- MACRO ---
    Voice("@MacroAlf", "x", "institutional macro framework (Alfonso Peccatiello) — original, low-cadence directional macro views"),
    Voice("@LynAldenContact", "x", "monetary/fiscal macro (Lyn Alden) — original, slow, track-record-bearing"),
    Voice("@RaoulGMI", "x", "macro + crypto regime calls (Raoul Pal) — original, directional, reputation-to-lose"),
    Voice("@TaviCosta", "x", "macro + gold/commodities charts (Otavio Costa) — original, frequent, thesis-driven"),
    Voice("@biancoresearch", "x", "rates/macro analysis (Jim Bianco) — original, data-driven, low-cadence calls"),
    Voice("@profplum99", "x", "market-structure / passive-flow macro (Mike Green) — original, contrarian"),
    Voice("@SantiagoAuFund", "x", "dollar + gold macro (Brent Johnson) — original 'milkshake' thesis, directional"),
    Voice("@GameofTrades_", "x", "retail-facing macro/equity directional calls — frequent, unproven; let the score decide"),
    # --- COMMODITIES ---
    Voice("@PeterLBrandt", "x", "classical-charting futures/commodities + BTC (Peter Brandt) — veteran, original, explicit chart calls"),
    Voice("@JavierBlas", "x", "energy/commodities analysis (Javier Blas, Bloomberg) — original columns + some relay"),
    Voice("@staunovo", "x", "oil market reads (Giovanni Staunovo, UBS) — original, frequent, analyst-grade"),
    Voice("@Ole_S_Hansen", "x", "cross-commodity strategist (Ole Hansen, Saxo) — original, frequent directional notes"),
    Voice("@TheLastBearSta1", "x", "energy/macro deep dives (The Last Bear Standing) — original, thesis-driven, low cadence"),
    Voice("@anasalhajji", "x", "oil-market expert (Anas Alhajji) — original supply/demand analysis"),
    Voice("@WallStreetSilver", "x", "silver-bull sentiment crowd — ECHO/bias control; persistent up-bias not timing, must NOT beat base rate"),
)

# The full wide net = first-10 + the rest. Pass SEED_ROSTER_FULL only when budget allows scoring everyone.
SEED_ROSTER_FULL: tuple[Voice, ...] = SEED_ROSTER_FIRST10 + SEED_ROSTER_REST
