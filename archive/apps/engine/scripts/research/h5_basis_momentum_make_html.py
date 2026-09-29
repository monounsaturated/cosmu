#!/usr/bin/env python3
"""Render the disposable, self-contained HTML table for the H5 basis-momentum edge-hunt (2026-06-25).
EXPERIMENT artifact only — reads the results JSON, writes one standalone HTML file. No prod impact."""
from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
RESULTS = _HERE / "h5_basis_momentum_results_2026_06_25.json"
OUT = _HERE / "h5_basis_momentum_table_2026_06_25.html"


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
    pre = next((c for c in d["book"] if c.get("pre_registered")), None)

    rows = ""
    for c in book:
        killed = ", ".join(c["reasons"]) if c["reasons"] else ("PASS" if c["passed"] else "")
        cfg_cls = "cfg pre" if c.get("pre_registered") else "cfg"
        rows += "<tr>" + "".join([
            f'<td class="{cfg_cls}">{c["label"]}</td>',
            _cell(c["deflated_sharpe"], good=lambda v: v >= 0.95, bad=lambda v: v < 0.95),
            _cell(c["sharpe_ann"], "{:.2f}"),
            _cell(c["n_trades"], "{:d}", good=lambda v: v >= 30, bad=lambda v: v < 30),
            _cell(c["n_rebalances"], "{:d}"),
            _cell(c["folds_positive"], "{:.2f}", good=lambda v: v >= 0.60, bad=lambda v: v < 0.60),
            _cell(c["pbo"], "{:.2f}", good=lambda v: v <= 0.50, bad=lambda v: v > 0.50),
            _cell(c["book_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["gross_return"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["alpha_ann"], "{:+.3f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            _cell(c["beta_btc"], "{:+.2f}"),
            _cell(c["alpha_t"], "{:+.2f}", good=lambda v: v > 1.64, bad=lambda v: v <= 0),
            _cell(c["avg_corr_to_btc"], "{:+.3f}", good=lambda v: abs(v) <= 0.30, bad=lambda v: abs(v) > 0.30),
            _cell(c["holdout_dsr"], "{:+.2f}", good=lambda v: v > 0, bad=lambda v: v <= 0),
            f'<td class="killed">{killed}</td>',
        ]) + "</tr>"

    pre_block = ""
    if pre:
        go = pre["passed"] and pre["holdout_passed"]
        pre_block = (
            f"<b>config</b> <code>{pre['label']}</code> · "
            f"<b>N</b> {pre['n_trades']:,} leg-trades · "
            f"<b>net</b> {pre['book_return']:+.3f} (gross {pre['gross_return']:+.3f}) · "
            f"<b>residual α</b> {pre['alpha_ann']:+.3f}/yr (t={pre['alpha_t']:+.2f}) · "
            f"<b>β-BTC</b> {pre['beta_btc']:+.3f} · <b>corr-BTC</b> {pre['avg_corr_to_btc']:+.3f} · "
            f"<b>DSR</b> {pre['deflated_sharpe']:.3f} · <b>holdout DSR</b> {pre['holdout_dsr']:+.3f}<br>"
            f"<b>verdict: {'GO' if go else 'KILL'}</b>"
        )

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>H5 basis-momentum carry — 2026-06-25</title>
<style>
 body{{font:13px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
 h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 8px}}
 .sub{{color:#666;margin:0 0 16px}} .meta{{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:10px 14px;margin:0 0 12px;font-size:12px}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:12px;box-shadow:0 1px 2px rgba(0,0,0,.05)}}
 th,td{{padding:4px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap}}
 th{{background:#f0f0f0;position:sticky;top:0;text-align:right;font-weight:600}}
 td.cfg,th.cfg{{text-align:left;font-family:ui-monospace,Menlo,monospace;font-size:11px}}
 td.pre{{font-weight:700;color:#7a4d00;background:#fff8e6}}
 td.killed{{text-align:left;color:#b00;font-size:11px}}
 td.good{{background:#e7f7e7;color:#0a0}} td.bad{{background:#fdeaea;color:#b00}}
 .verdict{{background:#fff3cd;border:1px solid #ffd24d;border-radius:8px;padding:10px 14px;margin:8px 0 16px}}
 code{{background:#eee;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>H5 — basis-momentum carry (d(basis)/dt cross-sectional book)</h1>
<p class="sub">2026-06-25 · EXPERIMENT ONLY · slate #6 · BRUT per config · locked Gate + decisive β-orthogonality · zero production impact</p>
<div class="meta">
 <b>Thesis:</b> ride an ACCELERATING perp-spot basis — trade the TIME-DERIVATIVE d(basis)/dt, not the level
 (level-fade tested elsewhere). A different family from price-momentum.<br>
 <b>Basis:</b> reconstructed honestly as <code>(perp_close − spot_close)/spot_close</code> (the registered
 tier0 <code>perp_spot_basis</code> = (mark−index)/index shape, PIT, evaluated at bar close).<br>
 <b>Data:</b> Bybit v5 keyless, <b>paginated</b> SPOT+PERP to {meta['common_bars']:,} × 4h bars/leg
 ({meta['common_span_days']} d ≈ {meta['common_span_days']/365:.2f} yr) common window across {len(meta['universe'])} names ·
 taker {meta['taker_bps']:.0f} bps + liquidity-tiered slippage on both legs · real Binance funding (PIT, 4h accrual).<br>
 <b>Gate (locked):</b> DSR ≥ 0.95 · PBO ≤ 0.50 · folds ≥ 0.60 · trades ≥ 30 · holdout DSR &gt; 0 ·
 <b>+ decisive: residual α &gt; 0</b> (regress book on BTC B&amp;H; α must NOT collapse to β).<br>
 <b>Pre-registered config:</b> lb={meta['pre_registered']['lookback']} (24h) · quantile={meta['pre_registered']['quantile']} (tertile) ·
 rebalance every {meta['pre_registered']['rebalance']} bars (~daily). One point; grid is diagnostic only.
</div>
<div class="verdict">
 <b>Verdict: 0 survivors — clean KILL.</b> {pre_block}<br><br>
 The β-test is unambiguous: the book IS genuinely market-neutral (β-BTC ≈ 0, corr-BTC ≈ 0), so this is
 <b>NOT</b> disguised bull-beta — that failure mode is ruled out. But the residual α is <b>NEGATIVE</b>
 (≈ −40%/yr, t ≈ −2.5): the basis-momentum spread carries <b>negative skill</b>, not zero. Even gross, most
 configs lose; the high-turnover spread (≈ 11.9k leg-trades) is then buried by two-leg cost. This confirms the
 prior — crypto carry/basis on liquid majors is arbitraged out and chasing its <i>acceleration</i> loses net of fees.
</div>

<h2>Every basis-momentum book config (ranked by deflated Sharpe) — pre-registered row highlighted</h2>
<table><thead><tr>
 <th class="cfg">config</th><th>DSR</th><th>Sharpe</th><th>trades</th><th>rebal</th><th>folds+</th><th>PBO</th>
 <th>net ret</th><th>gross ret</th><th>α /yr</th><th>β-BTC</th><th>α t-stat</th><th>corr-BTC</th><th>holdout DSR</th><th>killed by</th>
</tr></thead><tbody>{rows}</tbody></table>
<p class="sub">net ret = book return after fees+slippage on both legs · gross ret = the SAME book cost-free
(isolates the cost wall) · α /yr = annualized residual intercept of <code>r_book = α + β·r_btc</code> NET of fees
(the decisive disconfirmer — must be &gt; 0) · β-BTC ≈ 0 + corr-BTC ≈ 0 confirm the book is genuinely
market-neutral (so a positive return could NOT be disguised beta) · α t-stat &lt; 0 means the negative skill is
statistically real, not noise.</p>
</body></html>"""
    OUT.write_text(html)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
