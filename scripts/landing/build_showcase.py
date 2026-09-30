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
import re
import sys
from pathlib import Path

import hypotheses as hx
import news_spikes as ns
import wiki_spikes as ws

OUT = Path(__file__).parents[2] / "apps/web/lib/showcase.json"
EVENT_H, SPIKE_H, SPIKE_K = 20, 10, 2.0
MIN_N, PASS, PROMISING = 10, 0.95, 0.80
DRAWS = 10_000  # random-date draws per idea (the page says 10,000)
FDR_Q = 0.10    # Benjamini-Hochberg false-discovery rate across every idea tested (as in archive .../master/fdr.py)

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
HEADLINES = Path(__file__).parent / "data" / "headlines.json"  # real, same-day headlines (fetch_headlines.py)


def clean(title):
    """Drop outlet furniture: 'Exclusive | …', '… | CNN Business'."""
    t = re.sub(r"^(exclusive|breaking|update[d]?)\s*[|:]\s*", "", title, flags=re.I)
    return re.sub(r"\s+\|\s+[^|]+$", "", t).strip()


def headline(heads, cache_key):
    h = heads.get(cache_key) or {}
    return (clean(h["title"]), h.get("source")) if h.get("title") else (None, None)


def register_spikes(heads, notes, not_tested):
    """Every news topic, with the one standard threshold. Topics without data are recorded, never silently dropped."""
    keys = []
    for slug, asset, q in ns.TOPICS:
        ev = ns.spikes(slug, SPIKE_K)
        if ev is None:
            not_tested.append({"q": q, "reason": "news-volume data not downloaded (GDELT rate limit)"})
            continue
        if not ev:
            not_tested.append({"q": q, "reason": f"no news spike reached {SPIKE_K}× normal"})
            continue
        key = f"spike_{slug}_{asset}"
        events = []
        for d, m, _ in ev:
            head, source = headline(heads, f"{slug}|{d}")
            word = TOPIC_WORD.get(slug, slug.capitalize())
            events.append((d, asset, head or f"{word} news at {m}× normal"))
            notes[f"{key}|{d}"] = f"{source} · {m}× normal coverage" if head else f"{m}× normal coverage"
        hx.HYP[key] = {"q": q, "events": events}
        keys.append(key)
    return keys


def main():
    hx.derived_events()
    hx.variants()
    heads = json.loads(HEADLINES.read_text()) if HEADLINES.exists() else {}
    notes: dict[str, str] = {}
    not_tested: list[dict] = []
    spike_keys = set(register_spikes(heads, notes, not_tested))
    hx.HYP["fear_btc"] = {"q": "Buy Bitcoin when crypto sentiment hits Extreme Fear",
                          "events": [(d, "BTC-USD", f"Fear & Greed {v}") for d, v, _ in ns.fear_events()]}
    spike_keys.add("fear_btc")
    for key in ws.register(not_tested):  # public-attention spikes (Wikipedia), same 2-week hold
        spike_keys.add(key)
        art = key.split("_", 1)[1].rsplit("_", 1)[0]
        mult = {d: m for d, m, _ in ws.spikes(art)}
        events = []
        for d, asset, name in hx.HYP[key]["events"]:
            head, source = headline(heads, f"wiki:{art}|{d}")
            events.append((d, asset, head or name))
            notes[f"{key}|{d}"] = f"{source} · {mult[d]}× normal attention" if head else f"{mult[d]}× normal attention"
        hx.HYP[key]["events"] = events

    # Every idea, one fixed setting per kind.
    tested = []
    for key in hx.HYP:
        h = SPIKE_H if key in spike_keys else EVENT_H
        r = hx.run(key, h=h, draws=DRAWS)
        tested.append({"key": key, "q": r["q"], "n": r["n"], "hold_days": h, "avg": round(r["mean"], 4),
                       "random": round(r["rand_mean"], 4), "beats": round(r["beaten"], 4),
                       "pass": r["n"] >= MIN_N and r["beaten"] >= PASS,
                       "promising": r["n"] >= MIN_N and PROMISING <= r["beaten"] < PASS})
    tested.sort(key=lambda x: -x["beats"])

    # Multiple-testing correction: one-sided empirical p-value per idea, then Benjamini-Hochberg across all of them.
    m = len(tested)
    for t in tested:
        t["p"] = round(max(1 - t["beats"], 1 / (DRAWS + 1)), 5)
    ranked = sorted(tested, key=lambda t: t["p"])
    k = max((i + 1 for i, t in enumerate(ranked) if t["p"] <= (i + 1) / m * FDR_Q), default=0)
    survivors = {t["key"] for t in ranked[:k]}
    for t in tested:
        t["fdr_pass"] = t["key"] in survivors
    print(f"Benjamini-Hochberg at q={FDR_Q} over {m} ideas: {k} survive; smallest p = {ranked[0]['p']} ({ranked[0]['key']})")
    print(f"tested {len(tested)} ideas, passed {sum(t['pass'] for t in tested)}, promising {sum(t['promising'] for t in tested)}")

    missing = [key for key, *_ in SHOW if key not in hx.HYP]
    if missing:
        sys.exit(f"Missing inputs for {', '.join(missing)} (a source rate-limited the download). "
                 "Re-run `pnpm research:fetch` later; apps/web/lib/showcase.json was left unchanged.")

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
    OUT.write_text(json.dumps({"window": ["2020-01-01", "2025-12-31"], "draws": DRAWS,
                               "rule": {"min_n": MIN_N, "pass": PASS, "promising": PROMISING},
                               "fdr": {"q": FDR_Q, "ideas": m, "survivors": sorted(survivors)},
                               "tested": tested, "not_tested": not_tested, "ideas": ideas}, separators=(",", ":")))


if __name__ == "__main__":
    main()
