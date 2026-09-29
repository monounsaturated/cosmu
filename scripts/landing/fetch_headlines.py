# intent: one real, representative English headline for each news-spike day (GDELT DOC API, artlist mode),
#   so the landing page's news scan shows what people actually read that day. Cached per (topic, day);
#   GDELT allows ~1 request / 5 s, so this runs slowly and can be re-run to fill gaps.
import json
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

import news_spikes as ns

OUT = ns.G / "headlines.json"
QUERY = {"layoffs": "layoffs", "hurricane": "hurricane"}


def fetch(query, day):
    d0 = datetime.strptime(day, "%Y-%m-%d")
    params = {
        "query": f"{query} sourcelang:english",
        "mode": "artlist",
        "maxrecords": "10",
        "sort": "hybridrel",
        "format": "json",
        "startdatetime": d0.strftime("%Y%m%d000000"),
        "enddatetime": (d0 + timedelta(days=1)).strftime("%Y%m%d000000"),
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)
    raw = subprocess.run(["curl", "-s", "-m", "60", url], capture_output=True, text=True).stdout
    if not raw.lstrip().startswith("{"):
        raise RuntimeError(raw[:60])
    arts = json.loads(raw).get("articles", [])
    for a in arts:  # prefer a clean, readable title
        t = " ".join(a.get("title", "").split())
        if 25 <= len(t) <= 110 and query.split()[0].lower()[:6] in t.lower():
            return {"title": t, "domain": a.get("domain", "")}
    return {"title": None, "domain": None}


def main(pause=30):
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    jobs = [(slug, d) for slug, k in (("layoffs", 2.0), ("hurricane", 3.0)) for d, _, _ in ns.spikes(slug, k)]
    for slug, day in jobs:
        key = f"{slug}|{day}"
        if key in cache:
            continue
        for attempt in range(4):
            try:
                cache[key] = fetch(QUERY[slug], day)
                OUT.write_text(json.dumps(cache, indent=1))
                print("ok", key, cache[key]["title"], flush=True)
                break
            except Exception as e:  # rate limited or network — back off and retry
                print("retry", key, str(e)[:50], flush=True)
                time.sleep(pause * (attempt + 2))
        time.sleep(pause)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
