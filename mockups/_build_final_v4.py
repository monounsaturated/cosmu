#!/usr/bin/env python3
"""Final consolidation — base = final-g1-row (the chosen design). Applies the last batch:
 1. strat sheet: remove the ★ next to the Live column header (both panels)
 2. strat sheet: show an equity chart even for non-live strategies (phase-appropriate; honest
    empty-state for strategies still in backtest with no curve yet)
 3. strat table: remove the colored P&L highlight cell (plain, black background)
 4. strat table: extend the existing Columns picker with relevant optional columns
    (Drift / Fees / Origin), off by default — defaults unchanged
 5. paper dashboard: 'Pause all' -> neutral 'Stop' button (not red) + honest paper-stop modal
 6. costs: category tiles no longer alert() — they filter the register below, in place
 7. navigation: strategy names in live/paper positions & trades link to their strat sheet
Outputs mockups/cosmu-final-v3.html
"""
import pathlib

SRC = pathlib.Path("mockups/final-g1-row.html")
html = SRC.read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:55]!r}], found {c}"
    html = html.replace(old, new)

# ── 1. remove the ★ next to Live (phase comparison headers, both panels) ──────────
repl("col-live\">Live ★</th>", "col-live\">Live</th>", n=2)

# ── 3. strat table: drop the P&L colour-highlight cell ───────────────────────────
repl(
"""function pnlHeat(s,val,pct,num){
  if(!val||val==='—') return '<span class="quiet">—</span>';
  const isUp=num>0,isDn=num<0;
  const bg=isUp?`oklch(0.78 0.16 160 / ${Math.min(num/30*0.18,0.18)})`:`oklch(0.70 0.17 18 / ${Math.min(Math.abs(num)/30*0.18,0.18)})`;
  const cl=isUp?'up':isDn?'dn':'';
  return `<div class="pnl-wrap"><div class="pnl-bg" style="background:${bg}"></div><div class="pnl-val ${cl} tab">${val}</div><div class="pnl-pct tab">${pct}</div></div>`;
}""",
"""function pnlHeat(s,val,pct,num){
  if(!val||val==='—') return '<span class="quiet">—</span>';
  const cl=num>0?'up':num<0?'dn':'';
  return `<div class="pnl-wrap"><div class="pnl-val ${cl} tab">${val}</div><div class="pnl-pct tab">${pct}</div></div>`;
}""")

# ── 4. extra optional columns: data + helpers (inserted after selectedId) ─────────
repl("let selectedId=null;",
"""let selectedId=null;

// optional-column data (maps to LeaderboardRow fields: divergence_status, Σ executions.fee, origin)
const STRAT_META={
 'funding-carry-btc':{drift:'tracking',origin:'evolved'},
 'xsect-momentum-top5':{drift:'tracking',origin:'seed'},
 'gtaa-monthly':{drift:'tracking',origin:'seed'},
 'fg-contrarian-eth':{drift:'diverging',origin:'chat'},
 'stablecoin-lead-eth':{drift:'building',origin:'chat'},
 'vol-regime-btc':{drift:'—',origin:'seed'},
 'orb-sol-4h':{drift:'—',origin:'chat'},
 'wiki-zscore-btc':{drift:'—',origin:'chat'},
 'reddit-spike-doge':{drift:'—',origin:'chat'},
 'pm-riskon-overlay':{drift:'—',origin:'chat'},
 'fvg-btc-1h':{drift:'—',origin:'seed'},
 'ma-trend-eth-1d':{drift:'—',origin:'seed'},
};
function sMeta(id){return STRAT_META[id]||{drift:'—',origin:'—'};}
function feesOf(s){return s.stage==='live'?'$3.12':s.stage==='paper'?'$'+(0.4+s.days*0.05).toFixed(2):'<span class="quiet">—</span>';}
function driftCell(d){if(d==='tracking')return '<span class="up" style="font-size:10.5px">● tracking</span>';if(d==='diverging')return '<span class="gold" style="font-size:10.5px">● diverging</span>';if(d==='building')return '<span class="quiet" style="font-size:10.5px">● building</span>';return '<span class="quiet">—</span>';}""")

# colgroup (+3 cols)
repl('<col class="col-venue col-hidden col-venue-h">',
     '<col class="col-venue col-hidden col-venue-h"><col class="col-drift col-hidden col-drift-h"><col class="col-fees col-hidden col-fees-h"><col class="col-origin col-hidden col-origin-h">')
# thead (+3 th)
repl('<th class="col-venue-h col-hidden"><div class="th-inner">Venue</div></th>',
     '<th class="col-venue-h col-hidden"><div class="th-inner">Venue</div></th>'
     '<th class="col-drift-h col-hidden"><div class="th-inner">Drift</div></th>'
     '<th class="col-fees-h col-hidden"><div class="th-inner">Fees</div></th>'
     '<th class="col-origin-h col-hidden"><div class="th-inner">Origin</div></th>')
# tbody (+3 td)
repl('<td class="col-venue-h col-hidden"><span class="muted" style="font-size:11px">${s.venue}</span></td>',
     '<td class="col-venue-h col-hidden"><span class="muted" style="font-size:11px">${s.venue}</span></td>'
     '<td class="col-drift-h col-hidden">${driftCell(sMeta(s.id).drift)}</td>'
     '<td class="col-fees-h col-hidden"><span class="muted tab" style="font-size:11px">${feesOf(s)}</span></td>'
     '<td class="col-origin-h col-hidden"><span class="muted" style="font-size:10.5px;text-transform:capitalize">${sMeta(s.id).origin}</span></td>')
# picker (+3 items)
repl('<div class="col-picker-item"><input type="checkbox" id="col-days" checked onchange="toggleCol(\'col-days\',this)"><label for="col-days">Days</label></div>',
     '<div class="col-picker-item"><input type="checkbox" id="col-days" checked onchange="toggleCol(\'col-days\',this)"><label for="col-days">Days</label></div>\n'
     '          <div class="col-picker-divider"></div>\n'
     '          <div class="col-picker-item"><input type="checkbox" id="col-drift" onchange="toggleCol(\'col-drift\',this)"><label for="col-drift">Drift</label></div>\n'
     '          <div class="col-picker-item"><input type="checkbox" id="col-fees" onchange="toggleCol(\'col-fees\',this)"><label for="col-fees">Fees paid</label></div>\n'
     '          <div class="col-picker-item"><input type="checkbox" id="col-origin" onchange="toggleCol(\'col-origin\',this)"><label for="col-origin">Origin</label></div>')

# ── 2. strat sheet: chart even for non-live (sheetChart + inject into templatePanel) ─
repl("function templatePanel(s){",
"""function sheetChart(s){
  const known=(s.pnlNum&&s.pnlNum!==0)||(s.oos&&s.oos!=='—'&&s.oos!=='');
  const stage=s.stage;
  const lab=stage==='live'?'Live':(stage==='paper'||stage==='paper-ready')?'Paper':stage==='killed'?'Backtest (killed)':'Backtest';
  if(!known) return '<div class="psec"><div class="psec-title">Equity</div><div class="eq-empty">No equity curve yet — this strategy is still in backtest.</div></div>';
  const col=stage==='live'?'oklch(0.78 0.16 160)':(stage==='paper'||stage==='paper-ready')?'oklch(0.66 0.19 290)':'oklch(0.62 0.05 286)';
  let ret=s.pnlNum||0; if(!ret){const o=parseFloat((s.oos||'').replace(/[^-0-9.]/g,''));ret=isNaN(o)?2:o;}
  const N=40,W=560,H=90,PT=10,PB=14,start=100,end=100*(1+ret/100);
  const pts=[]; let lo=1e9,hi=-1e9;
  for(let i=0;i<N;i++){const f=i/(N-1);const w=Math.sin(i*0.7)*Math.abs(end-start)*0.12+Math.sin(i*0.27+1)*Math.abs(end-start)*0.07;const v=start+(end-start)*f+w;pts.push(v);if(v<lo)lo=v;if(v>hi)hi=v;}
  pts[0]=start;pts[N-1]=end;
  let rng=(hi-lo)||1; lo-=rng*0.2; hi+=rng*0.2; const R=hi-lo;
  const X=i=>(i/(N-1))*W, Y=v=>PT+(H-PT-PB)*(1-(v-lo)/R);
  const line=pts.map((v,i)=>X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ');
  const area='M0,'+Y(pts[0]).toFixed(1)+' L'+line.split(' ').join(' L')+' L'+W+','+H+' L0,'+H+'Z';
  const gid='sc-'+s.id, cap=(s.days?s.days+'d':'OOS')+' · '+(s.pnlPct||s.oos||'—')+' · '+lab;
  return '<div class="psec"><div class="psec-title">Equity — '+lab+'</div><div class="eq-wrap"><svg viewBox="0 0 '+W+' '+H+'" width="100%" height="90" preserveAspectRatio="none">'+
    '<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+col+'" stop-opacity=".20"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+
    '<path d="'+area+'" fill="url(#'+gid+')"/><polyline points="'+line+'" fill="none" stroke="'+col+'" stroke-width="1.6" vector-effect="non-scaling-stroke"/>'+
    '<text x="4" y="11" font-size="8" fill="oklch(0.48 0.010 286)">'+cap+'</text></svg></div></div>';
}
function templatePanel(s){""")

repl("""</div>`:''}
<div class="psec">
  <div class="psec-title">Phase comparison</div>""",
"""</div>`:''}
${sheetChart(s)}
<div class="psec">
  <div class="psec-title">Phase comparison</div>""")

# ── 5. paper 'Pause all' -> neutral 'Stop' (base .btn is the neutral bordered style) ─
repl('<button class="btn btn-ghost btn-sm" style="margin-left:auto">⏸ Pause all</button>',
     '<button class="btn btn-sm" style="margin-left:auto" onclick="openPaperStop()">Stop</button>')

# paper-stop modal (neutral) — inserted before the live liquidate overlay
repl('<div class="overlay" id="liq-overlay">',
"""<div class="overlay" id="pstop-overlay">
  <div class="modal">
    <div class="modal-title">Stop all paper tracks</div>
    <div class="modal-body">Halt every running paper track and close their simulated positions. <strong>No real money is involved</strong> — this only stops the simulations and frees their virtual capital. Each track <strong>keeps its stats</strong> so you can still review what happened. Live trading is not affected.</div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closePaperStop()">Cancel</button>
      <button class="btn btn-iris" onclick="closePaperStop()">Stop paper tracks</button>
    </div>
  </div>
</div>
<div class="overlay" id="liq-overlay">""")

repl("function openLiquidate(){document.getElementById('liq-overlay').classList.add('open')}",
     "function openLiquidate(){document.getElementById('liq-overlay').classList.add('open')}\n"
     "function openPaperStop(){document.getElementById('pstop-overlay').classList.add('open')}\n"
     "function closePaperStop(){document.getElementById('pstop-overlay').classList.remove('open')}\n"
     "document.getElementById('pstop-overlay').addEventListener('click',e=>{if(e.target===document.getElementById('pstop-overlay'))closePaperStop()});")

# ── 6. costs: category tiles filter the register in place (no navigation) ─────────
repl("function catCards(noStrip){var cats=['infra','trading','data','ai'];var h='<div class=\"cat-tiles\">';",
     "var costCat=null;\nfunction costPick(c){costCat=(costCat===c?null:c);renderCosts();}\nfunction catCards(noStrip){var cats=['infra','trading','data','ai'];var h='<div class=\"cat-tiles\">';")
repl("h+='<div class=\"cat-tile\" onclick=\"alert(\\''+CAT[c][0]+' — see register\\')\">",
     "h+='<div class=\"cat-tile'+(costCat===c?' active':'')+'\" onclick=\"costPick(\\''+c+'\\')\" title=\"Filter the register below by '+CAT[c][0]+'\">")
repl("var body='';SUBS.forEach(function(s){var last=lastPaid(s.id);",
     "var body='';SUBS.forEach(function(s){if(costCat&&s.cat!==costCat)return;var last=lastPaid(s.id);")
repl("  // usage row\n  body+='<tr><td>Trading fees + funding</td>",
     "  // usage row\n  if(!costCat||costCat==='trading')body+='<tr><td>Trading fees + funding</td>")
repl("function renderSubsTable(){return '<div class=\"card\">'+tline('Subscriptions &amp; renewals')+'<div class=\"card-body\">'+registerTbl()+'</div></div>';}",
     "function renderSubsTable(){return '<div class=\"card\">'+tline('Subscriptions &amp; renewals'+(costCat?' · '+CAT[costCat][0]+' only — click the tile again to clear':''))+'<div class=\"card-body\">'+registerTbl()+'</div></div>';}")

# ── 7. backlinks: strategy names in dashboards open their strat sheet ─────────────
repl("function tradesBox(which){var tr=DASH[which].trades;",
"""var STRAT_ID={'Funding Carry BTC':'funding-carry-btc','Cross-Sect Momentum':'xsect-momentum-top5','GTAA Monthly':'gtaa-monthly','Stablecoin Flows ETH':'stablecoin-lead-eth','Fear & Greed ETH':'fg-contrarian-eth'};
function gotoStrat(name){var id=STRAT_ID[name];nav('strategies');if(id)openPanel(id);}
function tradesBox(which){var tr=DASH[which].trades;""")
repl("<td>'+x[2]+'</td><td class=\"side-'",
     "<td><span class=\"strat-link\" onclick=\"gotoStrat(\\''+x[2]+'\\')\">'+x[2]+'</span></td><td class=\"side-'")
repl("'<tr><td>'+x.n+'</td><td class=\"muted\">'+x.sym+'</td>",
     "'<tr><td><span class=\"strat-link\" onclick=\"gotoStrat(\\''+x.n+'\\')\">'+x.n+'</span></td><td class=\"muted\">'+x.sym+'</td>")

# ── CSS additions ────────────────────────────────────────────────────────────────
CSS = """
/* ── final-v3: filter tiles, backlinks, sheet empty-state, picker divider ── */
.cat-tile.active{border-color:var(--iris);box-shadow:inset 0 0 0 1px var(--iris-mid),var(--cell-shadow)}
.strat-link{cursor:pointer;border-bottom:1px dashed transparent;transition:color var(--tr)}
.strat-link:hover{color:var(--iris-s);border-bottom-color:var(--iris-mid)}
.eq-empty{padding:22px 12px;text-align:center;color:var(--quiet);font-size:11px;background:var(--surf);border:1px dashed var(--border);border-radius:var(--r-sm)}
.col-picker-divider{height:1px;background:var(--hairline);margin:5px 2px}
"""
repl("\n</style>", CSS + "\n</style>")

OUT = pathlib.Path("mockups/cosmu-final-v3.html")
OUT.write_text(html)
print("wrote", OUT, len(html), "bytes")
