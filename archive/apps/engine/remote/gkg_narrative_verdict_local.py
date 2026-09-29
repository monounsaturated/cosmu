# intent: the LOCAL fallback for the LLM-narrative VERDICT stage — Binance 451-geo-blocks from Modal's
# datacenter, so the verdict (which needs crypto spot bars) runs on the M2 instead, loading the DEEP daily
# scores downloaded from the cosmu-gkg-narrative Modal volume into /tmp/gkg_daily_scores. Only the bars-fetch
# path differs from remote/gkg_narrative.py::verdict(); the gate/holdout/disconfirmer logic is identical.
"""Local LLM-narrative VERDICT runner.

Mirrors remote/gkg_narrative.py::verdict() EXACTLY — loads the DEEP daily PIT narrative scores
materialized by the Modal score stage, fetches real daily bars, and runs the UNCHANGED
research.llm_narrative_cohort.run_cohort harness per asset (promote_cohort BH-FDR q=0.10 ONLY,
REAL purged+embargoed holdout, time-shuffle placebo + momentum-only control disconfirmers,
PIT fees). The ONLY deviation from the Modal function is the bars-fetch path, because:
  * Binance returns 451 (geo-block) from the Modal datacenter -> run crypto bars locally (reachable here).
  * Stooq is serving an anti-bot JS challenge AND Yahoo range=max silently downgrades to MONTHLY bars,
    so equities use Yahoo with an EXPLICIT period1/period2 epoch range (forces true daily granularity).
Neither touches the gate/scoring/holdout/disconfirmer logic — only how price bars arrive.
"""
from __future__ import annotations

import datetime as _dt
import json
import ssl
import tempfile
import urllib.request
from decimal import Decimal
from pathlib import Path

import certifi

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.knowledge.store import Store
from cosmu.research.gkg_corpus import DEFAULT_UNIVERSE
from cosmu.research.llm_narrative_cohort import run_cohort

SCORES_DIR = Path("/tmp/gkg_daily_scores")


def _load_daily_points(symbol: str) -> list[AltDataPoint]:
    path = SCORES_DIR / f"{symbol}.jsonl"
    if not path.exists():
        return []
    pts = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        pts.append(
            AltDataPoint(
                ts=_dt.datetime.fromisoformat(d["ts"]),
                available_at=_dt.datetime.fromisoformat(d["available_at"]),
                value=float(d["value"]),
            )
        )
    return sorted(pts, key=lambda p: p.ts)


def _yahoo_daily(symbol: str, start: _dt.date, end: _dt.date) -> list[Bar]:
    """True daily equity/ETF bars via Yahoo with an EXPLICIT epoch window (range=max gives MONTHLY)."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    p1 = int(_dt.datetime(start.year, start.month, start.day, tzinfo=_dt.UTC).timestamp())
    p2 = int(_dt.datetime(end.year, end.month, end.day, tzinfo=_dt.UTC).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={p1}&period2={p2}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    res = (payload.get("chart", {}).get("result") or [{}])[0]
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    out: list[Bar] = []
    for i, ts in enumerate(timestamps):
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, lo, c):
            continue
        out.append(
            Bar(
                ts=_dt.datetime.fromtimestamp(int(ts), tz=_dt.UTC),
                open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(lo)),
                close=Decimal(str(c)),
                volume=Decimal(str(volumes[i] if i < len(volumes) and volumes[i] is not None else 0)),
            )
        )
    return sorted(out, key=lambda b: b.ts)


def _bars_for(symbol: str, kind: str, lo: _dt.date, hi: _dt.date) -> list[Bar]:
    if kind == "crypto":
        return BinanceSpotOHLCVProvider().fetch_bars(symbol, "1d", limit=1400)
    return _yahoo_daily(symbol, lo - _dt.timedelta(days=30), hi + _dt.timedelta(days=2))


def main() -> None:
    kind_of = {a.symbol: a.kind for a in DEFAULT_UNIVERSE}
    # Report order matches the prompt's score depths.
    targets = ["BTCUSDT", "QQQ", "META", "ETHUSDT", "MSFT", "AAPL", "TSLA", "GOOGL", "NVDA", "AMZN"]

    results: dict[str, dict] = {}
    for sym in targets:
        points = _load_daily_points(sym)
        if not points:
            results[sym] = {"verdict": "NO-SCORES"}
            print(f"[verdict] {sym}: NO-SCORES", flush=True)
            continue
        lo = min(p.available_at for p in points).date()
        hi = max(p.available_at for p in points).date()
        try:
            bars = _bars_for(sym, kind_of.get(sym, "equity"), lo, hi)
        except Exception as exc:  # noqa: BLE001
            results[sym] = {"verdict": "BARS-ERROR", "note": f"{type(exc).__name__}: {exc}"}
            print(f"[verdict] {sym}: BARS-ERROR {type(exc).__name__}: {exc}", flush=True)
            continue
        if len(bars) < 80:
            results[sym] = {"verdict": "NO-BARS", "note": f"only {len(bars)} bars"}
            print(f"[verdict] {sym}: NO-BARS ({len(bars)})", flush=True)
            continue
        market = {sym: bars}
        tmp = tempfile.mkdtemp(prefix="cosmu-gkg-")
        store = Store(Settings(database_url=f"sqlite:///{tmp}/v.sqlite3", openrouter_api_key=None))
        rep = run_cohort(market, points, store, symbol=sym, data_source="gdelt-gkg+openrouter")
        results[sym] = {
            "verdict": rep.verdict,
            "headline": rep.headline,
            "window": rep.window,
            "narrative_days": rep.narrative_points,
            "disconfirmers": rep.disconfirmers,
            "members": [
                {
                    "name": m.name, "net": m.net_return, "gross": m.gross_return,
                    "dsr": m.deflated_sharpe_prob, "holdout_dsr": m.holdout_deflated_sharpe,
                    "pbo": m.cscv_pbo, "trades": m.num_trades, "beat_bh": m.beat_buy_and_hold,
                    "promoted": m.promoted, "survived_fdr": m.survived_fdr,
                }
                for m in rep.members
            ],
            "notes": rep.notes,
        }
        print(f"[verdict] {sym}: {rep.verdict} — {rep.headline}", flush=True)
        print(f"    window={rep.window} narrative_days={rep.narrative_points} bars={len(bars)}", flush=True)
        for m in rep.members:
            flag = "PROMOTED" if m.promoted else ("fdr" if m.survived_fdr else "stop")
            print(
                f"    [{flag:>8}] {m.name:<30} net={m.net_return:+.4f} gross={m.gross_return:+.4f} "
                f"dsr={m.deflated_sharpe_prob:.3f} holdoutDSR={m.holdout_deflated_sharpe:+.3f} "
                f"pbo={m.cscv_pbo:.3f} trades={m.num_trades} b&h={'Y' if m.beat_buy_and_hold else 'N'}",
                flush=True,
            )
        for k, v in rep.disconfirmers.items():
            print(f"      {k}: {v}", flush=True)
        for n in rep.notes:
            print(f"      note: {n}", flush=True)

    Path("/tmp/gkg_verdict_results.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n=== SUMMARY ===", flush=True)
    for sym, r in results.items():
        print(f"  {sym:8} {r['verdict']}", flush=True)


if __name__ == "__main__":
    main()
