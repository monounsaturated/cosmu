#!/usr/bin/env python3
"""v12 (final) — base = cosmu-final-v11. Output: cosmu-final-v12.html
 1. $ on dollar values: P&L/deltas were stripping the '$' (dfmt(...).slice(1)) -> show +$419
 2. OOS shown with its window (e.g. +8.2% · 2.4yr) on the strat table + sheet phase comparison
 3. strat-sheet Recent trades: add the time next to the date (like the dashboards)
 4. Costs chart = the dashboard equity chart: timeframe segmented control (7D/30D/All), same
    size + hover + headline scrub
"""
import re, pathlib

h = pathlib.Path("mockups/cosmu-final-v11.html").read_text()

def repl(old, new, n=1):
    global h
    c = h.count(old); assert c == n, f"{n}!={c} for {old[:50]!r}"; h = h.replace(old, new)

# ── 1. $ on dollar values ────────────────────────────────────────────────────────
repl("dfmt(d.pnl).slice(1)", "dfmt(d.pnl)", n=3)               # KPI/sheet P&L -> +$419
repl("dfmt(Math.abs(d)).slice(1)", "'$'+dfmt(Math.abs(d)).slice(1)", n=1)  # headline delta -> +$1,392

# ── 2. OOS window (data map + table cell + phase Duration row + gate-chip tip) ────
repl("function sMeta(id){return STRAT_META[id]||{drift:'—',origin:'—'};}",
"""function sMeta(id){return STRAT_META[id]||{drift:'—',origin:'—'};}
var OOSWIN={'funding-carry-btc':'2.4yr','xsect-momentum-top5':'18mo','gtaa-monthly':'3.1yr','fg-contrarian-eth':'14mo','stablecoin-lead-eth':'16mo','vol-regime-btc':'2.1yr','orb-sol-4h':'11mo','wiki-zscore-btc':'9mo'};
function oosWinOf(id){return OOSWIN[id]||'';}""")
repl("case 'oos': return (s.oos&&s.oos!=='—')?'<span class=\"tab '+(s.oos.charAt(0)==='+'?'up':'dn')+'\">'+s.oos+'</span>':'<span class=\"quiet\">—</span>';",
     "case 'oos': return (s.oos&&s.oos!=='—')?'<span class=\"tab '+(s.oos.charAt(0)==='+'?'up':'dn')+'\">'+s.oos+'</span>'+(oosWinOf(s.id)?'<span class=\"oos-win\">'+oosWinOf(s.id)+'</span>':''):'<span class=\"quiet\">—</span>';")
# funding panel phase-comparison Duration (Backtest column) — show the real OOS window
repl('<td class="quiet" style="font-size:10.5px">OOS window</td>',
     '<td class="quiet" style="font-size:10.5px">OOS · 2.4yr</td>')
# template panel phase-comparison Duration
repl('<tr><td>Duration</td><td class="quiet" style="font-size:10px">OOS</td>',
     '<tr><td>Duration</td><td class="quiet" style="font-size:10px">${oosWinOf(s.id)?\'OOS · \'+oosWinOf(s.id):\'OOS\'}</td>')

# ── 3. strat-sheet Recent trades: add the time next to the date ──────────────────
# funding panel trades table is static HTML — change header + append a deterministic time per row
ts = h.index('<table class="mini-tbl">', h.index('id="sheet-trades"'))
te = h.index('</table>', ts)
block = h[ts:te]
block = block.replace('<thead><tr><th>Date</th>', '<thead><tr><th>Date · time</th>', 1)
_times = ['14:22','09:11','17:46','08:03','21:30','11:55','13:07','22:10','10:18','15:41','19:02','07:33']
_i = [0]
def _addtime(m):
    t = _times[_i[0] % len(_times)]; _i[0] += 1
    return '<td>' + m.group(1) + ' <span style="color:var(--quiet)">' + t + '</span></td>'
block = re.sub(r'<td>([A-Z][a-z]{2} \d{2})</td>', _addtime, block)
h = h[:ts] + block + h[te:]

# ── 4. Costs chart = dashboard equity chart with timeframe ───────────────────────
# curveInto: allow an external headline-scrub callback
repl(" svg.addEventListener('mouseleave',function(){box.classList.remove('on');});",
     " svg.addEventListener('mouseleave',function(){box.classList.remove('on');if(opts&&opts.onScrub)opts.onScrub(-1);});")
repl("xt.querySelector('.td').textContent=labels[idx];});",
     "xt.querySelector('.td').textContent=labels[idx];if(opts&&opts.onScrub)opts.onScrub(idx);});")
# replace costChartCard + drawCostCurve with a daily series + timeframe + scrub
old_cc = h[h.index("function costChartCard(){"):h.index("function renderChart(){")]
new_cc = """var COST_DAILY=null;
function buildCostDaily(){var rows=TXN.slice().sort(function(a,b){return a.d<b.d?-1:1;});var s=D(START),e=D(TODAY);var ndays=Math.round((e-s)/86400000);var dates=[],cum=[],c=0,ri=0;for(var i=0;i<=ndays;i++){var day=new Date(s);day.setDate(s.getDate()+i);var iso=day.getFullYear()+'-'+String(day.getMonth()+1).padStart(2,'0')+'-'+String(day.getDate()).padStart(2,'0');while(ri<rows.length&&rows[ri].d<=iso){c+=rows[ri].amt;ri++;}dates.push(day);cum.push(c);}COST_DAILY={dates:dates,cum:cum,life:c};}
function costTF(t){var L=COST_DAILY.cum.length;var n=t==='7D'?7:t==='30D'?30:L;var k=Math.max(0,L-n);return {v:COST_DAILY.cum.slice(k),d:COST_DAILY.dates.slice(k)};}
function costChartCard(){buildCostDaily();
  return '<div class="card dh" style="padding:14px 16px;margin-bottom:var(--gap)">'+
   '<div class="hero-top"><div><div class="hero-label">Total spend</div><div><span class="hero-val tab" id="cost-hd">'+fmt(COST_DAILY.life)+'</span><span class="hero-delta tab" id="cost-dl" style="color:var(--quiet);font-weight:500">since '+fmtD(START)+', 2026</span></div></div>'+
   '<div class="tf-seg">'+['7D','30D','All'].map(function(x){return '<button'+(x==='30D'?' class="on"':'')+' onclick="setCostTF(\\''+x+'\\',this)">'+x+'</button>';}).join('')+'</div></div>'+
   '<div class="eqwrap sheet-eq" id="cost-eq" style="height:150px"></div>'+
   '<div class="eq-axis"><span id="cost-ax0"></span><span id="cost-ax1"></span></div></div>';
}
function setCostTF(t,btn){Array.prototype.forEach.call(btn.parentNode.children,function(b){b.classList.toggle('on',b===btn);});drawCostCurve(t);}
function drawCostCurve(t){var box=document.getElementById('cost-eq');if(!box)return;if(!COST_DAILY)buildCostDaily();t=t||'30D';var dat=costTF(t);
  var labels=dat.d.map(function(d){return d.toLocaleDateString('en-US',{month:'short',day:'numeric'});});
  curveInto(box,dat.v,labels,'var(--iris)',{fmt:function(i){return '$'+Math.round(dat.v[i]).toLocaleString('en-US');},onScrub:function(i){var hd=document.getElementById('cost-hd'),dl=document.getElementById('cost-dl');if(!hd)return;if(i<0){hd.textContent=fmt(COST_DAILY.life);if(dl){dl.textContent='since '+fmtD(START)+', 2026';dl.style.color='var(--quiet)';}}else{hd.textContent='$'+Math.round(dat.v[i]).toLocaleString('en-US');if(dl){dl.textContent=labels[i];dl.style.color='var(--quiet)';}}}});
  var a0=document.getElementById('cost-ax0'),a1=document.getElementById('cost-ax1');if(a0)a0.textContent=labels[0];if(a1)a1.textContent=labels[labels.length-1];
}
"""
h = h.replace(old_cc, new_cc, 1)
repl("  if(document.getElementById('cost-eq'))drawCostCurve();}",
     "  if(document.getElementById('cost-eq'))drawCostCurve('30D');}")

# ── CSS for the OOS window sub ───────────────────────────────────────────────────
repl("\n</style>", "\n.oos-win{display:block;font-size:9px;color:var(--quiet);line-height:1.1;margin-top:1px;font-variant-numeric:tabular-nums}\n</style>")

pathlib.Path("mockups/cosmu-final-v12.html").write_text(h)
print("wrote mockups/cosmu-final-v12.html", len(h), "bytes")
