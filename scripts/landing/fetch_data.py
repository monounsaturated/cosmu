# intent: download every input the landing-page research needs into scripts/landing/cache/ (gitignored),
#   so `pnpm research` / `pnpm demo:data` run on a fresh clone. Keyless public sources only:
#   Yahoo Finance daily closes (2020–2025), alternative.me crypto Fear & Greed, Wikimedia pageviews,
#   GDELT news volume (strictly rate-limited: slow, and some topics may need a re-run later).
#   Idempotent: files already present are skipped. Uses curl (avoids macOS Python SSL-certificate issues).
# usage: python3 scripts/landing/fetch_data.py
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import hypotheses as hx
import news_spikes as ns
import wiki_spikes as ws

CACHE = hx.CACHE
UA = "cosmu-research/1.0 (github.com/monounsaturated/cosmu)"


def curl(url: str, dest: Path, ua: str = "Mozilla/5.0") -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-s", "-m", "90", "-A", ua, "-o", str(dest), url])
    ok = r.returncode == 0 and dest.exists() and dest.stat().st_size > 0 and dest.read_bytes()[:1] in (b"{", b"[")
    if not ok:
        dest.unlink(missing_ok=True)
    return ok


def fetch_with_retry(url: str, dest: Path, ua: str, tries: int = 3, backoff: float = 20) -> bool:
    """Public APIs rate-limit bursts (Wikimedia, GDELT): retry with a growing pause instead of giving up."""
    for attempt in range(tries):
        if curl(url, dest, ua):
            return True
        time.sleep(backoff * (attempt + 1))
    return False


def tickers() -> set[str]:
    # every asset any idea trades (data-derived triggers use SPY/QQQ/BTC-USD, the AI variant uses SMH)
    out = {"SPY", "QQQ", "BTC-USD", "SMH"}
    for hyp in hx.HYP.values():
        out |= {asset for _, asset, _ in hyp["events"]}
    out |= {asset for _, asset, _ in ns.TOPICS}
    out |= {asset for _, asset, _, _ in ws.TOPICS}
    return out


def main():
    missing = []
    # 1) prices
    for t in sorted(tickers()):
        f = CACHE / f"{t.replace('^', '')}.json"
        if f.exists():
            continue
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}"
               "?period1=1577836800&period2=1767225600&interval=1d&events=div%7Csplit")
        print("prices", t, "ok" if curl(url, f) else "FAILED", flush=True)
    # 2) crypto Fear & Greed
    f = CACHE / "fng.json"
    if not f.exists():
        print("fear&greed", "ok" if curl("https://api.alternative.me/fng/?limit=0&format=json", f) else "FAILED")
    # 3) Wikipedia attention
    for art, *_ in ws.TOPICS:
        f = ws.W / f"{art}.json"
        if f.exists():
            continue
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
               f"{urllib.parse.quote(art)}/daily/20191101/20251231")
        ok = fetch_with_retry(url, f, UA, tries=3, backoff=10)
        print("wikipedia", art, "ok" if ok else "FAILED (rate-limited, re-run later)", flush=True)
        if not ok:
            missing.append(f"wikipedia:{art}")
        time.sleep(4)
    # 4) GDELT news volume (one request per ~10 s; GDELT blocks faster callers)
    for slug, query in ns.QUERIES.items():
        f = ns.G / f"{slug}.json"
        if f.exists() and "timeline" in f.read_text()[:200]:
            continue
        params = {"query": query, "mode": "timelinevolraw", "startdatetime": "20200101000000",
                  "enddatetime": "20251231000000", "format": "json"}
        ok = fetch_with_retry("https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params), f, UA,
                              tries=2, backoff=30)
        print("gdelt", slug, "ok" if ok else "rate-limited, re-run later", flush=True)
        if not ok:
            missing.append(f"gdelt:{slug}")
        time.sleep(10)
    if missing:
        print(f"\n{len(missing)} inputs still missing ({', '.join(missing)}): the sources rate-limit bursts. "
              "Re-run later; the build lists anything still missing as not tested.")
    else:
        print("\nall inputs present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
