# intent: the LIVE run behind docs/research/polymarket-live-opportunities-2026-06-29.md — the LLM/Conviction
# lane made concrete. It (1) scans live Polymarket (keyless Gamma) for the highest-leverage macro/geo/commodity/
# rates event markets via cosmu.research.polymarket_correlation.LiveEventScanner, (2) for each mappable top
# market pulls the daily YES-probability history (PerMarketOddsSource, keyless CLOB) and the CLOCK-ALIGNED
# correlated-asset price series (FRED daily CSV — the only free source on the SAME calendar as Gamma in this
# environment; Yahoo is a year off), and (3) runs the honest lead_lag_profile to decide LEADS vs COINCIDENT.
# Propose-only — it prints/writes a watchlist + lead-lag verdicts + any Conviction proposal; it NEVER trades
# and NEVER touches the Gate. Re-runnable; writes a results JSON next to this file.
#
# Price source — Yahoo chart API (keyless, reliable): in this environment Gamma + Yahoo return the SAME 2026
# calendar (Yahoo CL=F tracks the FRED WTI 2026 crash shape-for-shape, ~$3 spot-vs-futures basis), so the
# lead-lag join is clock-aligned. We use the futures/yield instruments directly: crude (CL=F / BZ=F) and the
# Fed path (^IRX 13-week T-bill — the most policy-sensitive yield over a single-meeting horizon — and ^TNX 10Y).
# (FRED's fredgraph.csv is an equally clock-aligned alternative but throttles burst requests from one IP.)
# Energy-equity / gold links are documented in EVENT_THEMES but NOT lead-lag-measured here — that limitation is
# reported honestly, never papered over.
#
# ⚠️ DAILY TIMESTAMP CAVEAT (see lead_lag_profile docstring): the CLOB daily bucket is stamped 00:00 UTC while
# the oil close is ~20:00 UTC, so a calendar-date join already hands the PM series a ~1-day head start. A lag+1
# "LEADS" here is therefore UNCONFIRMED until re-run hourly — the runner prints the verdict but the doc reads it
# as 'correlation present, direction-consistent, lead unconfirmed'.

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

_ENGINE_ROOT = Path(__file__).resolve().parents[2]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from cosmu.data.sources.polymarket import PerMarketOddsSource  # noqa: E402
from cosmu.research.polymarket_correlation import (  # noqa: E402
    LiveEventScanner,
    lead_lag_profile,
)

_RESULTS_JSON = Path(__file__).resolve().parent / "polymarket_live_opportunities_2026_06_30_results.json"

# theme → the Yahoo symbol(s) that are clock-aligned to the Gamma 2026 calendar. Only crude + rates are
# measurable here; the macro/geopolitics gold/equity links live in EVENT_THEMES for documentation but are not
# lead-lag-measured (a gold/equity link would need the same care; left as a documented follow-up).
_THEME_YAHOO = {
    "oil_geopolitics": [("WTI front-month (CL=F)", "CL=F"), ("Brent front-month (BZ=F)", "BZ=F")],
    "us_rates": [("13-week T-bill yield (^IRX)", "^IRX"), ("10Y Treasury yield (^TNX)", "^TNX")],
}

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def yahoo_daily(symbol: str, *, lookback_days: int = 95, cache_dir: Path | None = None,
                tries: int = 4) -> dict[str, float]:
    """A Yahoo daily close series as {YYYY-MM-DD: close} over the last `lookback_days`, keyless. The bar
    timestamp is the session date; we key by that calendar date (see the module's DAILY TIMESTAMP CAVEAT for
    why the intra-day stamp matters for lead-lag). Optional on-disk cache so re-runs are free."""
    safe = symbol.replace("=", "_").replace("^", "idx_")
    cache = (cache_dir / f"yh_{safe}.json") if cache_dir else None
    if cache and cache.exists() and cache.stat().st_size > 0:
        return {k: float(v) for k, v in json.loads(cache.read_text()).items()}
    now = datetime.now(tz=UTC)
    p2 = int(now.timestamp()) + 86400
    p1 = p2 - lookback_days * 86400
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?period1={p1}&period2={p2}&interval=1d")
    last: Exception | None = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            res = payload["chart"]["result"][0]
            ts = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            out = {
                datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%d"): float(c)
                for t, c in zip(ts, closes, strict=False)
                if c is not None
            }
            if cache:
                cache.write_text(json.dumps(out))
            return out
        except Exception as e:  # noqa: BLE001 — best-effort; give up gracefully so one dead symbol isn't fatal
            last = e
            time.sleep(2.0 * (i + 1))
    print(f"  [warn] Yahoo {symbol} unavailable: {last}")
    return {}


def prob_series(condition_id: str, src: PerMarketOddsSource) -> dict[str, float]:
    """Daily YES-probability {YYYY-MM-DD: prob} for one conditionId via the keyless CLOB (PerMarketOddsSource)."""
    return {p.ts.strftime("%Y-%m-%d"): p.value for p in src.fetch_odds(condition_id, fidelity=1440)}


def run(*, top_n: int = 15, cache_dir: Path | None = None) -> dict:
    now = datetime.now(tz=UTC)
    scanner = LiveEventScanner()
    print(f"[scan] live Polymarket Gamma @ {now.isoformat()} ...")
    watchlist = scanner.scan(top_n=top_n)
    print(f"[scan] {len(watchlist)} mappable high-leverage markets\n")
    for i, c in enumerate(watchlist, 1):
        print(f"  {i:>2}. lev={c.leverage:6.2f}  {c.theme:<18} p={c.yes_prob}  d2e={c.days_to_event:.0f}  "
              f"liq=${c.liquidity:,.0f}  vol24=${c.volume_24h:,.0f}")
        print(f"      {c.question[:90]}")

    src = PerMarketOddsSource()
    plays: list[dict] = []
    # Deep lead-lag on every mappable candidate whose theme has a clock-aligned price series.
    px_cache: dict[str, dict[str, float]] = {}
    for c in watchlist:
        links = _THEME_YAHOO.get(c.theme or "")
        if not links or not c.condition_id:
            continue
        probs = prob_series(c.condition_id, src)
        if len(probs) < 6:
            print(f"\n[skip] {c.question[:60]} — only {len(probs)} prob days")
            continue
        print(f"\n[measure] {c.question[:70]}  ({len(probs)} prob days)")
        results = []
        for label, sym in links:
            if sym not in px_cache:
                px_cache[sym] = yahoo_daily(sym, cache_dir=cache_dir)
            px = px_cache[sym]
            res = lead_lag_profile(probs, px, asset=label, max_lag=2)
            results.append(res)
            print(f"    {label:<28} N={res.n_paired:>2}  corr_by_lag={res.corr_by_lag}  "
                  f"sig≈{res.sig_threshold}  => {res.verdict}")
        plays.append({
            "question": c.question,
            "condition_id": c.condition_id,
            "theme": c.theme,
            "yes_prob": c.yes_prob,
            "days_to_event": c.days_to_event,
            "leverage": c.leverage,
            "asset_links": [asdict(a) for a in c.asset_links],
            "lead_lag": [asdict(r) for r in results],
        })

    out = {
        "generated_at": now.isoformat(),
        "watchlist": [asdict(c) for c in watchlist],
        "plays": plays,
    }
    _RESULTS_JSON.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] wrote {_RESULTS_JSON}")
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Live Polymarket→correlated-asset opportunity scan + lead-lag.")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--cache-dir", type=str, default=None, help="dir of pre-fetched fred_<id>.csv files")
    args = ap.parse_args()
    run(top_n=args.top, cache_dir=Path(args.cache_dir) if args.cache_dir else None)
