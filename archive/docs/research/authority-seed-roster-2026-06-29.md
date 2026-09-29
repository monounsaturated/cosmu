# Authority seed roster — directional-call X/Twitter accounts (2026-06-29)

_A WIDE-net starter roster of X/Twitter accounts that post **directional asset calls** (crypto · equities/options ·
macro · commodities), compiled to feed the **Authority** lane (PR #492). The Authority scoreboard reads an account's
calls and measures whether they **precede** price moves (Brier-skill vs base rate, lead-lag, echo-disconfirmed). It
needs a roster of candidates; this is that roster._

## The discipline (why a wide net is correct)

This is **not** a watchlist of accounts we believe in. Per the operator's trust heuristic: for *foundations/theory* we
trust only reputation-to-lose sources, **but for SIGNAL accounts we want to include even unproven / "stupid" ones — the
whole point is to SCORE them and let the data say who's good.** So we cast wide and let the price-anchored scoreboard
decide. No account here is asserted to have skill; each `why` in the config is a **falsifiable hypothesis written before
scoring** (the same anti-survivorship rule as `VOICE_PANEL`). The honest first verdict may well be "0/N carry skill after
the base rate" — that is the machine working, not a bug.

## How it plugs into ingestion

The keyless `VOICE_PANEL` in [`cosmu/config/voices.py`](../../apps/engine/cosmu/config/voices.py) stays the `$0`
default (Reddit + RSS, no key). This roster is a **separate, opt-in** list in
[`cosmu/config/authority_seed_roster.py`](../../apps/engine/cosmu/config/authority_seed_roster.py) that the local
(keyed) pass reads explicitly:

```python
from cosmu.config.authority_seed_roster import SEED_ROSTER_FIRST10, SEED_ROSTER_FULL
voices_pass(store, panel=SEED_ROSTER_FIRST10)   # score the cheap first batch
# voices_pass(store, panel=SEED_ROSTER_FULL)    # widen once budget allows
```

- **Cost / key:** every X handle is fetched via Grok LiveSearch → needs `XAI_API_KEY`, ≈ **$0.066 / account / pass**.
  Caps in `voices.py` bound it: `MAX_POSTS_PER_VOICE_PER_PASS = 25`, `MAX_EXTRACTIONS_PER_PASS = 100`.
- **First batch cost:** 10 accounts × ~$0.066 ≈ **$0.66 / pass**. Full roster (49) ≈ **$3.2 / pass**.

### ⚠️ Resolvability caveat — only crypto scores TODAY

A claim only resolves where its entity maps to a bar symbol in `ENTITY_BARS_SYMBOL`, which is **crypto-only right now**
(`BTC→BTCUSDT`, `ETH`, `SOL`, `BNB`, `XRP`, `DOGE`, `ADA`, `AVAX`, `LINK`, `DOT`, `LTC`). Equity / macro / commodity
calls resolve as `no_data` (named, never guessed) until two things are extended:

1. `ENTITY_BARS_SYMBOL` — add equity/commodity tickers (SPY, QQQ, AAPL, CL=oil, GC=gold, …).
2. A **venue with bars** for those entities (the EODHD equities/commodities lane already scoped in the price-data sweep).

→ Therefore the **FIRST-10 is all crypto** — the only accounts whose calls resolve against bars we already have, so the
first xAI spend buys real scores instead of `no_data`. Equity/macro/commodity accounts are seeded now (so they're
pre-registered before scoring) but should be scored **after** the entity-map + venue extension.

---

## ⭐ FIRST-10 to score (cost-managed, resolvable today)

All crypto · all original callers · biased to **high call-frequency** (more scoreable claims per $0.066) with a
deliberate spread: reputation-to-lose names + one very-high-volume unproven + one bold-specific perma-caller + an
on-chain lead-lag candidate.

| # | Handle | ~Followers | Call freq | Original/Echo | Why it's in the first batch |
|---|--------|-----------:|-----------|---------------|------------------------------|
| 1 | [@il_capo_of_crypto](https://x.com/il_capo_of_crypto) | ~750k | very high | Original | Specific BTC/ETH price-target (often short) calls — maximally falsifiable |
| 2 | [@CryptoMichNL](https://x.com/CryptoMichNL) | ~750k | very high | Original | Near-daily BTC/alt level calls (M. van de Poppe); high claim density |
| 3 | [@ali_charts](https://x.com/ali_charts) | ~600k | very high | Original | Huge volume of BTC/ETH/SOL signals (Ali Martinez); quality unproven — let score decide |
| 4 | [@Pentoshi](https://x.com/Pentoshi) | ~700k | high | Original | Reputation-to-lose BTC/alt caller; test foresight vs base rate |
| 5 | [@CryptoDonAlt](https://x.com/CryptoDonAlt) | ~600k | high | Original | Respected BTC/ETH TA (DonAlt); lead candidate |
| 6 | [@RektCapital](https://x.com/RektCapital) | ~500k | high | Original | BTC/ETH cycle + level calls; structured framing |
| 7 | [@CryptoTony__](https://x.com/CryptoTony__) | ~520k | high | Original | Daily BTC/ETH/alt TA with explicit invalidation levels |
| 8 | [@intocryptoverse](https://x.com/intocryptoverse) | ~800k | medium | Original | Quant, low-hype BTC/ETH risk calls (B. Cowen); calibration candidate |
| 9 | [@WClementeIII](https://x.com/WClementeIII) | ~700k | medium | Original | On-chain-driven BTC reads (Will Clemente); potential lead-lag LEADER |
| 10 | [@CredibleCrypto](https://x.com/CredibleCrypto) | ~500k | high | Original | Frequent BTC/ETH/XRP TA calls; widens the on-chain+TA spread |

> Follower counts are **approximate** (rough order of magnitude, ~2025–26) — used only to gauge reach, never as a skill
> signal. The scoreboard, not the follower count, decides authority.

---

## Full roster (the wide net)

Grouped by domain. **Resolves now?** = whether claims resolve against bars we already have (crypto = yes; the rest need
the entity-map + venue extension). **Priority** = scoring order: ⭐ first-10 · ✓ score-when-resolvable · ▽ low (echo /
bias control — kept deliberately as the lead-lag negative controls).

### Crypto (resolve now)

| Handle | ~Followers | Call freq | Original/Echo | Note | Priority |
|--------|-----------:|-----------|---------------|------|----------|
| [@il_capo_of_crypto](https://x.com/il_capo_of_crypto) | ~750k | very high | Original | Bold specific price-target/short calls | ⭐ |
| [@CryptoMichNL](https://x.com/CryptoMichNL) | ~750k | very high | Original | Daily BTC/alt levels (van de Poppe) | ⭐ |
| [@ali_charts](https://x.com/ali_charts) | ~600k | very high | Original | High-volume signals (Ali Martinez) | ⭐ |
| [@Pentoshi](https://x.com/Pentoshi) | ~700k | high | Original | Reputation-bearing BTC/alt caller | ⭐ |
| [@CryptoDonAlt](https://x.com/CryptoDonAlt) | ~600k | high | Original | Respected BTC/ETH TA (DonAlt) | ⭐ |
| [@RektCapital](https://x.com/RektCapital) | ~500k | high | Original | Cycle + level calls | ⭐ |
| [@CryptoTony__](https://x.com/CryptoTony__) | ~520k | high | Original | Daily TA with invalidations | ⭐ |
| [@intocryptoverse](https://x.com/intocryptoverse) | ~800k | medium | Original | Quant risk-metric (B. Cowen) | ⭐ |
| [@WClementeIII](https://x.com/WClementeIII) | ~700k | medium | Original | On-chain BTC (lead candidate) | ⭐ |
| [@CredibleCrypto](https://x.com/CredibleCrypto) | ~500k | high | Original | BTC/ETH/XRP TA | ⭐ |
| [@rovercrc](https://x.com/rovercrc) | ~900k | very high | Echo-ish | "BREAKING" hype (Crypto Rover) — momentum-chase test | ✓ |
| [@CryptoKaleo](https://x.com/CryptoKaleo) | ~700k | high | Original | Alt narrative bets (Kaleo) | ✓ |
| [@Trader_XO](https://x.com/Trader_XO) | ~500k | high | Original | BTC/alt swing TA | ✓ |
| [@AltcoinGordon](https://x.com/AltcoinGordon) | ~600k | high | Mixed | Altcoin narrative/setups | ✓ |
| [@SmartContracter](https://x.com/SmartContracter) | ~250k | medium | Original | Elliott-Wave BTC/alt (Bluntz) | ✓ |
| [@AltcoinPsycho](https://x.com/AltcoinPsycho) | ~400k | medium | Original | Alt TA + market structure | ✓ |
| [@KoroushAK](https://x.com/KoroushAK) | ~400k | medium | Original | BTC/alt trade ideas | ✓ |
| [@TheCryptoDog](https://x.com/TheCryptoDog) | ~700k | high | Mixed | Sentiment + TA | ✓ |
| [@CryptoCred](https://x.com/CryptoCred) | ~450k | low | Original | TA educator, few explicit calls | ✓ |
| [@woonomic](https://x.com/woonomic) | ~1.1M | low | Original | On-chain BTC (Willy Woo) — slow LEAD candidate | ✓ |
| [@100trillionUSD](https://x.com/100trillionUSD) | ~1.8M | low | Original | S2F model BTC (PlanB) | ✓ |
| [@CryptoCobain](https://x.com/CryptoCobain) | ~1M | medium | Mixed | Sentiment/shitpost — noise control | ▽ |
| [@inversebrah](https://x.com/inversebrah) | ~400k | high | **Echo** | Meme aggregator/reposter — echo control | ▽ |

### Equities / options (need equity entity-map + venue before scoring)

| Handle | ~Followers | Call freq | Original/Echo | Note | Priority |
|--------|-----------:|-----------|---------------|------|----------|
| [@ElonTrades](https://x.com/ElonTrades) | ~mid | high | Original | **Operator-seeded**; stock/options day-trader calls | ✓ |
| [@unusual_whales](https://x.com/unusual_whales) | ~1.9M | very high | Original (data) | Options-flow / unusual-activity data | ✓ |
| [@TheRoaringKitty](https://x.com/TheRoaringKitty) | ~1.5M | sporadic | Original | Meme-stock catalyst (Keith Gill) — event-driven | ✓ |
| [@markminervini](https://x.com/markminervini) | ~700k | low | Original | SEPA momentum setups | ✓ |
| [@traderstewie](https://x.com/traderstewie) | ~300k | high | Original | Day-trading setups + levels | ✓ |
| [@alphatrends](https://x.com/alphatrends) | ~200k | high | Original | VWAP/multi-TF TA (Brian Shannon) | ✓ |
| [@hmeisler](https://x.com/hmeisler) | ~150k | high | Original | Short-term equity TA (Helene Meisler) | ✓ |
| [@CitronResearch](https://x.com/CitronResearch) | ~300k | sporadic | Original | Activist short calls (Andrew Left) | ✓ |
| [@muddywatersre](https://x.com/muddywatersre) | ~200k | sporadic | Original | Forensic short reports | ✓ |
| [@DeItaone](https://x.com/DeItaone) | ~900k | very high | **Echo** | Walter Bloomberg headline wire — lead-lag echo control | ▽ |
| [@stockmktnewz](https://x.com/stockmktnewz) | ~500k | high | **Echo** | Stock news relay (Evan) | ▽ |

### Macro (need macro/index entity-map + venue before scoring)

| Handle | ~Followers | Call freq | Original/Echo | Note | Priority |
|--------|-----------:|-----------|---------------|------|----------|
| [@MacroAlf](https://x.com/MacroAlf) | ~400k | medium | Original | Institutional macro (A. Peccatiello) | ✓ |
| [@LynAldenContact](https://x.com/LynAldenContact) | ~500k | low | Original | Monetary/fiscal macro (Lyn Alden) | ✓ |
| [@RaoulGMI](https://x.com/RaoulGMI) | ~1.2M | medium | Original | Macro + crypto regime calls (Raoul Pal) | ✓ |
| [@TaviCosta](https://x.com/TaviCosta) | ~400k | high | Original | Macro + gold/commodities theses | ✓ |
| [@biancoresearch](https://x.com/biancoresearch) | ~300k | medium | Original | Rates/macro (Jim Bianco) | ✓ |
| [@profplum99](https://x.com/profplum99) | ~300k | medium | Original | Market structure / passive flow (Mike Green) | ✓ |
| [@SantiagoAuFund](https://x.com/SantiagoAuFund) | ~200k | medium | Original | Dollar + gold macro (Brent Johnson) | ✓ |
| [@GameofTrades_](https://x.com/GameofTrades_) | ~300k | high | Mixed | Retail-facing macro/equity calls | ✓ |

### Commodities (need commodity entity-map + venue before scoring)

| Handle | ~Followers | Call freq | Original/Echo | Note | Priority |
|--------|-----------:|-----------|---------------|------|----------|
| [@PeterLBrandt](https://x.com/PeterLBrandt) | ~800k | medium | Original | Classical-charting futures + BTC (veteran) | ✓ |
| [@JavierBlas](https://x.com/JavierBlas) | ~300k | high | Mixed | Energy/commodities (Bloomberg) | ✓ |
| [@staunovo](https://x.com/staunovo) | ~60k | high | Original | Oil reads (G. Staunovo, UBS) | ✓ |
| [@Ole_S_Hansen](https://x.com/Ole_S_Hansen) | ~80k | high | Original | Cross-commodity strategist (Saxo) | ✓ |
| [@TheLastBearSta1](https://x.com/TheLastBearSta1) | ~150k | low | Original | Energy/macro deep dives | ✓ |
| [@anasalhajji](https://x.com/anasalhajji) | ~100k | medium | Original | Oil supply/demand expert | ✓ |
| [@WallStreetSilver](https://x.com/WallStreetSilver) | ~1M | high | **Echo/bias** | Silver-bull crowd — bias control | ▽ |

**Roster size: 49 accounts** (23 crypto · 11 equities/options · 8 macro · 7 commodities).
Echo / bias controls flagged ▽ (kept as deliberate lead-lag negative controls): @inversebrah, @CryptoCobain,
@DeItaone, @stockmktnewz, @WallStreetSilver.

---

## Next steps (local)

1. **Score the FIRST-10** with the local xAI key: `voices_pass(store, panel=SEED_ROSTER_FIRST10)` (~$0.66/pass).
2. Read the scoreboard; expect a brutal base-rate verdict (most will not beat it — that is correct).
3. **Extend `ENTITY_BARS_SYMBOL` + add an equity/commodity venue** (EODHD lane) to unlock the equities/macro/commodities
   half, then score `SEED_ROSTER_FULL`.
4. Widen the net in future passes — add/remove a line in `authority_seed_roster.py`; the next pass picks it up.

### Sources

- [Ledn — Top crypto X accounts 2025](https://www.ledn.io/post/best-crypto-x-accounts)
- [Coingape — Best crypto X accounts 2026](https://coingape.com/best-crypto-twitter-accounts/)
- [TradersLog — Must-follow X accounts for traders 2025](https://www.traderslog.com/x-traders)
- [INOMICS — Top economics & finance Twitter feeds](https://inomics.com/blog/30-top-twitter-feeds-in-economics-and-finance-47892)
- [CommodityHQ — Crude oil traders to follow](https://commodityhq.com/investor-resources/10-crude-oil-traders-worth-following-on-twitter/)
- [CommodityHQ — Gold traders to follow](https://commodityhq.com/investor-resources/10-gold-traders-worth-following-on-twitter/)
- [AskTraders — Best stock traders on X 2025](https://www.asktraders.com/learn-to-trade/trading-guide/top-10-trader-twitter-to-follow/)
- [@ElonTrades on X](https://x.com/elontrades) (operator-seeded example)
