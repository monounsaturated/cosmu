# intent: export the ideas shown on the landing page from the standard harness (hypotheses.py) into
#   apps/web/lib/showcase.json. Per idea: every headline with its entry/exit and GROSS 1-month return,
#   the asset's price path (for the chart), and the random-timing baseline. Platform costs are applied
#   in the browser so the visitor can switch broker. Real closes only.
import json
from pathlib import Path

import hypotheses as hx

OUT = Path(__file__).parents[2] / "apps/web/lib/showcase.json"

SHOW = [
    # key, asset label, short title, emoji-free icon hint
    ("ai_nvda", "Nvidia", "AI launches", "spark"),
    ("war_defense", "US defense stocks", "Wars", "shield"),
    ("bank_btc", "Bitcoin", "Bank collapses", "bank"),
    ("hack_cibr", "Cybersecurity stocks", "Big hacks", "lock"),
]


def main():
    hx.derived_events()
    hx.variants()
    ideas = []
    for key, label, title, icon in SHOW:
        r = hx.run(key)
        asset = r["trades"][0]["asset"]
        days, p = hx.px(asset)
        trades = []
        for t in r["trades"]:
            i = days.index(t["fill"])
            j = i + hx.H
            trades.append({
                "news": t["news"], "name": t["name"],
                "in": days[i], "out": days[j],
                "gross": round(p[j] / p[i] - 1, 4),
            })
        lo = max(0, days.index(trades[0]["in"]) - 40)
        hi = min(len(p) - 1, days.index(trades[-1]["out"]) + 25)
        step = max(1, (hi - lo) // 220)
        series = [[days[k], round(p[k], 2)] for k in range(lo, hi + 1, step)]
        for t in trades:  # make sure every entry/exit day is on the path
            for d in (t["in"], t["out"]):
                k = days.index(d)
                series.append([d, round(p[k], 2)])
        series = sorted({s[0]: s for s in series}.values())
        ideas.append({
            "key": key, "title": title, "icon": icon, "q": r["q"], "asset": asset, "label": label,
            "crypto": asset.endswith("-USD"), "hold_days": hx.H,
            "random_month": round(r["rand_mean"] + hx.COST.get(asset, hx.DEFAULT_COST), 4),
            "beats_random": round(r["beaten"], 4),
            "trades": trades, "series": series,
        })
        print(f"{key:<14} {len(trades)} trades, {len(series)} pts")
    OUT.write_text(json.dumps({"window": ["2020-01-01", "2025-12-31"], "ideas": ideas}, separators=(",", ":")))


if __name__ == "__main__":
    main()
