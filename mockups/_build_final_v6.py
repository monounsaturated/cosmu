#!/usr/bin/env python3
"""Final detail pass — base = cosmu-final-v4b (chosen). Emits 3 versions that differ ONLY in
the Columns picker interaction style (cp1 checkbox+highlight · cp2 filled pill · cp3 switch).
Everything else is identical and applies these fixes:
 - sidebar: selected-page highlight inset from the edge (rounded, not touching)
 - chart hover: positioned with % (zoom-safe) — fixes the off-by-zoom crosshair
 - tables: horizontal scroll when cropped/zoomed; fixes the broken table on column toggle
 - Columns picker: click the whole row to toggle (not just the box), clear selected state
 - removed the Drift column (low signal/unclear)
 - strat sheet: paper/backtest strategies get the full phased chart like live, with phases the
   strategy never reached greyed out/disabled (e.g. killed-at-backtest → paper & live greyed)
 - strat sheet: added a local AI summary (Claude Code, no API fees)
 - strat sheet: live top row made as thin as the paper one (smaller buttons)
 - costs chart: redesigned — natural cumulative curve + modest projection (no weird extension)
 - sidebar status: just a small static dot (not a button, no blink)
 - strat table: dropped the kill-reason / 'in backtesting' subtext (clean stacked names)
"""
import pathlib

html = pathlib.Path("mockups/cosmu-final-v4b.html").read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:60]!r}], found {c}"
    html = html.replace(old, new)

# ── 1. sidebar nav highlight inset ───────────────────────────────────────────────
repl(".sb-nav{flex:1;overflow-y:auto;padding:7px 7px 0}",
     ".sb-nav{flex:1;overflow-y:auto;padding:7px 7px 0;display:flex;flex-direction:column}")
repl("user-select:none;border:1px solid transparent;background:transparent;width:100%;text-align:left;",
     "user-select:none;border:1px solid transparent;background:transparent;text-align:left;")

# ── 2. tables: horizontal scroll + fix broken-on-toggle ──────────────────────────
repl(".screener-wrap{\n  border-radius:var(--r);overflow:hidden;\n  box-shadow:var(--cell-shadow);\n}",
     ".screener-wrap{\n  border-radius:var(--r);overflow-x:auto;overflow-y:hidden;\n  box-shadow:var(--cell-shadow);\n}")

# ── 3. remove Drift column (colgroup / thead / tbody) ────────────────────────────
repl('<col class="col-venue col-hidden col-venue-h"><col class="col-drift col-hidden col-drift-h"><col class="col-fees col-hidden col-fees-h"><col class="col-origin col-hidden col-origin-h">',
     '<col class="col-venue col-hidden col-venue-h"><col class="col-fees col-hidden col-fees-h"><col class="col-origin col-hidden col-origin-h">')
repl('<th class="col-venue-h col-hidden"><div class="th-inner">Venue</div></th><th class="col-drift-h col-hidden"><div class="th-inner">Drift</div></th><th class="col-fees-h col-hidden"><div class="th-inner">Fees</div></th><th class="col-origin-h col-hidden"><div class="th-inner">Origin</div></th>',
     '<th class="col-venue-h col-hidden"><div class="th-inner">Venue</div></th><th class="col-fees-h col-hidden"><div class="th-inner">Fees</div></th><th class="col-origin-h col-hidden"><div class="th-inner">Origin</div></th>')
repl('<td class="col-venue-h col-hidden"><span class="muted" style="font-size:11px">${s.venue}</span></td><td class="col-drift-h col-hidden">${driftCell(sMeta(s.id).drift)}</td><td class="col-fees-h col-hidden">',
     '<td class="col-venue-h col-hidden"><span class="muted" style="font-size:11px">${s.venue}</span></td><td class="col-fees-h col-hidden">')

# ── 4. strat table: drop the kill-reason / in-backtesting subtext ─────────────────
repl("""    const subExtra=s.killReason
      ?`<span style="color:var(--down);font-size:9.5px">killed: ${s.killReason}</span>`
      :s.stage==='backtest'?'<span class="quiet" style="font-size:9.5px">in backtesting</span>':'';
""", "")
repl('<td><div class="cell-name">${s.name}</div><div class="cell-sub">${subExtra}</div></td>',
     '<td><div class="cell-name">${s.name}</div></td>')

# ── 5. Columns picker: whole-row click + clear state (replace menu + add pickCol/fitTable) ─
OLD_MENU = """        <div class="col-picker-menu" id="col-picker-menu">
          <div class="col-picker-item"><input type="checkbox" id="col-dsr" checked onchange="toggleCol('col-dsr',this)"><label for="col-dsr">DSR</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-pbo" checked onchange="toggleCol('col-pbo',this)"><label for="col-pbo">PBO</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-dd" checked onchange="toggleCol('col-dd',this)"><label for="col-dd">Max DD</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-oos" checked onchange="toggleCol('col-oos',this)"><label for="col-oos">OOS</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-venue" onchange="toggleCol('col-venue',this)"><label for="col-venue">Venue</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-days" checked onchange="toggleCol('col-days',this)"><label for="col-days">Days</label></div>
          <div class="col-picker-divider"></div>
          <div class="col-picker-item"><input type="checkbox" id="col-drift" onchange="toggleCol('col-drift',this)"><label for="col-drift">Drift</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-fees" onchange="toggleCol('col-fees',this)"><label for="col-fees">Fees paid</label></div>
          <div class="col-picker-item"><input type="checkbox" id="col-origin" onchange="toggleCol('col-origin',this)"><label for="col-origin">Origin</label></div>
        </div>"""
NEW_MENU = """        <div class="col-picker-menu __CPCLASS__" id="col-picker-menu">
          <div class="cp-head">Show columns <span class="cp-hint">click a row</span></div>
          <div class="col-picker-item on" data-col="col-dsr" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">DSR</span></div>
          <div class="col-picker-item on" data-col="col-pbo" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">PBO</span></div>
          <div class="col-picker-item on" data-col="col-dd" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">Max DD</span></div>
          <div class="col-picker-item on" data-col="col-oos" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">OOS</span></div>
          <div class="col-picker-item on" data-col="col-days" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">Days</span></div>
          <div class="col-picker-divider"></div>
          <div class="col-picker-item" data-col="col-venue" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">Venue</span></div>
          <div class="col-picker-item" data-col="col-fees" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">Fees paid</span></div>
          <div class="col-picker-item" data-col="col-origin" onclick="pickCol(this)"><span class="cp-ind"></span><span class="cp-label">Origin</span></div>
        </div>"""
repl(OLD_MENU, NEW_MENU)

repl("function toggleCol(cls,cb){",
"""var COLW={'col-name':215,'col-stage':92,'col-life':104,'col-days':52,'col-val':84,'col-pnl':110,'col-dsr':94,'col-pbo':68,'col-dd':84,'col-oos':68,'col-venue':72,'col-fees':74,'col-origin':82};
function fitTable(){var t=document.getElementById('screener');if(!t)return;var sum=0;Array.prototype.forEach.call(t.querySelectorAll('colgroup col'),function(c){if(c.classList.contains('col-hidden'))return;var w=0;c.classList.forEach(function(x){if(COLW[x])w=COLW[x];});sum+=w||80;});t.style.minWidth=sum+'px';}
function pickCol(row){var on=row.classList.toggle('on');var cls=row.dataset.col;document.querySelectorAll('.'+cls+'-h').forEach(function(el){el.classList.toggle('col-hidden',!on);});fitTable();}
function toggleCol(cls,cb){""")
repl("  }).join('');\n}\nrenderScreener();", "  }).join('');\n  fitTable();\n}\nrenderScreener();")

# ── 6. chart hover: percentage positioning (zoom-safe) ───────────────────────────
repl(""" svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect();var ratio=(ev.clientX-r.left)/r.width;var idx=Math.max(0,Math.min(n-1,Math.round(ratio*(n-1))));var px=idx/(n-1)*r.width,py=Y(v[idx])/H*r.height;box.classList.add('on');xl.style.left=px+'px';xd.style.left=px+'px';xd.style.top=py+'px';var tx=Math.max(48,Math.min(px,r.width-48)),above=py>52;xt.style.left=tx+'px';xt.style.top=(py+(above?-10:14))+'px';xt.style.transform='translate(-50%,'+(above?'-100%':'0')+')';xt.querySelector('.tv').textContent=dfmt(v[idx]);xt.querySelector('.td').textContent=dfmtDate(ds[idx],dat.intra);setHead(which,v[idx]);});""",
""" svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect();var ratio=Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width));var idx=Math.max(0,Math.min(n-1,Math.round(ratio*(n-1))));var xp=(n>1?idx/(n-1):0)*100,yp=Y(v[idx])/H*100;box.classList.add('on');xl.style.left=xp+'%';xd.style.left=xp+'%';xd.style.top=yp+'%';var tx=Math.max(6,Math.min(xp,94)),above=yp>30;xt.style.left=tx+'%';xt.style.top='calc('+yp+'% '+(above?'- 10px':'+ 14px')+')';xt.style.transform='translate(-50%,'+(above?'-100%':'0')+')';xt.querySelector('.tv').textContent=dfmt(v[idx]);xt.querySelector('.td').textContent=dfmtDate(ds[idx],dat.intra);setHead(which,v[idx]);});""")

# ── 7. strat sheet: phased chart for non-live + AI summary (replace sheetChart) ──
OLD_SHEETCHART = """function sheetChart(s){
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
}"""
NEW_SHEETCHART = r"""function phaseSvg(id,ret,col,caption,show){
  const N=44,W=560,H=90,PT=10,PB=14,start=100,end=100*(1+ret/100),seed=id.charCodeAt(0);
  const pts=[]; let lo=1e9,hi=-1e9;
  for(let i=0;i<N;i++){const f=i/(N-1);const w=Math.sin(i*0.6+seed)*Math.abs(end-start)*0.13+Math.sin(i*0.31+1)*Math.abs(end-start)*0.06;const v=start+(end-start)*f+w;pts.push(v);if(v<lo)lo=v;if(v>hi)hi=v;}
  pts[0]=start;pts[N-1]=end;
  let rng=(hi-lo)||1; lo-=rng*0.2; hi+=rng*0.2; const R=hi-lo;
  const X=i=>(i/(N-1))*W, Y=v=>PT+(H-PT-PB)*(1-(v-lo)/R);
  const line=pts.map((v,i)=>X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ');
  const area='M0,'+Y(pts[0]).toFixed(1)+' L'+line.split(' ').join(' L')+' L'+W+','+H+' L0,'+H+'Z';
  const gid='ph'+id+Math.round(Math.abs(ret)*10);
  return '<svg id="eq-'+id+'" viewBox="0 0 '+W+' '+H+'" width="100%" height="90" preserveAspectRatio="none" style="display:'+(show?'block':'none')+'">'+
    '<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+col+'" stop-opacity=".20"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+
    '<path d="'+area+'" fill="url(#'+gid+')"/><polyline points="'+line+'" fill="none" stroke="'+col+'" stroke-width="1.6" vector-effect="non-scaling-stroke"/>'+
    '<text x="4" y="11" font-size="8" fill="oklch(0.48 0.010 286)">'+caption+'</text></svg>';
}
function sheetChartPhases(s){
  const hasBt=s.oos&&s.oos!=='—'&&s.oos!=='';
  const reachedPa=['paper','paper-ready','live'].indexOf(s.stage)>=0;
  const reachedLi=s.stage==='live';
  if(!hasBt&&!reachedPa) return '<div class="psec"><div class="psec-title">Equity</div><div class="eq-empty">No equity curve yet — this strategy is still in the backtest queue.</div></div>';
  const o=parseFloat((s.oos||'').replace(/[^-0-9.]/g,'')), btRet=isNaN(o)?2:o;
  const paRet=reachedPa?(s.pnlNum||1):0, def=reachedLi?'li':reachedPa?'pa':'bt';
  function b(ph,lbl,enabled,tip){return enabled
    ?'<button class="'+(def===ph?'on':'')+'" data-title="Equity — '+lbl+'" onclick="setPhase(\''+ph+'\',this)">'+lbl+'</button>'
    :'<button class="ph-off" data-tip="'+tip+'">'+lbl+'</button>';}
  let svgs='';
  if(hasBt) svgs+=phaseSvg('bt',btRet,'oklch(0.62 0.05 286)',(s.killReason?'killed at backtest · ':'')+'OOS · '+(s.oos||'—'),def==='bt');
  if(reachedPa) svgs+=phaseSvg('pa',paRet,'oklch(0.66 0.19 290)',(s.days||0)+'d paper · '+(s.pnlPct||'—'),def==='pa');
  if(reachedLi) svgs+=phaseSvg('li',(s.pnlNum||1),'oklch(0.78 0.16 160)',(s.days||0)+'d live · '+(s.pnlPct||'—'),def==='li');
  const t0='Equity — '+(def==='li'?'Live':def==='pa'?'Paper':'Backtest');
  return '<div class="psec"><div class="eq-head"><span class="eq-title-txt" id="eq-title">'+t0+'</span><div class="phase-sel">'+
    b('bt','Backtest',hasBt,'No backtest data yet')+
    b('pa','Paper',reachedPa,'Never reached paper'+(s.killReason?' — killed at backtest':''))+
    b('li','Live',reachedLi,'Never went live'+(s.killReason?' — killed at backtest':''))+
    '</div></div><div class="eq-wrap">'+svgs+'</div></div>';
}
function aiSummary(s){
  var t;
  if(s.stage==='live'){t='Live '+s.days+' days, up '+s.pnlPct+' on $'+s.inv.toLocaleString('en-US')+' deployed — and tracking its paper read closely. The edge is funding-carry on BTC: it collects positive funding while delta-hedged. Drawdown ('+s.dd+'%) stays well inside the 25% cap and fees ($3.12) are immaterial next to P&L. Nothing anomalous — the live record matches the thesis.';}
  else if(s.stage==='paper'||s.stage==='paper-ready'){t=s.name+' has run '+s.days+' days in paper at '+s.pnlPct+'. '+(s.pnlNum>=0?'It is holding up versus its backtest ('+(s.oos||'—')+' OOS)':'It is lagging its backtest ('+(s.oos||'—')+' OOS) — watch for decay')+'. Gate read: DSR '+(s.dsr||'—')+', PBO '+(s.pbo||'—')+'. '+(s.stage==='paper-ready'?'Past the maturity bar — a launch candidate.':'Needs ≥30 net-positive days before it is launch-ready.');}
  else if(s.stage==='killed'){t=s.name+' was killed at backtest — reason: '+s.killReason+'. Out-of-sample read was '+(s.oos||'—')+' with PBO '+(s.pbo||'—')+'. It never reached paper or live, so there is no forward record. Kept visible so the same idea is not blindly re-tried.';}
  else if(s.stage==='backtest'){t=s.name+' is in backtest. '+(s.gateOk?'It has cleared the Gate (DSR '+(s.dsr||'—')+', PBO '+(s.pbo||'—')+', OOS '+(s.oos||'—')+') and is a candidate to promote to paper.':'It has not cleared the Gate yet — DSR '+(s.dsr||'—')+', PBO '+(s.pbo||'—')+'.');}
  else {t=s.name+' is queued for backtest. No results yet.';}
  return '<div class="psec ai-sec"><div class="ai-head"><span class="ai-title">AI summary</span><span class="ai-badge">Claude Code · local · no API fees</span></div><p class="ai-body">'+t+'</p></div>';
}"""
repl(OLD_SHEETCHART, NEW_SHEETCHART)
repl("${sheetChart(s)}", "${sheetChartPhases(s)}\n${aiSummary(s)}")

# setPhase: read the title from the clicked button (so each panel sets its own durations)
repl("""function setPhase(ph,btn){
  document.querySelectorAll('.phase-sel button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  ['bt','pa','li'].forEach(k=>{const el=document.getElementById('eq-'+k);if(el)el.style.display=k===ph?'block':'none'});
  const titles={bt:'Equity — Backtest <span style="color:var(--quiet);font-weight:400">(OOS)</span>',pa:'Equity — Paper <span style="color:var(--quiet);font-weight:400">(47d)</span>',li:'Equity — Live <span style="color:var(--quiet);font-weight:400">(current · 18d)</span>'};
  const ti=document.getElementById('eq-title');if(ti)ti.innerHTML=titles[ph];
}""",
"""function setPhase(ph,btn){
  if(btn.classList.contains('ph-off'))return;
  document.querySelectorAll('.phase-sel button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  ['bt','pa','li'].forEach(k=>{const el=document.getElementById('eq-'+k);if(el)el.style.display=k===ph?'block':'none'});
  const ti=document.getElementById('eq-title');if(ti&&btn.dataset.title)ti.innerHTML=btn.dataset.title;
}""")

# funding panel: phase buttons carry their titles + add AI summary
repl("""    <div class="phase-sel">
      <button onclick="setPhase('bt',this)">Backtest</button>
      <button onclick="setPhase('pa',this)">Paper</button>
      <button class="on" onclick="setPhase('li',this)">Live</button>
    </div>""",
"""    <div class="phase-sel">
      <button data-title='Equity — Backtest <span style="color:var(--quiet);font-weight:400">(OOS)</span>' onclick="setPhase('bt',this)">Backtest</button>
      <button data-title='Equity — Paper <span style="color:var(--quiet);font-weight:400">(47d)</span>' onclick="setPhase('pa',this)">Paper</button>
      <button class="on" data-title='Equity — Live <span style="color:var(--quiet);font-weight:400">(current · 18d)</span>' onclick="setPhase('li',this)">Live</button>
    </div>""")
repl("  <!-- PHASE COMPARISON TABLE per spec -->",
     "  ${aiSummary(strategies.find(x=>x.id==='funding-carry-btc'))}\n  <!-- PHASE COMPARISON TABLE per spec -->")

# ── 8. live sheet top row as thin as paper (smaller buttons + center) ────────────
repl(".panel-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}",
     ".panel-top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}")
repl('<div class="panel-actions"><button class="btn btn-danger btn-sm" onclick="openLiquidate()">Stop</button></div>',
     '<div class="panel-actions"><button class="btn btn-danger btn-xs" onclick="openLiquidate()">Stop</button></div>')
repl("'<div class=\"panel-actions\"><button class=\"btn btn-iris btn-sm\">Start paper</button></div>'",
     "'<div class=\"panel-actions\"><button class=\"btn btn-iris btn-xs\">Start paper</button></div>'")

# ── 9. costs chart redesign (replace spark) ──────────────────────────────────────
OLD_SPARK = """function spark(){
  var rows=TXN.slice().sort(function(a,b){return a.d<b.d?-1:1;});
  var W=660,H=120,PAD=6; var t0=D(START).getTime(),t1=D(TODAY).getTime();
  var maxLife=totals().life; var projEnd=maxLife+totals().run*6; var maxY=projEnd;
  var pts=[[0,0]],cum=0;
  rows.forEach(function(x){cum+=x.amt;var px=(D(x.d).getTime()-t0)/(t1-t0)*(W*0.6);pts.push([px,cum]);});
  pts.push([W*0.6,cum]);
  function X(x){return PAD+x;} function Y(y){return H-PAD-(y/maxY)*(H-PAD*2);}
  var poly=pts.map(function(p){return X(p[0]).toFixed(0)+','+Y(p[1]).toFixed(0);}).join(' ');
  var lastx=W*0.6,lasty=cum; var projx=W-PAD,projy=projEnd;
  var area='M'+X(0)+','+Y(0)+' L'+poly.split(' ').join(' L')+' L'+X(lastx)+','+(H-PAD)+' L'+X(0)+','+(H-PAD)+'Z';"""
NEW_SPARK = """function spark(){
  var rows=TXN.slice().sort(function(a,b){return a.d<b.d?-1:1;});
  var W=660,H=120,PL=8,PR=10,PT=18,PB=18,plotW=W-PL-PR,plotH=H-PT-PB;
  var t0=D(START).getTime(),t1=D(TODAY).getTime();
  var life=totals().life,run=totals().run,todayF=0.72,projVal=life+run*2,maxY=Math.max(projVal,life*1.18);
  function X(f){return PL+f*plotW;} function Y(v){return PT+plotH*(1-v/maxY);}
  var pts=[[0,0]],cum=0;
  rows.forEach(function(x){cum+=x.amt;var f=(D(x.d).getTime()-t0)/(t1-t0)*todayF;pts.push([f,cum]);});
  pts.push([todayF,cum]);
  var poly=pts.map(function(p){return X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1);}).join(' ');
  var lastx=X(todayF),lasty=Y(cum),projx=X(1),projy=Y(projVal);
  var area='M'+X(0).toFixed(1)+','+Y(0).toFixed(1)+' L'+poly.split(' ').join(' L')+' L'+lastx.toFixed(1)+','+(H-PB)+' L'+X(0).toFixed(1)+','+(H-PB)+'Z';"""
repl(OLD_SPARK, NEW_SPARK)
# fix the SVG body that references the old vars (X(lastx) etc.)
OLD_SPARK_SVG = """   '<line x1="'+X(lastx)+'" y1="'+Y(lasty)+'" x2="'+X(projx)+'" y2="'+Y(projy)+'" stroke="var(--quiet)" stroke-width="1.4" stroke-dasharray="4,3"/>'+
   '<circle cx="'+X(lastx)+'" cy="'+Y(lasty)+'" r="3" fill="var(--iris)"/>'+
   '<text x="'+X(0)+'" y="'+(H-1)+'" font-size="8" fill="var(--quiet)">Apr 1</text>'+
   '<text x="'+X(lastx)+'" y="14" font-size="8" fill="var(--iris-s)">today '+fmt(maxLife)+'</text>'+
   '<text x="'+X(projx)+'" y="'+Y(projy)+'" font-size="8" fill="var(--quiet)" text-anchor="end">proj.</text>'+"""
NEW_SPARK_SVG = """   '<line x1="'+lastx.toFixed(1)+'" y1="'+lasty.toFixed(1)+'" x2="'+projx.toFixed(1)+'" y2="'+projy.toFixed(1)+'" stroke="var(--quiet)" stroke-width="1.3" stroke-dasharray="4,3" vector-effect="non-scaling-stroke"/>'+
   '<circle cx="'+lastx.toFixed(1)+'" cy="'+lasty.toFixed(1)+'" r="3" fill="var(--iris)"/>'+
   '<text x="'+X(0).toFixed(1)+'" y="'+(H-5)+'" font-size="8" fill="var(--quiet)">Apr 1</text>'+
   '<text x="'+lastx.toFixed(1)+'" y="'+(lasty-9).toFixed(1)+'" font-size="8.5" fill="var(--iris-s)" text-anchor="middle">today '+fmt(life)+'</text>'+
   '<text x="'+(projx-1).toFixed(1)+'" y="'+(projy-5).toFixed(1)+'" font-size="8" fill="var(--quiet)" text-anchor="end">proj. '+fmt(projVal)+'</text>'+"""
repl(OLD_SPARK_SVG, NEW_SPARK_SVG)
repl("'<polyline points=\"'+poly+'\" fill=\"none\" stroke=\"var(--iris)\" stroke-width=\"1.8\"/>'+",
     "'<polyline points=\"'+poly+'\" fill=\"none\" stroke=\"var(--iris)\" stroke-width=\"1.8\" vector-effect=\"non-scaling-stroke\"/>'+")

# ── 10. sidebar status: just a small static dot (not a button, no blink) ─────────
repl('<button class="sb-power on" id="sb-power" onclick="togglePower()" data-tip="Engine On — executor ticked today 22:10 UTC, marks 38 min old."><span class="power-dot"></span><span class="power-lbl">On</span></button>',
     '<div class="sb-dot-wrap" data-tip="Engine On — executor ticked today 22:10 UTC, marks 38 min old."><span class="sb-dot"></span></div>')
repl("""if(location.hash)nav(location.hash.replace('#/',''));

// engine On/Off button (green On · red Off · amber Issue w/ error on hover)
var PWR=['on','warn','off'];
var PWR_I={on:{l:'On',t:'Engine On — executor ticked today 22:10 UTC, marks 38 min old.'},warn:{l:'Issue',t:'Heartbeat stale — last executor tick ~3h ago. Marks may be outdated; check the engine logs before trusting live numbers.'},off:{l:'Off',t:'Engine Off — autonomy paused. Nothing is trading or marking.'}};
var pwrI=0;
function togglePower(){pwrI=(pwrI+1)%PWR.length;var s=PWR[pwrI],el=document.getElementById('sb-power');if(!el)return;el.className='sb-power '+s;el.setAttribute('data-tip',PWR_I[s].t);el.querySelector('.power-lbl').textContent=PWR_I[s].l;}""",
     "if(location.hash)nav(location.hash.replace('#/',''));")

# ── CSS additions ────────────────────────────────────────────────────────────────
CSS = """
/* ── final-v6 polish ── */
.btn-xs{padding:2px 10px;font-size:10.5px}
.sb-dot-wrap{display:flex;align-items:center;justify-content:flex-start;padding:7px 11px;cursor:help}
.sb-dot{width:7px;height:7px;border-radius:50%;background:var(--up);flex-shrink:0}
.sb-dot.warn{background:var(--gold)}.sb-dot.off{background:var(--down)}
body.sb-collapsed .sb-dot-wrap{justify-content:center;padding:7px 0}
.phase-sel button.ph-off{opacity:.4;cursor:not-allowed;color:var(--quiet)}
.ai-head{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}
.ai-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--quiet)}
.ai-badge{font-size:8.5px;color:var(--iris-s);background:var(--iris-dim);border:1px solid var(--iris-mid);border-radius:999px;padding:1px 7px;font-weight:600;letter-spacing:.02em}
.ai-body{font-size:11.5px;line-height:1.55;color:var(--muted)}
.cp-head{font-size:9px;text-transform:uppercase;letter-spacing:.09em;color:var(--quiet);font-weight:700;padding:2px 8px 7px;display:flex;justify-content:space-between;align-items:center}
.cp-hint{font-size:8.5px;font-weight:500;color:var(--border-s);text-transform:none;letter-spacing:0}
.col-picker-item .cp-label{flex:1}
.cp-1 .cp-ind{width:14px;height:14px;border-radius:4px;border:1.5px solid var(--border-s);flex-shrink:0;position:relative;transition:all 120ms}
.cp-1 .col-picker-item.on .cp-ind{background:var(--iris);border-color:var(--iris)}
.cp-1 .col-picker-item.on .cp-ind::after{content:"";position:absolute;left:4px;top:1px;width:3.5px;height:7px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg)}
.cp-1 .col-picker-item.on{background:var(--iris-dim);color:var(--fg)}
.cp-2 .cp-ind{display:none}
.cp-2 .col-picker-item{border:1px solid var(--border);margin-bottom:2px}
.cp-2 .col-picker-item.on{background:var(--iris-dim);border-color:var(--iris-mid);color:var(--iris-s);font-weight:600}
.cp-2 .col-picker-item.on .cp-label::after{content:" ✓";font-weight:700}
.cp-3 .cp-ind{width:26px;height:15px;border-radius:999px;background:var(--surf4);flex-shrink:0;position:relative;transition:background 140ms}
.cp-3 .cp-ind::after{content:"";position:absolute;top:2px;left:2px;width:11px;height:11px;border-radius:50%;background:var(--quiet);transition:all 140ms}
.cp-3 .col-picker-item.on .cp-ind{background:var(--iris)}
.cp-3 .col-picker-item.on .cp-ind::after{left:13px;background:#fff}
.cp-3 .col-picker-item.on .cp-label{color:var(--fg)}
"""
repl("\n</style>", CSS + "\n</style>")

assert "__CPCLASS__" in html
for name, cp in [("cosmu-final-v6-cp1", "cp-1"), ("cosmu-final-v6-cp2", "cp-2"), ("cosmu-final-v6-cp3", "cp-3")]:
    out = html.replace("__CPCLASS__", cp)
    pathlib.Path("mockups/%s.html" % name).write_text(out)
    print("wrote mockups/%s.html  picker=%s  %d bytes" % (name, cp, len(out)))
