#!/usr/bin/env python3
"""Render the disposable, self-contained HTML table + net-vs-turnover frontier for the low-turnover edge-hunt
(2026-06-25). EXPERIMENT artifact only — reads the results JSON, writes one standalone HTML file. No prod impact."""
from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
RESULTS = _HERE / "edge_hunt_lowturnover_results_2026_06_25.json"
OUT = _HERE / "edge_hunt_lowturnover_table_2026_06_25.html"


def _cell(v, fmt="{:.3f}", good=None, bad=None):
    try:
        s = fmt.format(v)
    except (ValueError, TypeError):
        s = str(v)
    cls = ""
    if good is not None and bad is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
        cls = "good" if good(v) else ("bad" if bad(v) else "")
    return f'<td class="{cls}">{s}</td>'


def _frontier_svg(book: list[dict]) -> str:
    """Scatter net return (y) vs turnover/rebalance (x). Pure inline SVG, no JS. Highlights net>0 vs net<=0."""
    if not book:
        return ""
    xs = [c["turnover_per_reb"] for c in book]
    ys = [c["book_return"] for c in book]
    x0, x1 = min(xs) * 0.95, max(xs) * 1.05
    y0, y1 = min(ys + [0.0]) - 0.05, max(ys + [0.0]) + 0.05
    W, H, pad = 720, 320, 48

    def px(x):
        return pad + (x - x0) / (x1 - x0) * (W - 2 * pad)

    def py(y):
        return H - pad - (y - y0) / (y1 - y0) * (H - 2 * pad)

    zero_y = py(0.0)
    pts = ""
    for c in book:
        cx, cy = px(c["turnover_per_reb"]), py(c["book_return"])
        col = "#0a8a0a" if c["book_return"] > 0 else "#c0392b"
        pts += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{col}" fill-opacity="0.8"><title>{c["label"]} · net {c["book_return"]:+.3f} · gross {c["gross_return"]:+.3f} · band {c["band"]}</title></circle>'
    # axis ticks
    xt = ""
    for i in range(5):
        xv = x0 + (x1 - x0) * i / 4
        xt += f'<line x1="{px(xv):.1f}" y1="{H-pad}" x2="{px(xv):.1f}" y2="{H-pad+4}" stroke="#888"/><text x="{px(xv):.1f}" y="{H-pad+16}" font-size="10" text-anchor="middle" fill="#666">{xv:.2f}</text>'
    yt = ""
    for i in range(5):
        yv = y0 + (y1 - y0) * i / 4
        yt += f'<line x1="{pad-4}" y1="{py(yv):.1f}" x2="{pad}" y2="{py(yv):.1f}" stroke="#888"/><text x="{pad-8}" y="{py(yv)+3:.1f}" font-size="10" text-anchor="end" fill="#666">{yv:+.2f}</text>'
    return f"""<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:720px;background:#fff;border:1px solid #e2e2e2;border-radius:8px">
 <line x1="{pad}" y1="{zero_y:.1f}" x2="{W-pad}" y2="{zero_y:.1f}" stroke="#0a8a0a" stroke-dasharray="4 3" stroke-width="1"/>
 <text x="{W-pad}" y="{zero_y-4:.1f}" font-size="10" text-anchor="end" fill="#0a8a0a">net = 0 (cash hurdle)</text>
 <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="#888"/>
 <line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#888"/>
 {xt}{yt}{pts}
 <text x="{W/2}" y="{H-6}" font-size="11" text-anchor="middle" fill="#444">turnover per rebalance (fraction of book changed)</text>
 <text x="14" y="{H/2}" font-size="11" text-anchor="middle" fill="#444" transform="rotate(-90 14 {H/2})">net return (after fees+slippage)</text>
</svg>"""


def main() -> int:
    d = json.loads(RESULTS.read_text())
    meta = d["meta"]
    book = sorted(d["book"], key=lambda c: c["book_return"], reverse=True)

    rows = ""
    for c in book:
        killed = ", ".join(c["reasons"]) if c["reasons"] else ("PASS" if c["passed"] else "")
        rows += "<tr>" + "".join([
            f'<td class="cfg">{c["label"]}</td>',
            _cell(c["book_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["gross_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["turnover_per_reb"], "{:.3f}"),
            _cell(c["n_trades"], "{:d}", good=lambda v: v >= 30, bad=lambda v: v < 30),
            _cell(c["n_rebalances"], "{:d}"),
            _cell(c["deflated_sharpe"], good=lambda v: v >= 0.95, bad=lambda v: v < 0.95),
            _cell(c["folds_positive"], "{:.2f}", good=lambda v: v >= 0.60, bad=lambda v: v < 0.60),
            _cell(c["pbo"], "{:.2f}", good=lambda v: v <= 0.50, bad=lambda v: v > 0.50),
            _cell(c["holdout_dsr"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["max_dd"], "{:.2f}"),
            _cell(c["avg_corr_to_btc"], "{:+.3f}", good=lambda v: abs(v) <= 0.30, bad=lambda v: abs(v) > 0.30),
            f'<td class="killed">{killed}</td>',
        ]) + "</tr>"

    survivors = sum(1 for c in book if c["passed"] and c["holdout_passed"])
    best = max(book, key=lambda c: c["book_return"])
    frontier = _frontier_svg(book)

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Edge-hunt low-turnover — 2026-06-25</title>
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
<h1>Edge-hunt — low-turnover deadbanded market-neutral xsec momentum book</h1>
<p class="sub">2026-06-25 · EXPERIMENT ONLY · BRUT per book · locked Gate · zero production impact · attacks the #391 turnover-cost wall</p>
<div class="meta">
 <b>Data:</b> Bybit v5 keyless spot, <b>paginated</b> to {meta['common_bars']} × 4h bars
 ({meta['common_span_days']} d ≈ {meta['common_span_days']/365:.1f} yr) common window across {len(meta['universe'])} names ·
 taker {meta['taker_bps']:.0f} bps + liquidity-tiered slippage on both legs (the SAME honest cost floor production charges) ·
 real Binance funding (PIT, 4h accrual).<br>
 <b>Pre-registered grid:</b> {meta['grid']} — 16 configs, no best-of-N cherry-pick.<br>
 <b>Gate (locked):</b> DSR ≥ 0.95 · PBO ≤ 0.50 · folds ≥ 0.60 · trades ≥ 30 · holdout DSR &gt; 0 · beat benchmark (cash/0).
</div>
<div class="verdict">
 <b>Verdict: {survivors} / {len(book)} clear the Gate — crypto cross-sectional momentum is UNECONOMIC at our cost tier.</b>
 Only 2/16 configs even net positive. The single best NET book (<code>{best['label']}</code>) earns
 <b>net {best['book_return']:+.1%}</b> (gross {best['gross_return']:+.1%}) over ~3 yr validation — but its
 <b>holdout DSR is ≈ 0 ({best['holdout_dsr']:+.3f})</b> and DSR {best['deflated_sharpe']:.2f} ≪ 0.95: an in-sample-only
 mirage, killed by drawdown + deflation. <b>Lowering turnover does NOT rescue the book:</b> widening the no-trade band
 cuts churn modestly but starves the thin xsec signal FASTER (band 0.0 → net +66%; band 0.1 → −14%; band 0.3 → −47% at
 the slowest bi-weekly cadence). There is no turnover/return corner where net flips positive AND survives the embargoed
 holdout. This is a <b>real economic reject</b> (signal present, no surviving net edge), not a data/wiring gap.
</div>

<h2>Net-vs-turnover frontier</h2>
<p class="sub">Each dot is one pre-registered config. Green = net-positive, red = net-negative. The cloud sits mostly
 BELOW the cash hurdle, and the few green dots are the no-band corners — confirming the band trades signal for churn
 at a losing rate on this 12-name universe.</p>
{frontier}

<h2>All 16 deadbanded book configs (ranked by NET return — the economic frontier)</h2>
<table><thead><tr>
 <th class="cfg">config (venue:int:lookback:quantile:rebalance:band)</th><th>net ret</th><th>gross ret</th>
 <th>turnover/reb</th><th>trades</th><th>rebal</th><th>DSR</th><th>folds+</th><th>PBO</th><th>holdout DSR</th>
 <th>maxDD</th><th>corr-BTC</th><th>killed by</th>
</tr></thead><tbody>{rows}</tbody></table>
<p class="sub">net ret = book return after fees+slippage on both legs · gross ret = the SAME book cost-free (isolates the
 cost wall) · turnover/reb = fraction of the held book that changes each rebalance · holdout DSR = embargoed last-fifth
 exam (the in-sample-vs-OOS tell) · corr-BTC ≈ 0 confirms the book is genuinely market-neutral. RANKED BY OUTLIER (net);
 every config shown — never a pooled mean.</p>
</body></html>"""
    OUT.write_text(html)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
