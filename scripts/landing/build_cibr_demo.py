# intent: build the landing-page demo dataset from REAL data — "buy 1 share of CIBR every time a major
#   hack makes national news, 2021–2025". Inputs: Yahoo daily CIBR bars (cibr_raw.json, adjusted close
#   incl. dividends) + the hand-curated event list below. Output: apps/web/lib/cibr-hacks.json.
# invariants: no look-ahead — each buy fills at the close of the first session STRICTLY AFTER the day the
#   news broke. Results are published as-is (good or bad). Fees are applied per platform in the browser.
import json
import random
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "apps/web/lib/cibr-hacks.json"

# (date the story broke publicly, short name, one-line what happened)
EVENTS = [
    ("2021-03-02", "Microsoft Exchange", "State-backed group exploits Exchange servers worldwide"),
    ("2021-05-08", "Colonial Pipeline", "Ransomware shuts the largest US fuel pipeline"),
    ("2021-05-31", "JBS Foods", "Ransomware halts the world's largest meat processor"),
    ("2021-07-02", "Kaseya VSA", "Supply-chain ransomware hits ~1,500 businesses"),
    ("2021-08-16", "T-Mobile", "Breach exposes data of 40M+ customers"),
    ("2021-12-10", "Log4Shell", "Critical flaw found in ubiquitous Java logging library"),
    ("2022-03-22", "Okta / Lapsus$", "Identity provider breached by extortion group"),
    ("2022-03-29", "Ronin Bridge", "$620M stolen from Axie Infinity's bridge"),
    ("2022-09-15", "Uber", "Attacker takes over Uber's internal systems"),
    ("2022-12-22", "LastPass", "Encrypted password vaults stolen"),
    ("2023-01-19", "T-Mobile", "API breach exposes 37M customer accounts"),
    ("2023-05-31", "MOVEit", "Mass exploitation of file-transfer software"),
    ("2023-09-11", "MGM Resorts", "Ransomware shuts down Las Vegas casinos"),
    ("2023-10-20", "Okta support", "Support-system breach hits identity provider again"),
    ("2024-01-19", "Microsoft / Midnight Blizzard", "Russian group reads senior executives' email"),
    ("2024-02-22", "Change Healthcare", "Ransomware paralyses US prescription processing"),
    ("2024-05-31", "Ticketmaster / Snowflake", "Data of 500M+ customers put up for sale"),
    ("2024-06-19", "CDK Global", "Attack takes 15,000 car dealerships offline"),
    ("2024-07-12", "AT&T", "Call and text records of nearly all customers stolen"),
    ("2024-10-05", "Salt Typhoon", "Chinese hackers inside US telecom wiretap systems"),
    ("2025-02-21", "Bybit", "$1.5B stolen — largest crypto theft ever"),
    ("2025-05-15", "Coinbase", "Bribed insiders leak customer data; $20M extortion"),
    ("2025-07-20", "SharePoint 'ToolShell'", "On-prem SharePoint zero-day hits governments"),
]

# 2021-01-01 → 2026-01-01, daily, with adjusted closes.
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/CIBR?period1=1609459200&period2=1767225600&interval=1d&events=div"

HORIZON = 20  # trading days used for the "impact" window (≈ 1 month)


def main() -> None:
    cache = HERE / "cibr_raw.json"
    if not cache.exists():
        req = urllib.request.Request(YAHOO, headers={"User-Agent": "Mozilla/5.0"})
        cache.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    raw = json.loads(cache.read_text())["chart"]["result"][0]
    ts = raw["timestamp"]
    adj = raw["indicators"]["adjclose"][0]["adjclose"]
    days = [datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d") for t in ts]
    bars = [(d, p) for d, p in zip(days, adj) if p is not None]
    days = [d for d, _ in bars]
    px = [p for _, p in bars]
    n = len(px)

    def first_after(date: str) -> int:
        return next(i for i, d in enumerate(days) if d > date)

    events = []
    for date, name, what in EVENTS:
        i = first_after(date)
        j = min(i + HORIZON, n - 1)
        events.append({
            "news": date, "fill": days[i], "i": i, "name": name, "what": what,
            "price": round(px[i], 2),
            "ret20": round(px[j] / px[i] - 1, 4),
        })
    buy_idx = [e["i"] for e in events]
    k = len(buy_idx)

    # Unconditional 20-day forward return over the same window (the "normal month" baseline).
    fwd = [px[i + HORIZON] / px[i] - 1 for i in range(n - HORIZON)]
    base20 = sum(fwd) / len(fwd)
    ev20 = sum(e["ret20"] for e in events) / k
    hit = sum(1 for e in events if e["ret20"] > 0) / k

    # Baseline: same number of shares bought on random days (10k draws, fixed seed).
    last = px[-1]
    def gross_multiple(idx: list[int]) -> float:
        return (k * last) / sum(px[i] for i in idx)
    strat = gross_multiple(buy_idx)
    rng = random.Random(7)
    draws = sorted(gross_multiple(rng.sample(range(n - 1), k)) for _ in range(10_000))
    pct_beaten = sum(1 for m in draws if m < strat) / len(draws)
    median_random = draws[len(draws) // 2]

    # Weekly series for the charts (every 5th bar + last) and cumulative shares held.
    series = []
    buys = set(buy_idx)
    shares = 0
    cost = 0.0
    for i in range(n):
        if i in buys:
            shares += 1
            cost += px[i]
        if i % 5 == 0 or i == n - 1 or i in buys:
            series.append([days[i], round(px[i], 2), shares, round(cost, 2)])

    out = {
        "asset": "CIBR",
        "asset_name": "First Trust NASDAQ Cybersecurity ETF",
        "window": [days[0], days[-1]],
        "rule": "Buy 1 share at the close of the first trading day after a major hack makes national news. Hold.",
        "source": "Yahoo Finance daily adjusted closes (dividends reinvested). Events hand-curated from public reporting.",
        "horizon_days": HORIZON,
        "last_price": round(last, 2),
        "events": [{k2: v for k2, v in e.items() if k2 != "i"} for e in events],
        "stats": {
            "trades": k,
            "gross_multiple": round(strat, 4),
            "avg_ret20_after_hack": round(ev20, 4),
            "avg_ret20_any_day": round(base20, 4),
            "hit_rate_20d": round(hit, 4),
            "random_median_multiple": round(median_random, 4),
            "pct_random_beaten": round(pct_beaten, 4),
        },
        "series": series,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(out["stats"], indent=2), len(series), "points")


if __name__ == "__main__":
    main()
