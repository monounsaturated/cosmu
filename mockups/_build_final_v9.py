#!/usr/bin/env python3
"""Final — base = cosmu-final-v8. Output: cosmu-final-v9.html
 - costs chart: now the same interactive curve as the dashboards (area+gridlines+hover), placed
   ABOVE the stat boxes, and the "+ Add cost" button removed from the chart card
 - See-all bug: opening one drawer no longer stretches/opens the sibling card (align-items:start)
 - responsive: layout adapts as the window narrows (stack the dashboard split, then the grids,
   then the sidebar to icons); usable on a half-width window
 - sidebar order: Live · Strategies · Paper · Costs · Commands
"""
import pathlib

html = pathlib.Path("mockups/cosmu-final-v8.html").read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:55]!r}], found {c}"
    html = html.replace(old, new)

def cut(start, end_marker, new):
    global html
    a = html.index(start); b = html.index(end_marker, a)
    html = html[:a] + new + html[b:]

# ── curveInto: accept a tooltip formatter + 3 gridlines (match dashboards) ───────
repl("function curveInto(box,vals,labels,col){",
     "function curveInto(box,vals,labels,col,opts){\n  var fmtv=(opts&&opts.fmt)||function(i){var pc=vals[i]-100;return (pc>=0?'+':'')+pc.toFixed(1)+'%';};")
repl("var gy=(PT+(H-PT-PB)*0.5).toFixed(1),gln='<line x1=\"0\" y1=\"'+gy+'\" x2=\"'+W+'\" y2=\"'+gy+'\" stroke=\"var(--hairline)\" stroke-width=\"1\" vector-effect=\"non-scaling-stroke\"/>';",
     "var gln='';[0.25,0.5,0.75].forEach(function(g){var gy=(PT+(H-PT-PB)*g).toFixed(1);gln+='<line x1=\"0\" y1=\"'+gy+'\" x2=\"'+W+'\" y2=\"'+gy+'\" stroke=\"var(--hairline)\" stroke-width=\"1\" vector-effect=\"non-scaling-stroke\"/>';});")
repl("var pc=vals[idx]-100;xt.querySelector('.tv').textContent=(pc>=0?'+':'')+pc.toFixed(1)+'%';xt.querySelector('.td').textContent=labels[idx];});",
     "xt.querySelector('.tv').textContent=fmtv(idx);xt.querySelector('.td').textContent=labels[idx];});")

# ── costs: dashboard-style chart on top, no add-cost button ───────────────────────
repl("""function renderChart(){var t=totals();
  return statStrip()+'<div class="card" style="margin-bottom:var(--gap)">'+tline('Cumulative spend · '+fmt(t.life)+' to date, projecting '+fmt(t.projY)+' / yr')+
   '<div class="card-body">'+spark()+'</div></div>'+catCards(true)+renderSubsTable();
}""",
"""var COSTSERIES=null;
function costChartCard(){
  var rows=TXN.slice().sort(function(a,b){return a.d<b.d?-1:1;});
  var cum=0,vals=[0],labels=[fmtD(START)];
  rows.forEach(function(x){cum+=x.amt;vals.push(cum);labels.push(fmtD(x.d));});
  COSTSERIES={vals:vals,labels:labels};
  return '<div class="card dh" style="padding:14px 16px;margin-bottom:var(--gap)">'+
   '<div class="hero-top"><div><div class="hero-label">Total spend</div><div><span class="hero-val tab">'+fmt(cum)+'</span><span class="hero-delta tab" style="color:var(--quiet);font-weight:500">since '+fmtD(START)+', 2026 · '+fmt(totals().run)+'/mo run-rate</span></div></div></div>'+
   '<div class="eqwrap sheet-eq" id="cost-eq" style="height:150px"></div>'+
   '<div class="eq-axis"><span>'+labels[0]+'</span><span>'+labels[labels.length-1]+'</span></div></div>';
}
function drawCostCurve(){var box=document.getElementById('cost-eq');if(!box||!COSTSERIES)return;curveInto(box,COSTSERIES.vals,COSTSERIES.labels,'var(--iris)',{fmt:function(i){return '$'+Math.round(COSTSERIES.vals[i]).toLocaleString('en-US');}});}
function renderChart(){return costChartCard()+statStrip()+catCards(true)+renderSubsTable();}""")

repl("""function renderCosts(){var m=document.getElementById('costs-mount');if(!m)return;
  m.innerHTML = LAYOUT==='ledger'?renderLedger():LAYOUT==='chart'?renderChart():LAYOUT==='forecast'?renderForecast():LAYOUT==='cards'?renderCards():renderRegister();}""",
"""function renderCosts(){var m=document.getElementById('costs-mount');if(!m)return;
  m.innerHTML = LAYOUT==='ledger'?renderLedger():LAYOUT==='chart'?renderChart():LAYOUT==='forecast'?renderForecast():LAYOUT==='cards'?renderCards():renderRegister();
  if(document.getElementById('cost-eq'))drawCostCurve();}""")

# ── See-all bug: don't let the sibling card stretch (and stack on narrow) ─────────
repl("H+=grid('1fr 1fr',positions(which)+tradesBox(which));   // positions | trades — paper & live alike",
     "H+='<div class=\"kgrid dash-split\" style=\"grid-template-columns:1fr 1fr\">'+positions(which)+tradesBox(which)+'</div>';   // positions | trades")

# ── sidebar order: Live · Strategies · Paper · Costs · Commands ───────────────────
cut('    <button class="nav-item active" onclick="nav(\'strategies\')" id="nav-strategies">', '\n  </nav>',
"""    <button class="nav-item" onclick="nav('live')" id="nav-live">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 7.5h2.6l1.4-3 2.2 6 1.4-3h3.4"/></svg>
        Live
      </span>
      <span class="nav-count">1</span>
    </button>
    <button class="nav-item active" onclick="nav('strategies')" id="nav-strategies">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round"><circle cx="3.2" cy="4" r="1.1" fill="currentColor" stroke="none"/><line x1="6.2" y1="4" x2="13" y2="4"/><circle cx="3.2" cy="7.5" r="1.1" fill="currentColor" stroke="none"/><line x1="6.2" y1="7.5" x2="13" y2="7.5"/><circle cx="3.2" cy="11" r="1.1" fill="currentColor" stroke="none"/><line x1="6.2" y1="11" x2="13" y2="11"/></svg>
        Strategies
      </span>
      <span class="nav-count">12</span>
    </button>
    <button class="nav-item" onclick="nav('paper')" id="nav-paper">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="2.6" width="9" height="10.8" rx="1.6"/><rect x="5.4" y="1.5" width="4.2" height="2.3" rx="0.8"/><line x1="5.5" y1="7" x2="9.5" y2="7"/><line x1="5.5" y1="9.5" x2="9.5" y2="9.5"/></svg>
        Paper
      </span>
      <span class="nav-count">4</span>
    </button>
    <button class="nav-item" onclick="nav('costs')" id="nav-costs">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="3.5" width="12" height="8" rx="2"/><path d="M1.5 6.2h12"/><circle cx="10.4" cy="9" r="1" fill="currentColor" stroke="none"/></svg>
        Costs
      </span>
    </button>
    <button class="nav-item" onclick="nav('commands')" id="nav-commands">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2.6" width="12" height="9.8" rx="1.6"/><polyline points="4,6 6.4,8 4,10"/><line x1="8" y1="10" x2="11" y2="10"/></svg>
        Commands
      </span>
    </button>""")

# ── responsive: replace the single mobile query with a graceful multi-tier set ───
repl("""@media (max-width:680px){
  :root{--sidebar-w:54px}
  .sb-text,.sb-name,.nav-count{display:none}
  .nav-item{justify-content:center;padding-left:0;padding-right:0}
  .sb-tog{display:none}
  .side-panel{max-width:94vw}
  .summary-ribbon{flex-wrap:wrap;height:auto;row-gap:6px}
}""",
""".dash-split{align-items:start}
@media (max-width:1100px){ .dash-split{grid-template-columns:1fr!important} }
@media (max-width:820px){
  .kgrid,.kpi-grid,.cat-tiles,.money-band,.kpi-guard{grid-template-columns:repeat(2,1fr)!important}
  .dash-split{grid-template-columns:1fr!important}
}
@media (max-width:760px){
  :root{--sidebar-w:54px}
  .sb-text,.sb-name,.nav-count{display:none}
  .nav-item{justify-content:center;padding-left:0;padding-right:0}
  .sb-tog{display:none}
  .side-panel{max-width:94vw}
  .summary-ribbon{flex-wrap:wrap;height:auto;row-gap:6px}
}
@media (max-width:520px){
  .kgrid,.kpi-grid,.cat-tiles,.money-band,.stat-strip,.dash-split{grid-template-columns:1fr!important}
}""")

pathlib.Path("mockups/cosmu-final-v9.html").write_text(html)
print("wrote mockups/cosmu-final-v9.html", len(html), "bytes")
