# intent: reduce SURVIVORSHIP bias in the equity universe. The cached 73 names are TODAY's mega-cap survivors
# (AAPL/NVDA/META/TSLA...) — a long-only book on them is inflated, and a sector-neutral book that shorts the
# bottom-of-sector is shorting ex-winners only. FIX: backfill a broad set of large-caps that WERE big historically
# but FADED / declined (GE, INTC, IBM, F, GM, C, X, MO, T, CSCO, WBA, PFE, KHC, PARA, NWSA, ... ), so each GICS
# sector bucket contains losers as well as winners. We pull split+dividend ADJUSTED daily close from Yahoo's free
# keyless v8 chart JSON (range=max) into the SAME on-disk cache format the existing names use
# (.cosmu/market_data/equities/<SYM>_1d.json : [{ts(ms), open, high, low, close, volume}, ...], prices as strings,
# close = adjusted close to match the existing cache which is back-adjusted — verified on AAPL's 2020 4:1 split).
#
# RESIDUAL BIAS (stated honestly): these are still names that EXIST TODAY (listed, not bankrupt-and-delisted). True
# survivorship-free testing needs the delisted tape (Enron, Lehman, WorldCom, WaMu, Bear Stearns, Wachovia, GM-old,
# Kodak, Sears, ...), which Yahoo does not serve for delisted tickers without a paid CRSP-style source. So this
# broadening removes the "only-the-winners" bias materially (the shorts now include real laggards that fell 50-90%
# from their peaks) but does NOT remove the "only-the-still-alive" bias (the zero-equity terminal names are absent).
# The honest read: results here are an UPPER-MIDDLE estimate — better than the 73-survivor panel, still optimistic
# vs a CRSP delisted-inclusive panel. We flag this in the report, never hide it.
#
# DOCTRINE: keyless + free (no API key); idempotent (append-merge into the existing cache, never shrink); PIT
# (only realized daily bars, no synthetic fill); ZERO LLM calls.

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Equity-cache default; env-overridable so it works off this Mac / on Modal-Railway (the §9 hardcoded-path fix).
CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "<repo>/.cosmu/market_data/equities"))

# Faded / declined large-caps to add, grouped by GICS sector bucket (the same 9-SPDR scheme the sector-neutral
# book uses). Every name here is a large-cap that was a market leader at some point and then materially
# underperformed or declined — so each bucket gains genuine LOSERS, not just more winners.
#   XLK Information Technology   XLF Financials        XLE Energy
#   XLV Health Care              XLY Consumer Disc.    XLP Consumer Staples
#   XLI Industrials              XLU Utilities         XLB Materials
FADED: dict[str, str] = {
    # --- Information Technology (XLK): the dot-com / hardware leaders that lagged the FAANG era ---
    "HPQ": "XLK",   # HP Inc — PC/printing, secular decline
    "DELL": "XLK",  # Dell — re-listed 2018, lagged
    "WDC": "XLK",   # Western Digital — disk drives, cyclical decline
    "STX": "XLK",   # Seagate — disk drives
    "NOK": "XLK",   # Nokia (ADR) — phone leader -> also-ran
    "ERIC": "XLK",  # Ericsson (ADR) — telecom equipment fade
    "GLW": "XLK",   # Corning — fiber/glass, flat for years
    "JNPR": "XLK",  # Juniper — networking, lagged Cisco peers
    "HPE": "XLK",   # HP Enterprise — spun 2015, lagged
    # --- Financials (XLF): the GFC / value-trap banks & insurers ---
    "AIG": "XLF",   # AIG — GFC near-death, never recovered peak
    "MET": "XLF",   # MetLife — flat insurer
    "PRU": "XLF",   # Prudential Financial
    "ALL": "XLF",   # Allstate
    "BK": "XLF",    # Bank of NY Mellon
    "USB": "XLF",   # US Bancorp — regional, lagged
    "TFC": "XLF",   # Truist (ex-BB&T/SunTrust)
    # --- Energy (XLE): the post-2014 oil-bust majors / oilfield ---
    "SLB": "XLE",   # Schlumberger — oilfield, deep decline from 2014
    "HAL": "XLE",   # Halliburton
    "OXY": "XLE",   # Occidental — leveraged, cut dividend
    "COP": "XLE",   # ConocoPhillips
    "MRO": "XLE",   # Marathon Oil
    "DVN": "XLE",   # Devon Energy
    # --- Health Care (XLV): the patent-cliff / lagging pharma ---
    "BMY": "XLV",   # Bristol-Myers — value-trap pharma
    "GILD": "XLV",  # Gilead — post-HCV-peak decline
    "AMGN": "XLV",  # Amgen
    "CVS": "XLV",   # CVS Health — retail-pharmacy fade
    "WBA": "XLV",   # Walgreens Boots — collapsed 80%+ from peak
    "BAX": "XLV",   # Baxter
    "BIIB": "XLV",  # Biogen — post-Aduhelm collapse
    # --- Consumer Discretionary (XLY): the retail / media disruptees ---
    "F": "XLY",     # Ford — legacy auto
    "GM": "XLY",    # GM (post-2010 IPO) — legacy auto
    "PARA": "XLY",  # Paramount Global — media collapse
    "WBD": "XLY",   # Warner Bros Discovery — media collapse
    "GPS": "XLY",   # Gap — mall retail decline
    "M": "XLY",     # Macy's — department-store decline
    "HBI": "XLY",   # Hanesbrands — apparel decline
    "VFC": "XLY",   # VF Corp — apparel, cut dividend, collapsed
    # --- Consumer Staples (XLP): the packaged-food / tobacco laggards ---
    "MO": "XLP",    # Altria — tobacco, secular volume decline
    "PM": "XLP",    # Philip Morris Intl
    "KHC": "XLP",   # Kraft Heinz — famous 2019 writedown collapse
    "GIS": "XLP",   # General Mills — flat packaged food
    "K": "XLP",     # Kellanova/Kellogg — flat
    "CPB": "XLP",   # Campbell Soup
    "CAG": "XLP",   # Conagra
    "KMB": "XLP",   # Kimberly-Clark
    "CL": "XLP",    # Colgate
    # --- Industrials (XLI): the conglomerate / transport laggards ---
    "X": "XLI",     # US Steel — steel, deep cyclical decline
    "FDX": "XLI",   # FedEx — lagged UPS/transport
    "EMR": "XLI",   # Emerson Electric
    "ETN": "XLI",   # Eaton
    "DE": "XLI",    # Deere
    "CMI": "XLI",   # Cummins
    "NSC": "XLI",   # Norfolk Southern
    # --- Utilities (XLU): the steady-but-flat regulated utilities ---
    "DUK": "XLU",   # Duke Energy
    "SO": "XLU",    # Southern Co
    "D": "XLU",     # Dominion — cut dividend, lagged
    "EXC": "XLU",   # Exelon
    "AEP": "XLU",   # American Electric Power
    "PEG": "XLU",   # Public Service Enterprise
    # --- Materials (XLB): the cyclical / commodity laggards ---
    "DOW": "XLB",   # Dow Inc — chemicals
    "DD": "XLB",    # DuPont de Nemours
    "FCX": "XLB",   # Freeport-McMoRan — copper, deep cyclical
    "NEM": "XLB",   # Newmont — gold miner, lagged
    "NUE": "XLB",   # Nucor — steel
    "MOS": "XLB",   # Mosaic — fertilizer, collapsed from peak
    # --- Communication / telecom (mapped to XLK-adjacent behaviour, as the existing code does for GOOGL/META) ---
    "VZ": "XLK",    # already-cached telecom (kept for completeness if re-run)
    "NWSA": "XLY",  # News Corp — media
    "FOXA": "XLY",  # Fox Corp — media
    "IPG": "XLY",   # Interpublic — ad agency, declined
    "OMC": "XLY",   # Omnicom — ad agency
}


# Yahoo renamed some tickers; map our canonical cache symbol -> the symbol Yahoo currently serves. Names absent
# here fetch under their own symbol. The genuinely-delisted (acquired/taken-private in 2024-25: X, JNPR, WBA, PARA,
# MRO, K, HBI, IPG) have NO live Yahoo series and are simply skipped — Yahoo does not serve delisted history keylessly.
YAHOO_ALIAS: dict[str, str] = {
    "GPS": "GAP",   # Gap Inc changed its ticker GPS -> GAP in 2024
    "K": "KEL",     # Kellanova trades under K; Yahoo serves the history under KEL
}


def _ssl_context() -> ssl.SSLContext:
    # macOS system Python often can't find a CA bundle for ssl.create_default_context(); prefer certifi's bundle
    # (already a dependency) so the keyless Yahoo HTTPS fetch verifies. Fall back to the default context.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — last-resort fallback to the system default
        return ssl.create_default_context()


def _fetch_chart(ticker: str) -> dict:
    """Yahoo v8 chart JSON, FULL daily history with adjusted close. We pass an explicit period1/period2 epoch range
    (NOT range=max — Yahoo silently downgrades range=max to quarterly bars) so interval=1d returns every daily bar.
    events=div,split forces the adjclose array alongside the raw quote."""
    now = int(time.time())
    query = urllib.parse.urlencode({
        "interval": "1d", "period1": 0, "period2": now, "events": "div,split",
    })
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cosmu-research)"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 — fixed host
        return json.loads(resp.read().decode("utf-8"))


def _rows_from_chart(payload: dict) -> list[dict]:
    """Build cache rows [{ts(ms), open, high, low, close, volume}] from Yahoo chart JSON.
    `close` = ADJUSTED close (split+dividend) to match the existing cache (back-adjusted). open/high/low are the
    RAW quote arrays scaled by the same adj factor (adjclose/close) so they stay split-consistent with close.
    A bar with a null close or null adjclose is skipped (NO synthetic fill)."""
    try:
        result = (payload.get("chart", {}).get("result") or [])[0]
        stamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
        adj = (((result.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        vols = quote.get("volume") or []
    except (IndexError, AttributeError, TypeError):
        return []
    rows: list[dict] = []
    for i, stamp in enumerate(stamps):
        c = closes[i] if i < len(closes) else None
        a = adj[i] if i < len(adj) else None
        if c is None or a is None or c == 0:
            continue
        factor = a / c  # adjclose / rawclose — apply to o/h/l so the OHLC stay split-consistent
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        h = highs[i] if i < len(highs) and highs[i] is not None else c
        lo = lows[i] if i < len(lows) and lows[i] is not None else c
        v = vols[i] if i < len(vols) and vols[i] is not None else 0
        rows.append({
            "ts": int(stamp) * 1000,
            "open": f"{o * factor:.6f}",
            "high": f"{h * factor:.6f}",
            "low": f"{lo * factor:.6f}",
            "close": f"{a:.6f}",
            "volume": str(int(v)),
        })
    rows.sort(key=lambda r: r["ts"])
    return rows


def _merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Append-merge by ts: the cache can only grow (idempotent). Fresh rows overwrite same-ts (re-adjustment)."""
    by_ts = {int(r["ts"]): r for r in existing}
    for r in fresh:
        by_ts[int(r["ts"])] = r
    return [by_ts[t] for t in sorted(by_ts)]


def backfill(symbols: dict[str, str] | None = None, *, sleep_s: float = 0.6) -> dict[str, int]:
    """Fetch each faded name and write/merge into the cache. Returns {symbol: n_bars_written}."""
    symbols = symbols or FADED
    CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[str, int] = {}
    for sym in symbols:
        path = CACHE / f"{sym}_1d.json"
        existing = json.loads(path.read_text()) if path.exists() else []
        yticker = YAHOO_ALIAS.get(sym, sym)
        try:
            payload = _fetch_chart(yticker)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  {sym}: FETCH FAILED ({type(e).__name__}: {e})")
            out[sym] = -1
            time.sleep(sleep_s)
            continue
        fresh = _rows_from_chart(payload)
        if not fresh:
            print(f"  {sym}: no bars returned (delisted / unknown ticker?)")
            out[sym] = 0
            time.sleep(sleep_s)
            continue
        merged = _merge(existing, fresh)
        path.write_text(json.dumps(merged))
        first = merged[0]["ts"] // 1000
        last = merged[-1]["ts"] // 1000
        import datetime as _dt
        f0 = _dt.datetime.fromtimestamp(first, _dt.UTC).date()
        f1 = _dt.datetime.fromtimestamp(last, _dt.UTC).date()
        print(f"  {sym:<6} {len(merged):>6} bars  {f0}..{f1}  (added {len(merged) - len(existing)})")
        out[sym] = len(merged)
        time.sleep(sleep_s)
    return out


def main() -> int:
    print(f"=== FADED-NAME BACKFILL — {len(FADED)} names into {CACHE} ===")
    res = backfill()
    ok = sum(1 for v in res.values() if v > 0)
    failed = [s for s, v in res.items() if v <= 0]
    print(f"\n  wrote {ok}/{len(FADED)} names; failed/empty: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
