# intent: faster, more frequent triggers — no hand-picked dates. A "news spike" is a day when a topic's
#   share of ALL news articles (GDELT, 2020–2025) jumps to >= K× its median over the previous 30 days,
#   the first such day in a 10-day window. Same harness as hypotheses.py: buy at the close of the first
#   session strictly after the spike day, hold H sessions, pay costs, compare with 10,000 random-date draws.
#   Also: the crypto Fear & Greed index (alternative.me) dropping into "Extreme Fear".
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

import hypotheses as hx

G = hx.CACHE / "gdelt"
K = float(os.environ.get("SPIKE_K", "3"))
COOLDOWN = 10
MIN_ARTICLES = 50

# The GDELT search behind each topic slug (fetch_data.py downloads these).
QUERIES = {
    "cyber": "(cyberattack OR ransomware)",
    "strike": '(airstrike OR "missile strike" OR "missile attack")',
    "hurricane": "hurricane",
    "tariff": "tariffs",
    "birdflu": '"bird flu"',
    "heatwave": "heatwave",
    "drought": "drought",
    "bankrun": '("bank run" OR "bank failure" OR "bank collapse")',
    "recession": "recession",
    "chipshort": '"chip shortage"',
    "ai": '("artificial intelligence" OR ChatGPT)',
    "oil": '(OPEC OR "oil prices")',
    "musk": '"Elon Musk"',
    "inflation": "inflation",
    "cryptohack": '("crypto hack" OR "exchange hack" OR "crypto exchange hacked")',
    "layoffs": "layoffs",
}

# Topics that only make sense in a season (Atlantic hurricane season: June–November).
SEASON = {"hurricane": ("06-01", "11-30")}

# slug, asset, question
TOPICS = [
    ("cyber", "CIBR", "Buy cybersecurity stocks when hack news spikes"),
    ("strike", "ITA", "Buy defense stocks when missile-strike news spikes"),
    ("hurricane", "GNRC", "Buy Generac when hurricane news spikes"),
    ("tariff", "SPY", "Buy the S&P 500 when tariff news spikes"),
    ("birdflu", "CALM", "Buy the biggest egg producer when bird-flu news spikes"),
    ("heatwave", "UNG", "Buy natural gas when heatwave news spikes"),
    ("heatwave", "XLU", "Buy utilities when heatwave news spikes"),
    ("drought", "CORN", "Buy corn when drought news spikes"),
    ("bankrun", "BTC-USD", "Buy Bitcoin when bank-failure news spikes"),
    ("recession", "SPY", "Buy the S&P 500 when recession news spikes"),
    ("oil", "USO", "Buy oil when OPEC / oil-price news spikes"),
    ("musk", "TSLA", "Buy Tesla when Elon Musk news spikes"),
    ("cryptohack", "BTC-USD", "Buy Bitcoin when crypto-hack news spikes"),
    ("chipshort", "SMH", "Buy chip stocks when chip-shortage news spikes"),
    ("ai", "NVDA", "Buy Nvidia when AI news spikes"),
    ("inflation", "GLD", "Buy gold when inflation news spikes"),
    ("layoffs", "QQQ", "Buy the Nasdaq when layoff news spikes"),
]


def spikes(slug, k=K):
    f = G / f"{slug}.json"
    if not f.exists() or "timeline" not in f.read_text()[:200]:
        return None
    data = json.loads(f.read_text())["timeline"][0]["data"]
    days = [datetime.strptime(d["date"][:8], "%Y%m%d").strftime("%Y-%m-%d") for d in data]
    share = [d["value"] / d["norm"] if d["norm"] else 0 for d in data]
    count = [d["value"] for d in data]
    out, last = [], -999
    season = SEASON.get(slug)
    for i in range(30, len(days)):
        if season and not (season[0] <= days[i][5:] <= season[1]):
            continue
        base = statistics.median(share[i - 30 : i])
        if base > 0 and share[i] >= k * base and count[i] >= MIN_ARTICLES and i - last > COOLDOWN:
            out.append((days[i], round(share[i] / base, 1), count[i]))
            last = i
    return out


def fear_events(level=20):
    rows = json.loads((hx.CACHE / "fng.json").read_text())["data"]
    pts = sorted((datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"), int(r["value"])) for r in rows)
    pts = [p for p in pts if "2020-01-01" <= p[0] <= "2025-12-31"]
    out, last = [], -999
    for i, (d, v) in enumerate(pts):
        if v <= level and pts[i - 1][1] > level and i - last > COOLDOWN:
            out.append((d, v, None))
            last = i
    return out


def register():
    for slug, asset, q in TOPICS:
        ev = spikes(slug)
        if not ev:
            continue
        hx.HYP[f"spike_{slug}_{asset}"] = {"q": q, "events": [(d, asset, f"{slug} news ×{m}") for d, m, _ in ev]}
    hx.HYP["fear_btc"] = {"q": "Buy Bitcoin when crypto sentiment hits Extreme Fear",
                          "events": [(d, "BTC-USD", f"Fear & Greed {v}") for d, v, _ in fear_events()]}


def main():
    register()
    keys = [k for k in hx.HYP if k.startswith("spike_") or k == "fear_btc"]
    print(f"{'trigger':<28}{'n':>4} | avg return after (vs random) · win · beats-random")
    print(f"{'':<28}{'':>4} | {'5 days':>26} | {'10 days':>26} | {'20 days':>26}")
    out = {}
    for k in keys:
        cells = []
        for h in (5, 10, 20):
            r = hx.run(k, h=h, draws=3000)
            out[f"{k}@{h}"] = r
            cells.append(f"{r['mean'] * 100:+5.1f}% ({r['rand_mean'] * 100:+4.1f}) {r['win'] * 100:3.0f}% {r['beaten'] * 100:3.0f}%")
        print(f"{k:<28}{out[f'{k}@5']['n']:>4} | " + " | ".join(cells))
    (hx.CACHE / "spikes.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
