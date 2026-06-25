#!/usr/bin/env python3
"""Render the disposable, self-contained HTML table for the market-neutral edge-hunt (2026-06-25).
EXPERIMENT artifact only — reads the results JSON, writes one standalone HTML file. No prod impact."""
from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
RESULTS = _HERE / "edge_hunt_mktneutral_results_2026_06_25.json"
OUT = _HERE / "edge_hunt_mktneutral_table_2026_06_25.html"


def _cell(v, fmt="{:.3f}", good=None, bad=None):
    try:
        s = fmt.format(v)
    except (ValueError, TypeError):
        s = str(v)
    cls = ""
    if good is not None and bad is not None and isinstance(v, (int, float)):
        cls = "good" if good(v) else ("bad" if bad(v) else "")
    return f'<td class="{cls}">{s}</td>'


def main() -> int:
    d = json.loads(RESULTS.read_text())
    meta = d["meta"]
    book = sorted(d["book"], key=lambda c: c["deflated_sharpe"], reverse=True)
    fund = sorted([c for c in d["funding_percentile"] if c["n_trades"] >= 5],
                  key=lambda c: c["deflated_sharpe"], reverse=True)

    book_rows = ""
    for c in book:
        killed = ", ".join(c["reasons"]) if c["reasons"] else ("PASS" if c["passed"] else "")
        book_rows += "<tr>" + "".join([
            f'<td class="cfg">{c["label"]}</td>',
            _cell(c["deflated_sharpe"], good=lambda v: v >= 0.95, bad=lambda v: v < 0.95),
            _cell(c["sharpe_ann"], "{:.2f}"),
            _cell(c["n_trades"], "{:d}", good=lambda v: v >= 30, bad=lambda v: v < 30),
            _cell(c["n_rebalances"], "{:d}"),
            _cell(c["folds_positive"], "{:.2f}", good=lambda v: v >= 0.60, bad=lambda v: v < 0.60),
            _cell(c["pbo"], "{:.2f}", good=lambda v: v <= 0.50, bad=lambda v: v > 0.50),
            _cell(c["book_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["gross_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["long_only_bh"], "{:+.3f}"),
            _cell(c["holdout_dsr"], "{:+.2f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["avg_corr_to_btc"], "{:+.3f}", good=lambda v: abs(v) <= 0.30, bad=lambda v: abs(v) > 0.30),
            f'<td class="killed">{killed}</td>',
        ]) + "</tr>"

    fund_rows = ""
    for c in fund:
        killed = ", ".join(c["reasons"]) if c["reasons"] else ("PASS" if c["passed"] else "")
        fund_rows += "<tr>" + "".join([
            f'<td class="cfg">{c["label"]}</td>',
            _cell(c["deflated_sharpe"], good=lambda v: v >= 0.95, bad=lambda v: v < 0.95),
            _cell(c["n_trades"], "{:d}", good=lambda v: v >= 30, bad=lambda v: v < 30),
            _cell(c["folds_positive"], "{:.2f}", good=lambda v: v >= 0.60, bad=lambda v: v < 0.60),
            _cell(c["book_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["buy_and_hold"], "{:+.3f}"),
            _cell(c["beat_bh"], "{}", good=lambda v: bool(v), bad=lambda v: not v),
            _cell(c["holdout_dsr"], "{:+.2f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            f'<td class="killed">{killed}</td>',
        ]) + "</tr>"

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Edge-hunt market-neutral — 2026-06-25</title>
<style>
 body{{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
 h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 8px}}
 .sub{{color:#666;margin:0 0 16px}} .meta{{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:10px 14px;margin:0 0 12px;font-size:12px}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:12px;box-shadow:0 1px 2px rgba(0,0,0,.05)}}
 th,td{{padding:4px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap}}
 th{{background:#f0f0f0;position:sticky;top:0;text-align:right;font-weight:600}}
 td.cfg,th.cfg{{text-align:left;font-family:ui-monospace,Menlo,monospace;font-size:11px}}
 td.killed{{text-align:left;color:#b00;font-size:11px}}
 td.good{{background:#e7f7e7;color:#0a0}} td.bad{{background:#fdeaea;color:#b00}}
 .verdict{{background:#fff3cd;border:1px solid #ffd24d;border-radius:8px;padding:10px 14px;margin:8px 0 16px}}
 code{{background:#eee;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>Edge-hunt — market-neutral xsec book + continuous funding percentile</h1>
<p class="sub">2026-06-25 · EXPERIMENT ONLY · BRUT per combo · locked Gate · zero production impact</p>
<div class="meta">
 <b>Data:</b> Bybit v5 keyless spot, <b>paginated</b> to {meta['common_bars']} × 4h bars
 ({meta['common_span_days']} d ≈ {meta['common_span_days']/365:.1f} yr) common window across {len(meta['universe'])} names ·
 taker {meta['taker_bps']:.0f} bps + liquidity-tiered slippage on both legs · real Binance funding (PIT, 4h accrual).<br>
 <b>Gate (locked):</b> DSR ≥ 0.95 · PBO ≤ 0.50 · folds ≥ 0.60 · trades ≥ 30 · holdout DSR &gt; 0 · beat benchmark.
</div>
<div class="verdict">
 <b>Verdict: 0 survivors — but both #390 walls broke.</b>
 The <b>trade-count wall</b> is gone (every book fires 3k–24k trades; 1.3k–7.9k rebalances).
 The <b>B&amp;H-beta wall</b> is gone (book corr-to-BTC ≈ 0 — genuinely market-neutral by construction).
 The gross L/S momentum spread is REAL (best book <b>gross +89%</b>), but it is <b>entirely eaten by turnover cost</b>
 (every config nets negative). The binding limit moved from DATA/SIGNAL to <b>CAPACITY / cost-per-turnover</b>.
</div>

<h2>Theme A — market-neutral cross-sectional momentum BOOK (long leaders − short laggards)</h2>
<table><thead><tr>
 <th class="cfg">config</th><th>DSR</th><th>Sharpe</th><th>trades</th><th>rebal</th><th>folds+</th><th>PBO</th>
 <th>net ret</th><th>gross ret</th><th>long-B&amp;H</th><th>holdout DSR</th><th>corr-BTC</th><th>killed by</th>
</tr></thead><tbody>{book_rows}</tbody></table>
<p class="sub">net ret = book return after fees+slippage on both legs · gross ret = the SAME book cost-free (isolates the
cost wall) · long-B&amp;H = the OLD long-only hurdle #390 measured (irrelevant to a neutral book; shown for contrast)
· corr-BTC ≈ 0 confirms the beta cancelled.</p>

<h2>Theme B — funding-contrarian as a CONTINUOUS funding percentile (per symbol, 4h) — top 15 by DSR</h2>
<table><thead><tr>
 <th class="cfg">config</th><th>DSR</th><th>trades</th><th>folds+</th><th>net ret</th><th>B&amp;H</th><th>beat B&amp;H</th>
 <th>holdout DSR</th><th>killed by</th>
</tr></thead><tbody>{fund_rows}</tbody></table>
<p class="sub">The hard oversold-RSI conjunction (#390, fired ≤4 trades) is dropped for a rolling funding-percentile
trigger. It now fires 150–320 trades — the #390 funding wall is broken — and the best (LTC) even beats its own B&amp;H,
but no config clears DSR 0.95 and holdout collapses (in-sample-only edge).</p>
</body></html>"""
    OUT.write_text(html)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
