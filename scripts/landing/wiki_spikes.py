# intent: "public attention" triggers — a day when a Wikipedia article's daily views jump to >= K× their
#   median over the previous 30 days (first such day in a 10-day window) means a story is breaking.
#   Wikimedia pageviews API, keyless, 2019-11 → 2025. ONE fixed setting for every topic, decided before
#   looking at results: K = 3, hold 10 sessions. Same harness as hypotheses.py (next-close entry, costs,
#   10,000 random draws from the same years).
import json
import statistics
from datetime import datetime

import hypotheses as hx

W = hx.CACHE / "wiki"
K = 3.0
COOLDOWN = 10
H = 10
MIN_VIEWS = 3000  # ignore tiny absolute bumps

# article, asset, question, why it might work
TOPICS = [
    ("Avian_influenza", "CALM", "Buy the biggest US egg producer when bird-flu attention spikes", "outbreaks cull hens → egg prices jump"),
    ("Tropical_cyclone", "GNRC", "Buy Generac when hurricane attention spikes", "storms → outages → generator demand"),
    ("Power_outage", "GNRC", "Buy Generac when blackout attention spikes", "outages → generator demand"),
    ("Tariff", "SPY", "Buy the S&P 500 when tariff attention spikes", "fear sells off, markets recover"),
    ("Ransomware", "CIBR", "Buy cybersecurity stocks when ransomware attention spikes", "attacks → security budgets"),
    ("Data_breach", "CIBR", "Buy cybersecurity stocks when data-breach attention spikes", "breaches → security budgets"),
    ("Recession", "SPY", "Buy the S&P 500 when recession fear spikes", "peak fear is often near the bottom"),
    ("Stock_market_crash", "QQQ", "Buy the Nasdaq when crash fear spikes", "peak fear is often near the bottom"),
    ("Layoff", "QQQ", "Buy the Nasdaq when layoff attention spikes", "cost cuts → margins"),
    ("Inflation", "GLD", "Buy gold when inflation attention spikes", "inflation hedge"),
    ("Stagflation", "GLD", "Buy gold when stagflation fear spikes", "inflation hedge"),
    ("Bank_run", "BTC-USD", "Buy Bitcoin when bank-run fear spikes", "flight from banks"),
    ("Bank_run", "GLD", "Buy gold when bank-run fear spikes", "flight to safety"),
    ("Heat_wave", "UNG", "Buy natural gas when heatwave attention spikes", "air-con → power demand"),
    ("Drought", "CORN", "Buy corn when drought attention spikes", "crop damage → prices"),
    ("Bitcoin", "BTC-USD", "Buy Bitcoin when Bitcoin attention spikes", "attention → inflows"),
    ("Nvidia", "NVDA", "Buy Nvidia when Nvidia attention spikes", "attention → inflows"),
    ("ChatGPT", "NVDA", "Buy Nvidia when ChatGPT attention spikes", "AI demand → chips"),
    ("Artificial_general_intelligence", "SMH", "Buy chip stocks when AGI attention spikes", "AI demand → chips"),
    ("Semiconductor", "SMH", "Buy chip stocks when semiconductor attention spikes", "chip news → chip stocks"),
    ("Short_squeeze", "IWM", "Buy small caps when short-squeeze attention spikes", "retail frenzy"),
    ("Pandemic", "MRNA", "Buy Moderna when pandemic attention spikes", "vaccine demand"),
    ("OPEC", "USO", "Buy oil when OPEC attention spikes", "supply cuts"),
    ("Nuclear_warfare", "ITA", "Buy defense stocks when nuclear-war fear spikes", "defense spending"),
    ("Ballistic_missile", "ITA", "Buy defense stocks when missile attention spikes", "defense spending"),
    ("Quantitative_easing", "QQQ", "Buy the Nasdaq when money-printing attention spikes", "liquidity → growth stocks"),
    ("Federal_funds_rate", "QQQ", "Buy the Nasdaq when Fed-rate attention spikes", "rate moves → growth stocks"),
    ("Stock_market_bubble", "QQQ", "Buy the Nasdaq when bubble talk spikes", "contrarian: bubble fear is early"),
    ("Gold_as_an_investment", "GLD", "Buy gold when gold attention spikes", "attention → inflows"),
]


def spikes(article, k=K):
    items = json.loads((W / f"{article}.json").read_text())["items"]
    days = [datetime.strptime(i["timestamp"][:8], "%Y%m%d").strftime("%Y-%m-%d") for i in items]
    views = [i["views"] for i in items]
    out, last = [], -999
    for i in range(30, len(days)):
        if days[i] < "2020-01-01":
            continue
        base = statistics.median(views[i - 30 : i])
        if base > 0 and views[i] >= k * base and views[i] >= MIN_VIEWS and i - last > COOLDOWN:
            out.append((days[i], round(views[i] / base, 1), views[i]))
            last = i
    return out


NICE = {"Ballistic_missile": "Missile", "Bank_run": "Bank-run", "Avian_influenza": "Bird-flu",
        "Artificial_general_intelligence": "AGI", "Tropical_cyclone": "Hurricane", "Power_outage": "Blackout"}


def label(article):
    return NICE.get(article, article.replace("_", " "))


def register(not_tested=None):
    keys = []
    for art, asset, q, _ in TOPICS:
        if not (W / f"{art}.json").exists():
            if not_tested is not None:
                not_tested.append({"q": q, "reason": "Wikipedia pageviews not downloaded"})
            continue
        ev = spikes(art)
        if not ev:
            if not_tested is not None:
                not_tested.append({"q": q, "reason": f"no attention spike reached {K}× normal"})
            continue
        key = f"wiki_{art}_{asset}"
        hx.HYP[key] = {"q": q, "events": [(d, asset, f"{label(art)} news at {m}× normal") for d, m, _ in ev]}
        keys.append(key)
    return keys


def main():
    keys = register()
    print(f"{'trigger':<42}{'n':>4}  avg   random  win  beats")
    rows = [hx.run(k, h=H, draws=4000) for k in keys]
    for r in sorted(rows, key=lambda r: -r["beaten"]):
        flag = "PASS" if r["n"] >= 10 and r["beaten"] >= 0.95 else ""
        print(f"{r['key']:<42}{r['n']:>4} {r['mean'] * 100:+5.1f}% {r['rand_mean'] * 100:+5.1f}% {r['win'] * 100:4.0f}% {r['beaten'] * 100:5.0f}% {flag}")


if __name__ == "__main__":
    main()
