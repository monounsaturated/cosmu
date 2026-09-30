# intent: one real, dated headline for each news-spike day shown on the landing page, so the news scan
#   shows what people actually read that day. Source: Google News RSS search (keyless) restricted to the
#   spike day itself — never a later article (no look-ahead). Prefers major outlets. Cached per
#   (topic, day) in scripts/landing/data/headlines.json (tracked); re-runnable, polite (1.5 s between requests).
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import news_spikes as ns
import wiki_spikes as ws

OUT = Path(__file__).parent / "data" / "headlines.json"  # tracked: the page must be reproducible
MAJOR = ["Reuters", "Associated Press", "AP News", "Bloomberg", "CNBC", "The Wall Street Journal", "WSJ",
         "The New York Times", "Financial Times", "BBC", "CNN", "The Guardian", "Axios", "Forbes",
         "Business Insider", "The Washington Post", "Fortune", "Al Jazeera", "NPR", "CBS News", "ABC News",
         "NBC News", "Yahoo Finance", "MarketWatch", "The Verge", "TechCrunch", "Politico", "Time"]

# The headline must be about the topic, not a sports "layoff" or a band's comeback.
MUST = {"layoffs": ("layoffs", "job cuts", "cut jobs", "cuts jobs", "jobs cut", "to cut", "laid off", "lay off"),
        "wiki:Ballistic_missile": ("missile",)}


# cache key prefix, search words, list of spike days
def jobs():
    out = [("layoffs", "layoffs OR \"job cuts\"", [d for d, _, _ in ns.spikes("layoffs", 2.0)])]
    out.append(("wiki:Ballistic_missile", "missile strike", [d for d, _, _ in ws.spikes("Ballistic_missile")]))
    return out


def fetch(prefix, words, day):
    d0 = datetime.strptime(day, "%Y-%m-%d")
    q = f"{words} after:{(d0 - timedelta(days=1)):%Y-%m-%d} before:{(d0 + timedelta(days=1)):%Y-%m-%d}"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    xml = subprocess.run(["curl", "-s", "-m", "30", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
    best = None
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = " ".join(re.search(r"<title>(.*?)</title>", it, re.S).group(1).split())
        pub = parsedate_to_datetime(re.search(r"<pubDate>(.*?)</pubDate>", it).group(1)).strftime("%Y-%m-%d")
        if pub != day:  # the spike day only — nothing published later
            continue
        title = (title.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                 .replace("&lt;", "<").replace("&gt;", ">"))
        head, _, source = title.rpartition(" - ")
        head = head or title
        if not (25 <= len(head) <= 100) or not any(m in head.lower() for m in MUST[prefix]):
            continue
        score = 2 if any(m.lower() in source.lower() for m in MAJOR) else 1
        if not best or score > best[0]:
            best = (score, {"title": head.strip(), "source": source.strip()})
            if score == 2:
                break
    return best[1] if best else {"title": None, "source": None}


def main(pause=1.5):  # add --refresh to re-fetch cached days
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    for prefix, words, days in jobs():
        for day in days:
            key = f"{prefix}|{day}"
            if cache.get(key, {}).get("title") and "--refresh" not in sys.argv:
                continue
            cache[key] = fetch(prefix, words, day)
            OUT.write_text(json.dumps(cache, indent=1))
            print(key, "→", cache[key]["title"], f"({cache[key]['source']})", flush=True)
            time.sleep(pause)


if __name__ == "__main__":
    main()
