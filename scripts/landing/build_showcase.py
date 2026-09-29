# intent: export the landing page's data from the standard harness (hypotheses.py + news_spikes.py) into
#   apps/web/lib/showcase.json:
#   - "ideas": the scenarios the studio can open — every trigger with entry/exit and GROSS return, the
#     asset's price path, and the random-timing baseline (same assets, same stretch of time, 10,000 draws);
#   - "tested": EVERY idea run through the harness with ONE fixed setting per kind (events: hold 1 month;
#     news spikes: 2× normal volume, hold 2 weeks), so the page can say how many were tried and how few passed.
#   Pass rule (shown on the page): at least 10 triggers AND better than >= 95% of random-date draws;
#   "promising" = at least 10 triggers and 80–95%.
#   Platform costs are applied in the browser so the visitor can switch broker. Real closes only.
import json
from pathlib import Path

import hypotheses as hx
import news_spikes as ns
import wiki_spikes as ws

OUT = Path(__file__).parents[2] / "apps/web/lib/showcase.json"
EVENT_H, SPIKE_H, SPIKE_K = 20, 10, 2.0
MIN_N, PASS, PROMISING = 10, 0.95, 0.80

# key, asset label, short title, icon, question typed into the prompt
SHOW = [
    ("spike_layoffs_QQQ", "Nasdaq", "Layoff news", "users", "What if I'd bought the Nasdaq whenever layoff news spiked?"),
    ("war_defense", "US defense stocks", "Wars", "shield", "What if I'd bought defense stocks every time a war broke out?"),
    ("wiki_Ballistic_missile_ITA", "US defense stocks", "Missile news", "target", "What if I'd bought defense stocks whenever missile news spiked?"),
    ("bank_btc", "Bitcoin", "Bank crises", "bank", "What if I'd bought Bitcoin every time a bank crisis hit?"),
    ("ai_nvda", "Nvidia", "AI launches", "spark", "What if I'd bought Nvidia every time a big AI model launched?"),
    ("hack_cibr", "Cybersecurity stocks", "Big hacks", "lock", "What if I'd bought cybersecurity stocks after every big hack?"),
]

TOPIC_WORD = {"layoffs": "Layoff", "hurricane": "Hurricane", "musk": "Elon Musk"}
HEADLINES = ns.G / "headlines.json"


def register_spikes(heads, notes):
    """Every downloaded news topic, with the one standard threshold."""
    keys = []
    for slug, asset, q in ns.TOPICS:
        ev = ns.spikes(slug, SPIKE_K)
        if not ev:
            continue
        key = f"spike_{slug}_{asset}"
        events = []
        for d, m, _ in ev:
            head = (heads.get(f"{slug}|{d}") or {}).get("title")
            word = TOPIC_WORD.get(slug, slug.capitalize())
            events.append((d, asset, head or f"{word} news at {m}× normal"))
            if head:
                notes[f"{key}|{d}"] = f"{m}× normal coverage"
        hx.HYP[key] = {"q": q, "events": events}
        keys.append(key)
    return keys


def main():
    hx.derived_events()
    hx.variants()
    heads = json.loads(HEADLINES.read_text()) if HEADLINES.exists() else {}
    notes: dict[str, str] = {}
    spike_keys = set(register_spikes(heads, notes))
    hx.HYP["fear_btc"] = {"q": "Buy Bitcoin when crypto sentiment hits Extreme Fear",
                          "events": [(d, "BTC-USD", f"Fear & Greed {v}") for d, v, _ in ns.fear_events()]}
    spike_keys.add("fear_btc")
    spike_keys |= set(ws.register())  # public-attention spikes (Wikipedia), same 2-week hold

    # Every idea, one fixed setting per kind.
    tested = []
    for key in hx.HYP:
        h = SPIKE_H if key in spike_keys else EVENT_H
        r = hx.run(key, h=h, draws=4000)
        tested.append({"key": key, "q": r["q"], "n": r["n"], "hold_days": h, "avg": round(r["mean"], 4),
                       "random": round(r["rand_mean"], 4), "beats": round(r["beaten"], 4),
                       "pass": r["n"] >= MIN_N and r["beaten"] >= PASS,
                       "promising": r["n"] >= MIN_N and PROMISING <= r["beaten"] < PASS})
    tested.sort(key=lambda x: -x["beats"])
    print(f"tested {len(tested)} ideas, passed {sum(t['pass'] for t in tested)}, promising {sum(t['promising'] for t in tested)}")

    ideas = []
    for key, label, title, icon, ask in SHOW:
        h = SPIKE_H if key in spike_keys else EVENT_H
        r = hx.run(key, h=h)
        asset = r["trades"][0]["asset"]
        days, p = hx.px(asset)
        trades = []
        for t in r["trades"]:
            i = days.index(t["fill"])
            j = i + t["h"]
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
            "crypto": asset.endswith("-USD"), "hold_days": h, "spike": key in spike_keys,
            "random_month": round(r["rand_mean"] + hx.COST.get(asset, hx.DEFAULT_COST), 4),
            "beats_random": round(r["beaten"], 4),
            "trades": trades, "series": series,
        })
        print(f"{key:<24} H={h:<3} {len(trades):>3} trades  avg {r['mean'] * 100:+.1f}%  rnd {r['rand_mean'] * 100:+.1f}%  beats {r['beaten'] * 100:.0f}%")
    OUT.write_text(json.dumps({"window": ["2020-01-01", "2025-12-31"], "rule": {"min_n": MIN_N, "pass": PASS, "promising": PROMISING},
                               "tested": tested, "ideas": ideas}, separators=(",", ":")))


if __name__ == "__main__":
    main()
