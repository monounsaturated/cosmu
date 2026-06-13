#!/usr/bin/env python3
"""v8 — base = cosmu-final-v7. Output: cosmu-final-v8.html
 - dashboard Recent-trades & Open-positions: "See all" toggle in the header (limit rows first)
 - column picker closes immediately when a strategy panel opens
 - removed the zoom:1.1 hack -> normal macOS/Chrome sizing that scales properly with browser
   zoom and is sane on mobile (revert the dependent /1.1 calcs)
 - costs chart: the today-dot was an SVG <circle> that stretched into an ellipse under
   preserveAspectRatio=none -> moved to an HTML dot (no distortion); labels already HTML
 - strat-sheet chart gets its bento inset back (cleaner separation from the AI summary below)
"""
import pathlib

html = pathlib.Path("mockups/cosmu-final-v7.html").read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:55]!r}], found {c}"
    html = html.replace(old, new)

# ── dashboard See-all on trades + positions ──────────────────────────────────────
repl(
"""function tradesBox(which){var tr=DASH[which].trades;var rows=tr.map(function(x){return '<tr><td class="muted" style="white-space:nowrap">'+new Date(x[0]+'T00:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})+' <span style="color:var(--quiet)">'+x[1]+'</span></td><td><span class="strat-link" onclick="gotoStrat(\\''+x[2]+'\\')">'+x[2]+'</span></td><td class="side-'+(x[3]==='Buy'?'buy':'sell')+'">'+x[3]+'</td><td class="r tab">'+x[4]+'</td><td class="r tab '+(x[5]?(x[5][0]==='-'?'dn':'up'):'muted')+'">'+(x[5]||'open')+'</td></tr>';}).join('');
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Recent trades</span></div><div class="card-body" style="max-height:260px;overflow-y:auto"><table class="mini-tbl"><thead><tr><th>Date · time</th><th>Strategy</th><th>Side</th><th class="r">Price</th><th class="r">P&L</th></tr></thead><tbody>'+rows+'</tbody></table></div></div>';}""",
"""function dashSeeAll(btn){var card=btn.closest('.card');var on=card.classList.toggle('dash-open');btn.textContent=on?'Show less':'See all \\u2192';}
function tradesBox(which){var tr=DASH[which].trades;var LIM=4;var rows=tr.map(function(x,i){return '<tr'+(i>=LIM?' class="dash-extra"':'')+'><td class="muted" style="white-space:nowrap">'+new Date(x[0]+'T00:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})+' <span style="color:var(--quiet)">'+x[1]+'</span></td><td><span class="strat-link" onclick="gotoStrat(\\''+x[2]+'\\')">'+x[2]+'</span></td><td class="side-'+(x[3]==='Buy'?'buy':'sell')+'">'+x[3]+'</td><td class="r tab">'+x[4]+'</td><td class="r tab '+(x[5]?(x[5][0]==='-'?'dn':'up'):'muted')+'">'+(x[5]||'open')+'</td></tr>';}).join('');
 var sa=tr.length>LIM?'<button class="seeall-btn" onclick="dashSeeAll(this)">See all \\u2192</button>':'';
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Recent trades</span>'+sa+'</div><div class="card-body"><table class="mini-tbl"><thead><tr><th>Date · time</th><th>Strategy</th><th>Side</th><th class="r">Price</th><th class="r">P&L</th></tr></thead><tbody>'+rows+'</tbody></table></div></div>';}""")

repl(
"""function positions(which){var arr=DASH[which].positions||[];var p=arr.map(function(x){var cls=x.pnl[0]==='-'?'dn':'up';return '<tr><td><span class="strat-link" onclick="gotoStrat(\\''+x.n+'\\')">'+x.n+'</span></td><td class="muted">'+x.sym+'</td><td class="r tab">'+x.qty+'</td><td class="r tab">'+x.mark+'</td><td class="r tab '+cls+'">'+x.pnl+' '+x.pct+'</td></tr>';}).join('');
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Open positions</span></div><div class="card-body"><table class="mini-tbl"><thead><tr><th>Strategy</th><th>Pair</th><th class="r">Size</th><th class="r">Value</th><th class="r">P&L</th></tr></thead><tbody>'+p+'</tbody></table></div></div>';}""",
"""function positions(which){var arr=DASH[which].positions||[];var LIM=3;var p=arr.map(function(x,i){var cls=x.pnl[0]==='-'?'dn':'up';return '<tr'+(i>=LIM?' class="dash-extra"':'')+'><td><span class="strat-link" onclick="gotoStrat(\\''+x.n+'\\')">'+x.n+'</span></td><td class="muted">'+x.sym+'</td><td class="r tab">'+x.qty+'</td><td class="r tab">'+x.mark+'</td><td class="r tab '+cls+'">'+x.pnl+' '+x.pct+'</td></tr>';}).join('');
 var sa=arr.length>LIM?'<button class="seeall-btn" onclick="dashSeeAll(this)">See all \\u2192</button>':'';
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Open positions</span>'+sa+'</div><div class="card-body"><table class="mini-tbl"><thead><tr><th>Strategy</th><th>Pair</th><th class="r">Size</th><th class="r">Value</th><th class="r">P&L</th></tr></thead><tbody>'+p+'</tbody></table></div></div>';}""")

# ── column picker closes when a panel opens ──────────────────────────────────────
repl("function openPanel(id){\n  selectedId=id;",
     "function openPanel(id){\n  selectedId=id;\n  var __cp=document.getElementById('col-picker-menu');if(__cp)__cp.classList.remove('open');")

# ── remove the zoom:1.1 hack + revert dependent calcs ────────────────────────────
repl("\n  zoom:1.1;", "")
repl("calc(100vh/1.1)", "100vh", n=3)
repl("window.innerWidth/1.1", "window.innerWidth")
repl("window.innerHeight/1.1", "window.innerHeight")

# ── costs chart: today-dot SVG circle -> HTML dot (no ellipse distortion) ─────────
repl('\'<circle cx="\'+lastx.toFixed(1)+\'" cy="\'+lasty.toFixed(1)+\'" r="3" fill="var(--iris)"/></svg>\';',
     "'</svg>';")
repl("return '<div class=\"cspark\">'+svg+labels+'</div>';",
     "return '<div class=\"cspark\">'+svg+labels+'<span class=\"cspark-dot\" style=\"left:'+lx(lastx)+';top:'+lasty.toFixed(0)+'px\"></span></div>';")

# ── CSS ───────────────────────────────────────────────────────────────────────────
CSS = """
/* ── v8: dashboard see-all, sheet-chart inset, cost dot ── */
.mini-tbl tr.dash-extra{display:none}
.card.dash-open .mini-tbl tr.dash-extra{display:table-row}
.card-hdr .seeall-btn{margin:0}
.sheet-eq{background:color-mix(in oklab,var(--surf3) 50%,transparent);border:1px solid var(--hairline);border-radius:var(--r-sm)}
.cspark-dot{position:absolute;width:7px;height:7px;border-radius:50%;background:var(--iris);transform:translate(-50%,-50%);pointer-events:none;box-shadow:0 0 0 2px var(--surf2)}
@media (max-width:680px){
  :root{--sidebar-w:54px}
  .sb-text,.sb-name,.nav-count{display:none}
  .nav-item{justify-content:center;padding-left:0;padding-right:0}
  .sb-tog{display:none}
  .side-panel{max-width:94vw}
  .summary-ribbon{flex-wrap:wrap;height:auto;row-gap:6px}
}
"""
repl("\n</style>", CSS + "\n</style>")

pathlib.Path("mockups/cosmu-final-v8.html").write_text(html)
print("wrote mockups/cosmu-final-v8.html", len(html), "bytes")
