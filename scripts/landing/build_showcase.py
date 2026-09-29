# intent: export the ideas shown on the landing page from the standard harness (hypotheses.py +
#   news_spikes.py) into apps/web/lib/showcase.json. Per idea: every trigger with its entry/exit and GROSS
#   return, the asset's price path (for the chart), and the random-timing baseline for the same hold.
#   Platform costs are applied in the browser so the visitor can switch broker. Real closes only.
import json
import os
from pathlib import Path

import hypotheses as hx
import news_spikes as ns

OUT = Path(__file__).parents[2] / "apps/web/lib/showcase.json"

# key, asset label, short title, icon, hold (sessions), spike threshold (None = curated events), question
SHOW = [
    ("ai_nvda", "Nvidia", "AI launches", "spark", 20, None, "What if I'd bought Nvidia every time a big AI model launched?"),
    ("spike_layoffs_QQQ", "Nasdaq", "Layoff news", "users", 10, 2.0, "What if I'd bought the Nasdaq whenever layoff news spiked?"),
    ("war_defense", "US defense stocks", "Wars", "shield", 20, None, "What if I'd bought defense stocks every time a war broke out?"),
    ("spike_hurricane_GNRC", "Generac", "Hurricane news", "wind", 5, 3.0, "What if I'd bought Generac whenever hurricane news spiked?"),
    ("bank_btc", "Bitcoin", "Bank collapses", "bank", 20, None, "What if I'd bought Bitcoin every time a bank collapsed?"),
    ("hack_cibr", "Cybersecurity stocks", "Big hacks", "lock", 20, None, "What if I'd bought cybersecurity stocks after every big hack?"),
]

TOPIC_WORD = {"layoffs": "Layoff", "hurricane": "Hurricane"}
HEADLINES = ns.G / "headlines.json"


def main():
    hx.derived_events()
    hx.variants()
    heads = json.loads(HEADLINES.read_text()) if HEADLINES.exists() else {}
    notes: dict[str, str] = {}
    ideas = []
    for key, label, title, icon, h, k, ask in SHOW:
        if k is not None:
            os.environ["SPIKE_K"] = str(k)
            ns.K = k
            slug = key.split("_")[1]
            asset = key.split("_", 2)[2]
            ev = ns.spikes(slug, k)
            q = next(t[2] for t in ns.TOPICS if t[0] == slug and t[1] == asset)
            events = []
            for d, m, _ in ev:
                title = (heads.get(f"{slug}|{d}") or {}).get("title")
                events.append((d, asset, title or f"{TOPIC_WORD[slug]} news spike"))
                notes[f"{key}|{d}"] = f"{m}× normal coverage"
            hx.HYP[key] = {"q": q, "events": events}
        r = hx.run(key, h=h)
        asset = r["trades"][0]["asset"]
        days, p = hx.px(asset)
        trades = []
        for t in r["trades"]:
            i = days.index(t["fill"])
            j = i + h
            tr = {"news": t["news"], "name": t["name"], "in": days[i], "out": days[j], "gross": round(p[j] / p[i] - 1, 4)}
            if f"{key}|{t['news']}" in notes:
                tr["note"] = notes[f"{key}|{t['news']}"]
            trades.append(tr)
        lo = max(0, days.index(trades[0]["in"]) - 40)
        hi = min(len(p) - 1, days.index(trades[-1]["out"]) + 25)
        step = max(1, (hi - lo) // 240)
        series = [[days[x], round(p[x], 2)] for x in range(lo, hi + 1, step)]
        for t in trades:
            for d in (t["in"], t["out"]):
                x = days.index(d)
                series.append([d, round(p[x], 2)])
        series = sorted({s[0]: s for s in series}.values())
        ideas.append({
            "key": key, "title": title, "icon": icon, "q": r["q"], "ask": ask, "asset": asset, "label": label,
            "crypto": asset.endswith("-USD"), "hold_days": h, "spike": k is not None,
            "random_month": round(r["rand_mean"] + hx.COST.get(asset, hx.DEFAULT_COST), 4),
            "beats_random": round(r["beaten"], 4),
            "trades": trades, "series": series,
        })
        print(f"{key:<24} H={h:<3} {len(trades):>3} trades  avg {r['mean'] * 100:+.1f}%  rnd {r['rand_mean'] * 100:+.1f}%  beats {r['beaten'] * 100:.0f}%")
    OUT.write_text(json.dumps({"window": ["2020-01-01", "2025-12-31"], "ideas": ideas}, separators=(",", ":")))


if __name__ == "__main__":
    main()
