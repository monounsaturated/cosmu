# intent: one standard harness for "what if I'd bought X every time Y made the news?" — the loop the product
#   automates. Every hypothesis runs identically: buy at the close of the first session STRICTLY AFTER the
#   news day (no look-ahead), sell H sessions later, pay a round-trip cost, then compare against the same
#   asset bought on random days (10k draws). Real Yahoo daily closes (adjusted), 2020–2025.
# output: a ranked table on stdout + scripts/landing/cache/hypotheses.json (full detail per idea).
import json
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path(__file__).parent / "cache"
H = 20  # holding period in trading sessions (~1 month)
COST = {"BTC-USD": 0.002}  # round trip; stocks/ETFs default below
DEFAULT_COST = 0.001


def load(t: str):
    raw = json.loads((CACHE / f"{t.replace('^', '')}.json").read_text())["chart"]["result"][0]
    adj = raw["indicators"].get("adjclose", [{}])[0].get("adjclose") or raw["indicators"]["quote"][0]["close"]
    rows = [(datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"), p) for ts, p in zip(raw["timestamp"], adj) if p]
    return [d for d, _ in rows], [p for _, p in rows]


PX: dict[str, tuple[list[str], list[float]]] = {}


def px(t):
    if t not in PX:
        PX[t] = load(t)
    return PX[t]


def first_after(days, date):
    return next((i for i, d in enumerate(days) if d > date), None)


# ── hypotheses: (news date, asset, headline). Dates = day the story broke publicly. ──
HYP = {
    "ai_nvda": {
        "q": "Buy Nvidia every time a major AI model launches",
        "events": [
            ("2022-11-30", "NVDA", "ChatGPT launches"),
            ("2023-03-14", "NVDA", "GPT-4 released"),
            ("2023-12-06", "NVDA", "Google unveils Gemini"),
            ("2024-02-15", "NVDA", "OpenAI shows Sora"),
            ("2024-05-13", "NVDA", "GPT-4o launches"),
            ("2024-09-12", "NVDA", "OpenAI o1 reasoning model"),
            ("2025-01-27", "NVDA", "DeepSeek R1 shock"),
            ("2025-08-07", "NVDA", "GPT-5 launches"),
        ],
    },
    "war_defense": {
        "q": "Buy defense stocks every time a war breaks out",
        "events": [
            ("2020-01-03", "ITA", "US kills Soleimani"),
            ("2022-02-24", "ITA", "Russia invades Ukraine"),
            ("2022-08-04", "ITA", "China drills around Taiwan"),
            ("2023-10-07", "ITA", "Hamas attacks Israel"),
            ("2024-01-11", "ITA", "US & UK strike the Houthis"),
            ("2024-04-13", "ITA", "Iran drone attack on Israel"),
            ("2024-10-01", "ITA", "Iran missile barrage on Israel"),
            ("2025-05-07", "ITA", "India strikes Pakistan"),
            ("2025-06-13", "ITA", "Israel strikes Iran"),
            ("2025-06-21", "ITA", "US bombs Iran nuclear sites"),
        ],
    },
    "storm_generac": {
        "q": "Buy the generator maker every time a storm knocks out power",
        "events": [
            ("2020-08-27", "GNRC", "Hurricane Laura"),
            ("2020-09-16", "GNRC", "Hurricane Sally"),
            ("2020-10-09", "GNRC", "Hurricane Delta"),
            ("2020-10-28", "GNRC", "Hurricane Zeta"),
            ("2021-02-15", "GNRC", "Texas freeze blackout"),
            ("2021-08-29", "GNRC", "Hurricane Ida"),
            ("2022-09-28", "GNRC", "Hurricane Ian"),
            ("2023-08-30", "GNRC", "Hurricane Idalia"),
            ("2024-07-08", "GNRC", "Hurricane Beryl"),
            ("2024-09-26", "GNRC", "Hurricane Helene"),
            ("2024-10-09", "GNRC", "Hurricane Milton"),
        ],
    },
    "split_announce": {
        "q": "Buy a stock the day after it announces a stock split",
        "events": [
            ("2020-07-30", "AAPL", "Apple 4-for-1"),
            ("2020-08-11", "TSLA", "Tesla 5-for-1"),
            ("2021-05-21", "NVDA", "Nvidia 4-for-1"),
            ("2022-02-01", "GOOGL", "Alphabet 20-for-1"),
            ("2022-03-09", "AMZN", "Amazon 20-for-1"),
            ("2022-04-11", "SHOP", "Shopify 10-for-1"),
            ("2024-01-30", "WMT", "Walmart 3-for-1"),
            ("2024-03-19", "CMG", "Chipotle 50-for-1"),
            ("2024-05-22", "NVDA", "Nvidia 10-for-1"),
            ("2024-05-23", "DECK", "Deckers 6-for-1"),
            ("2024-06-12", "AVGO", "Broadcom 10-for-1"),
            ("2024-08-06", "SMCI", "Supermicro 10-for-1"),
            ("2025-10-30", "NFLX", "Netflix 10-for-1"),
        ],
    },
    "opec_cut": {
        "q": "Buy oil every time OPEC announces a production cut",
        "events": [
            ("2020-04-12", "USO", "OPEC+ record 9.7M bbl cut"),
            ("2021-01-05", "USO", "Saudi surprise 1M bbl cut"),
            ("2022-10-05", "USO", "OPEC+ 2M bbl cut"),
            ("2023-04-02", "USO", "Surprise OPEC+ cut"),
            ("2023-06-04", "USO", "Saudi voluntary cut"),
            ("2023-09-05", "USO", "Saudi extends cut to year-end"),
            ("2023-11-30", "USO", "OPEC+ deeper voluntary cuts"),
        ],
    },
    "fed_cut_qqq": {
        "q": "Buy the Nasdaq every time the Fed cuts rates",
        "events": [
            ("2020-03-03", "QQQ", "Emergency 0.5% cut"),
            ("2020-03-15", "QQQ", "Emergency cut to zero"),
            ("2024-09-18", "QQQ", "First cut since 2020"),
            ("2024-11-07", "QQQ", "Second cut"),
            ("2024-12-18", "QQQ", "Third cut"),
            ("2025-09-17", "QQQ", "Cut resumes"),
            ("2025-10-29", "QQQ", "October cut"),
        ],
    },
    "bank_btc": {
        "q": "Buy Bitcoin every time a bank crisis hits",
        "events": [
            ("2023-03-10", "BTC-USD", "Silicon Valley Bank fails"),
            ("2023-03-19", "BTC-USD", "Credit Suisse rescued"),
            ("2023-05-01", "BTC-USD", "First Republic seized"),
            ("2024-01-31", "BTC-USD", "NYCB plunges on losses"),
        ],
    },
    "tariff_spy": {
        "q": "Buy the S&P 500 the day after a tariff shock",
        "events": [
            ("2025-02-01", "SPY", "Tariffs on Canada, Mexico, China"),
            ("2025-03-04", "SPY", "Canada & Mexico tariffs take effect"),
            ("2025-04-02", "SPY", "'Liberation Day' tariffs"),
            ("2025-10-10", "SPY", "100% China tariff threat"),
        ],
    },
    "pandemic_mrna": {
        "q": "Buy vaccine makers every time a new virus scare hits the news",
        "events": [
            ("2020-01-21", "MRNA", "First US COVID case"),
            ("2020-02-24", "MRNA", "COVID spreads to Europe"),
            ("2021-11-26", "MRNA", "Omicron variant"),
            ("2022-05-20", "MRNA", "Mpox spreads worldwide"),
            ("2024-08-14", "MRNA", "WHO mpox emergency"),
        ],
    },
    "adoption_btc": {
        "q": "Buy Bitcoin every time a big institution adopts it",
        "events": [
            ("2020-08-11", "BTC-USD", "MicroStrategy buys its first Bitcoin"),
            ("2020-10-08", "BTC-USD", "Square buys $50M of Bitcoin"),
            ("2021-02-08", "BTC-USD", "Tesla buys $1.5B of Bitcoin"),
            ("2021-06-09", "BTC-USD", "El Salvador makes it legal tender"),
            ("2024-01-10", "BTC-USD", "US approves spot Bitcoin ETFs"),
            ("2025-03-06", "BTC-USD", "US creates a Strategic Bitcoin Reserve"),
        ],
    },
    "war_gold": {
        "q": "Buy gold every time a war or major strike breaks out",
        "events": [
            ("2020-01-03", "GLD", "US kills Soleimani"),
            ("2022-02-24", "GLD", "Russia invades Ukraine"),
            ("2022-08-04", "GLD", "China drills around Taiwan"),
            ("2023-10-07", "GLD", "Hamas attacks Israel"),
            ("2024-01-11", "GLD", "US & UK strike the Houthis"),
            ("2024-04-13", "GLD", "Iran drone attack on Israel"),
            ("2024-10-01", "GLD", "Iran missile barrage on Israel"),
            ("2025-05-07", "GLD", "India strikes Pakistan"),
            ("2025-06-13", "GLD", "Israel strikes Iran"),
            ("2025-06-21", "GLD", "US bombs Iran nuclear sites"),
        ],
    },
    "hack_cibr": {
        "q": "Buy cybersecurity stocks after every big hack",
        "events": [(d, "CIBR", n) for d, n in [
            ("2021-03-02", "Microsoft Exchange"), ("2021-05-08", "Colonial Pipeline"), ("2021-05-31", "JBS Foods"),
            ("2021-07-02", "Kaseya"), ("2021-08-16", "T-Mobile"), ("2021-12-10", "Log4Shell"),
            ("2022-03-22", "Okta"), ("2022-03-29", "Ronin Bridge"), ("2022-09-15", "Uber"),
            ("2022-12-22", "LastPass"), ("2023-01-19", "T-Mobile"), ("2023-05-31", "MOVEit"),
            ("2023-09-11", "MGM Resorts"), ("2023-10-20", "Okta"), ("2024-01-19", "Microsoft"),
            ("2024-02-22", "Change Healthcare"), ("2024-05-31", "Ticketmaster"), ("2024-06-19", "CDK Global"),
            ("2024-07-12", "AT&T"), ("2024-10-05", "Salt Typhoon"), ("2025-02-21", "Bybit"),
            ("2025-05-15", "Coinbase"), ("2025-07-20", "SharePoint"),
        ]],
    },
}


def variants():
    HYP["ai_smh"] = {"q": "Buy chip stocks every time a major AI model launches",
                     "events": [(d, "SMH", n) for d, _, n in HYP["ai_nvda"]["events"]]}


def derived_events():
    """Data-defined triggers (no curation): market panic days and crypto crash days."""
    days, p = px("SPY")
    panic, last = [], -99
    for i in range(1, len(p)):
        if p[i] / p[i - 1] - 1 <= -0.03 and i - last > H:
            panic.append((days[i], "QQQ", f"S&P 500 falls {abs(p[i] / p[i - 1] - 1) * 100:.1f}%"))
            last = i
    HYP["panic_qqq"] = {"q": "Buy the Nasdaq the day after the market crashes 3%+", "events": panic}
    days, p = px("BTC-USD")
    crash, last = [], -99
    for i in range(1, len(p)):
        if p[i] / p[i - 1] - 1 <= -0.10 and i - last > H:
            crash.append((days[i], "BTC-USD", f"Bitcoin falls {abs(p[i] / p[i - 1] - 1) * 100:.0f}% in a day"))
            last = i
    HYP["crash_btc"] = {"q": "Buy Bitcoin the day after it crashes 10%+", "events": crash}


def fwd(t, i, h):
    days, p = px(t)
    return p[i + h] / p[i] - 1 - COST.get(t, DEFAULT_COST) if i + h < len(p) else None


def hold(t, h):
    """Stocks: h trading sessions. Crypto trades every day, so convert to the same calendar span (5 → 7)."""
    return round(h * 7 / 5) if t.endswith("-USD") else h


def run(key, h=H, draws=10_000):
    hyp = HYP[key]
    trades = []
    for news, t, name in hyp["events"]:
        days, p = px(t)
        i = first_after(days, news)
        if i is None or i + hold(t, h) >= len(p):
            continue
        trades.append({"news": news, "fill": days[i], "i": i, "h": hold(t, h), "asset": t, "name": name,
                       "ret": round(fwd(t, i, hold(t, h)), 4)})
    rets = [x["ret"] for x in trades]
    n = len(rets)
    mean = statistics.mean(rets)
    # Random baseline: same assets, same count, random entry days drawn from the SAME stretch of time as the
    # events (first → last trigger, at least ±6 months), so a strong era can't pass for a strong signal.
    rng = random.Random(11)
    span = {}
    for x in trades:
        lo, hi = span.get(x["asset"], (x["i"], x["i"]))
        span[x["asset"]] = (min(lo, x["i"]), max(hi, x["i"]))
    rand_means = []
    for _ in range(draws):
        s = 0.0
        for x in trades:
            t, hh = x["asset"], x["h"]
            days, p = px(t)
            lo, hi = span[t]
            lo, hi = max(0, min(lo, x["i"] - 126)), min(len(p) - hh - 1, max(hi, x["i"] + 126))
            s += fwd(t, rng.randint(lo, hi), hh)
        rand_means.append(s / n)
    rand_means.sort()
    beaten = sum(1 for m in rand_means if m < mean) / draws
    return {
        "key": key, "q": hyp["q"], "n": n, "h": h, "mean": mean, "median": statistics.median(rets),
        "win": sum(r > 0 for r in rets) / n, "best": max(rets), "worst": min(rets),
        "rand_mean": statistics.mean(rand_means), "beaten": beaten, "trades": trades,
    }


def main():
    derived_events()
    variants()
    out = {}
    print(f"{'hypothesis':<16}{'n':>4}{'avg/trade':>11}{'random':>9}{'win':>6}{'beats rnd':>11}   sweep avg (5/10/20/40/60d)")
    rows = []
    for k in HYP:
        r = run(k)
        sweep = [run(k, h, draws=1)["mean"] for h in (5, 10, 20, 40, 60)]
        r["sweep"] = sweep
        out[k] = r
        rows.append(r)
    for r in sorted(rows, key=lambda r: -r["beaten"]):
        sw = " ".join(f"{s * 100:+5.1f}" for s in r["sweep"])
        print(f"{r['key']:<16}{r['n']:>4}{r['mean'] * 100:>+10.1f}%{r['rand_mean'] * 100:>+8.1f}%{r['win'] * 100:>5.0f}%{r['beaten'] * 100:>10.0f}%   {sw}")
    (CACHE / "hypotheses.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
