#!/usr/bin/env python3
"""Authority V1 scorer for @ElonTrades. Reads calls.json, fetches FREE Kraken price
data via curl (urllib has SSL issues in this env), measures forward moves, discards
echoes, computes a COMPOSITE score (not Brier-only). Pure stdlib + curl subprocess."""
import json, subprocess, datetime, math, sys, time

CALLS = json.load(open("/tmp/authority/calls.json"))["calls"]

KRAKEN_PAIR = {"BTC": "XBTUSD", "ETH": "ETHUSD"}
KRAKEN_KEY  = {"BTC": "XXBTZUSD", "ETH": "XETHZUSD"}

def curl_json(url):
    out = subprocess.run(["curl", "-s", "--max-time", "20", url],
                         capture_output=True, text=True).stdout
    return json.loads(out)

def kraken_ohlc(asset, since_ts, interval, _tries=6):
    """interval in minutes (60=hourly, 1440=daily). Retries on rate-limit."""
    pair = KRAKEN_PAIR[asset]; key = KRAKEN_KEY[asset]
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}&since={since_ts}"
    for attempt in range(_tries):
        d = curl_json(url)
        if d.get("error"):
            time.sleep(2 + attempt)  # backoff on "Too many requests"
            continue
        rows = d["result"][key]
        return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]
    raise RuntimeError(f"kraken {asset} {interval}m failed: {d.get('error')}")

# ---- fetch ONE wide hourly + ONE wide daily window per asset (cached) ----
oldest = min(int(datetime.datetime.fromisoformat(c["ts"].replace("Z","+00:00")).timestamp())
             for c in CALLS)
CACHE_H, CACHE_D = {}, {}
for a in set(c["asset"] for c in CALLS if c["asset"] in KRAKEN_PAIR):
    CACHE_H[a] = kraken_ohlc(a, oldest - 12 * 3600, 60); time.sleep(1.5)
    CACHE_D[a] = kraken_ohlc(a, oldest - 5 * 86400, 1440); time.sleep(1.5)

def price_at_or_after(bars, target_ts):
    """First bar close at/after target_ts (uses bar open as the entry/exit ref)."""
    for ts, o, h, l, c in bars:
        if ts >= target_ts:
            return ts, o
    return None, None

def pct(a, b):
    return (b - a) / a * 100.0 if a else 0.0

# parse + fetch
results = []
for call in CALLS:
    ts = datetime.datetime.fromisoformat(call["ts"].replace("Z", "+00:00"))
    epoch = int(ts.timestamp())
    asset = call["asset"]
    direction = call["direction"]
    if asset not in KRAKEN_PAIR:
        results.append({**call, "skip": "asset_no_free_data"}); continue

    hb = CACHE_H[asset]   # wide hourly window (cached, covers echo lead-in to +3d)
    db = CACHE_D[asset]   # wide daily window (cached, robustness for long horizons)

    # If the tweet predates the hourly window (Kraken hourly only keeps ~720 bars / ~30d),
    # fall back to DAILY bars for entry + all forward windows (granularity ok for 1d/3d).
    hourly_covers = hb and hb[0][0] <= epoch
    grain = "hourly" if hourly_covers else "daily"
    src = hb if hourly_covers else db

    # entry: first bar at/after tweet
    e_ts, entry = price_at_or_after(src, epoch)
    if entry is None:
        results.append({**call, "skip": "no_entry_bar"}); continue

    # echo check: price ~6h BEFORE tweet vs entry -> if move already underway in the
    # call's direction by a large amount, flag as late/echo and discount.
    # (use hourly if available, else daily 1-bar-before as a coarse proxy)
    if hourly_covers:
        _, pre6 = price_at_or_after(hb, epoch - 6 * 3600)
    else:
        prev = [b for b in db if b[0] <= epoch - 86400]
        pre6 = prev[-1][1] if prev else None
    pre_move_6h = pct(pre6, entry) if pre6 else 0.0  # lead-in move

    # forward windows
    fwd = {}
    for label, secs in (("1h", 3600), ("1d", 86400), ("3d", 3 * 86400)):
        if hourly_covers:
            _, p = price_at_or_after(hb, epoch + secs)
            if p is None:  # long horizon beyond hourly coverage -> daily
                _, p = price_at_or_after(db, epoch + secs)
        else:
            # daily-only: 1h window not resolvable at daily grain -> null
            p = None if label == "1h" else price_at_or_after(db, epoch + secs)[1]
        fwd[label] = pct(entry, p) if p else None
    fwd_grain = grain

    # signed move = move in the DIRECTION of the call (bullish -> +; bearish -> -move)
    sign = {"bullish": 1, "bearish": -1, "neutral": 0}[direction]
    signed = {k: (sign * v if v is not None else None) for k, v in fwd.items()}

    # echo: a bullish call where price already ran >+3% in the prior 6h (or bearish already dropped >3%)
    echo = False
    if sign != 0:
        lead = sign * pre_move_6h  # how much the move already went our way pre-tweet
        echo = lead > 3.0

    results.append({
        **call,
        "entry": entry, "entry_bar_ts": e_ts, "grain": grain,
        "pre_move_6h_pct": round(pre_move_6h, 3),
        "fwd_pct": {k: (round(v, 3) if v is not None else None) for k, v in fwd.items()},
        "signed_pct": {k: (round(v, 3) if v is not None else None) for k, v in signed.items()},
        "echo": echo,
        "sign": sign,
    })

# ---- COMPOSITE over DIRECTIONAL, non-echo calls ----
HORIZON = "1d"  # primary scoring horizon
directional = [r for r in results if r.get("sign", 0) != 0 and "skip" not in r]
scored = [r for r in directional if not r["echo"] and r["signed_pct"].get(HORIZON) is not None]

n_all = len(CALLS)
n_directional = len(directional)
n_scored = len(scored)

def brier_terms(r):
    # treat a directional call as p=0.75 prob of move in called direction (signal accounts
    # don't emit probabilities; 0.75 = "confident lean"). outcome=1 if signed move>0 else 0.
    p = 0.75
    outcome = 1 if r["signed_pct"][HORIZON] > 0 else 0
    return (p - outcome) ** 2

if n_scored:
    hits = sum(1 for r in scored if r["signed_pct"][HORIZON] > 0)
    hit_rate = hits / n_scored
    # EV / payoff: cumulative signed return if you traded each call small (1 unit, equal weight)
    ev_cum = sum(r["signed_pct"][HORIZON] for r in scored)
    ev_avg = ev_cum / n_scored
    wins = [r["signed_pct"][HORIZON] for r in scored if r["signed_pct"][HORIZON] > 0]
    avg_move_when_right = sum(wins) / len(wins) if wins else 0.0
    losses = [r["signed_pct"][HORIZON] for r in scored if r["signed_pct"][HORIZON] <= 0]
    avg_move_when_wrong = sum(losses) / len(losses) if losses else 0.0
    brier = sum(brier_terms(r) for r in scored) / n_scored
    # consistency = 1 - normalized stdev of signed returns (lower vol of outcome = more consistent)
    mean = ev_avg
    var = sum((r["signed_pct"][HORIZON] - mean) ** 2 for r in scored) / n_scored
    std = math.sqrt(var)
    consistency = max(0.0, 1 - std / (abs(mean) + std + 1e-9))
    # lead-time proxy: avg (negative) pre-move => calling BEFORE the move is good.
    # we already drop echoes; report mean pre_move in called direction for scored calls
    lead_proxy = -sum(r["sign"] * r["pre_move_6h_pct"] for r in scored) / n_scored

    # COMPOSITE: blend (all in [0,1]-ish, then 0-100)
    #  - edge term: hit_rate centered at 0.5
    #  - payoff term: avg EV per call, scaled (1% per call ~ meaningful)
    #  - calibration term: (1 - 2*brier) maps brier 0->1, 0.25->0.5, 0.5->0
    edge_term = (hit_rate - 0.5) * 2          # -1..+1
    payoff_term = max(-1, min(1, ev_avg / 2)) # +-2% per call saturates
    calib_term = 1 - 2 * brier                # -1..+1 (brier .5 = coinflip = 0)
    composite_raw = 0.40 * payoff_term + 0.35 * edge_term + 0.25 * calib_term  # -1..+1
    composite = round(50 + 50 * composite_raw, 1)  # 0..100, 50 = no edge
else:
    hit_rate = ev_cum = ev_avg = avg_move_when_right = avg_move_when_wrong = brier = 0
    consistency = lead_proxy = composite = 0

# top-3 movers = biggest signed wins across ALL directional non-skip calls (incl echo-flagged,
# but echoes get a note) at primary horizon, by absolute realized move
movers_pool = [r for r in directional if r["signed_pct"].get(HORIZON) is not None]
top3 = sorted(movers_pool, key=lambda r: r["signed_pct"][HORIZON], reverse=True)[:3]

summary = {
    "account": "@ElonTrades",
    "horizon": HORIZON,
    "n_asset_calls_total": n_all,
    "n_directional": n_directional,
    "n_neutral": n_all - n_directional,
    "n_scored_after_echo_filter": n_scored,
    "hit_rate": round(hit_rate, 3),
    "ev_cum_pct": round(ev_cum, 3),
    "ev_avg_pct": round(ev_avg, 3),
    "avg_move_when_right_pct": round(avg_move_when_right, 3),
    "avg_move_when_wrong_pct": round(avg_move_when_wrong, 3),
    "brier": round(brier, 4),
    "consistency": round(consistency, 3),
    "lead_proxy_pct": round(lead_proxy, 3),
    "composite_0_100": composite,
    "top3_movers": [
        {"asset": r["asset"], "ts": r["ts"], "direction": r["direction"],
         "signed_move_1d_pct": r["signed_pct"][HORIZON], "echo": r["echo"],
         "url": r["url"], "text": r["text"][:140]}
        for r in top3
    ],
    "all_results": results,
}
json.dump(summary, open("/tmp/authority/summary.json", "w"), indent=2)
print(json.dumps({k: v for k, v in summary.items() if k != "all_results"}, indent=2))
