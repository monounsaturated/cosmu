#!/usr/bin/env python3
"""Final detail pass v7 — base = cosmu-final-v6-cp1. One canonical output: cosmu-final-v7.html
 - table is now JS-rendered from a COLS config: tighter widths, real horizontal scroll when
   wide, drag column headers to reorder, "Reset to default" button in the picker
 - picker (cp1): whole-row click kept, smoother open transition + cleaner highlight, reset btn
 - Apple-native scrollbars (thin, rounded, semi-transparent, transparent track)
 - AI summary badge -> just the model name ("Sonnet 4.6"), small/lean
 - strat-sheet equity chart: interactive (hover crosshair + tooltip), unified renderer; phases
   never reached stay greyed/disabled; funding panel uses the same interactive chart
 - costs chart: SVG line/area kept, but labels moved to HTML overlay so they no longer stretch
   (the preserveAspectRatio=none text-distortion that read as "broken")
"""
import pathlib

html = pathlib.Path("mockups/cosmu-final-v6-cp1.html").read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:55]!r}], found {c}"
    html = html.replace(old, new)

def cut(start, end_marker, new):
    global html
    a = html.index(start); b = html.index(end_marker, a)
    html = html[:a] + new + html[b:]

# ── A. table: static colgroup/thead -> placeholders ──────────────────────────────
cut('<colgroup>', '<tbody id="screener-body">',
    '<colgroup id="screener-colgroup"></colgroup>\n        <thead id="screener-head"></thead>\n        ')

# ── B. JS table machinery + new renderScreener (prepend before the function) ─────
TABLE_JS = r"""var DEFAULT_COLS=[
 {k:'name',label:'Name',w:200,sort:'name'},
 {k:'stage',label:'Stage',w:92,sort:'stage'},
 {k:'life',label:'Lifecycle',w:104},
 {k:'days',label:'Days',w:54,sort:'days'},
 {k:'val',label:'Value',w:84,sort:'val'},
 {k:'pnl',label:'P&L',w:104,sort:'pnl'},
 {k:'dsr',label:'DSR',w:92,sort:'dsr'},
 {k:'pbo',label:'PBO',w:64,sort:'pbo'},
 {k:'dd',label:'Max DD',w:84,sort:'dd'},
 {k:'oos',label:'OOS',w:66,sort:'oos'},
 {k:'venue',label:'Venue',w:74,vis:false},
 {k:'fees',label:'Fees',w:74,vis:false},
 {k:'origin',label:'Origin',w:84,vis:false}
];
DEFAULT_COLS.forEach(function(c){if(c.vis===undefined)c.vis=true;});
var COLS=DEFAULT_COLS.map(function(c){return Object.assign({},c);});
var DRAG_K=null;
function visCols(){return COLS.filter(function(c){return c.vis;});}
function cellOf(s,k){
 switch(k){
  case 'name': return '<div class="cell-name">'+s.name+'</div>';
  case 'stage': return stageBadge(s.stage,s.killReason,s.gateOk);
  case 'life': return lifGlyph(s.lifecycle);
  case 'days': return s.days>0?'<span class="tab">'+s.days+'</span>':'<span class="quiet">—</span>';
  case 'val': return s.val?'<span class="tab">$'+s.val.toLocaleString('en-US')+'</span>':'<span class="quiet">—</span>';
  case 'pnl': return pnlHeat(s.stage,s.pnlVal,s.pnlPct,s.pnlNum);
  case 'dsr': return dsrBar(s.dsr);
  case 'pbo': return s.pbo!==null?'<span class="tab '+(s.pbo>0.45?'gold':'')+'">'+s.pbo+'</span>':'<span class="quiet">—</span>';
  case 'dd': return ddArc(s.dd,s.ddColor);
  case 'oos': return (s.oos&&s.oos!=='—')?'<span class="tab '+(s.oos.charAt(0)==='+'?'up':'dn')+'">'+s.oos+'</span>':'<span class="quiet">—</span>';
  case 'venue': return '<span class="muted" style="font-size:11px">'+s.venue+'</span>';
  case 'fees': return '<span class="muted tab" style="font-size:11px">'+feesOf(s)+'</span>';
  case 'origin': return '<span class="muted" style="font-size:10.5px;text-transform:capitalize">'+sMeta(s.id).origin+'</span>';
 }
 return '';
}
function renderScreener(){
  var q=(document.getElementById('strat-search')&&document.getElementById('strat-search').value||'').toLowerCase().trim();
  var rows=strategies.filter(function(s){
    if(q&&s.name.toLowerCase().indexOf(q)<0&&s.id.indexOf(q)<0) return false;
    if(activeFilter==='all') return true;
    return s.stage===activeFilter;
  });
  rows=rows.slice().sort(function(a,b){
    var ka=sortKey(a,sortCol),kb=sortKey(b,sortCol);
    if(ka===null||ka===undefined) return 1;
    if(kb===null||kb===undefined) return -1;
    if(typeof ka==='string') return sortDir*ka.localeCompare(kb);
    if(ka===kb) return (STAGE_RANK[b.stage]||0)-(STAGE_RANK[a.stage]||0);
    return sortDir*(ka-kb);
  });
  visibleIds=rows.map(function(s){return s.id;});
  var vc=visCols(),sum=0;vc.forEach(function(c){sum+=c.w;});
  document.getElementById('screener-colgroup').innerHTML=vc.map(function(c){return '<col style="width:'+c.w+'px">';}).join('');
  document.getElementById('screener-head').innerHTML='<tr>'+vc.map(function(c){
    var so=c.sort?' onclick="sortBy(\''+c.sort+'\')" style="cursor:pointer"':'';
    var ind=c.sort?'<span class="sort-ind" id="si-'+c.sort+'"></span>':'';
    return '<th draggable="true" data-k="'+c.k+'" ondragstart="thStart(event,\''+c.k+'\')" ondragover="thOver(event)" ondragleave="thLeave(event)" ondrop="thDrop(event,\''+c.k+'\')" ondragend="thEnd(event)"'+so+'><div class="th-inner">'+c.label+ind+'</div></th>';
  }).join('')+'</tr>';
  paintSortInds();
  document.getElementById('screener-body').innerHTML=rows.map(function(s){
    var isSel=s.id===selectedId;
    var rc=[s.stage==='killed'?'row-killed':'',s.stage==='queued'?'row-queued':'',s.stage==='backtest'?'row-backtest':'',isSel?'sel':''].filter(Boolean).join(' ');
    return '<tr class="'+rc+'" onclick="openPanel(\''+s.id+'\')">'+vc.map(function(c){return '<td>'+cellOf(s,c.k)+'</td>';}).join('')+'</tr>';
  }).join('');
  var t=document.getElementById('screener');if(t)t.style.minWidth=sum+'px';
}
"""
cut("function renderScreener(){", "\nrenderScreener();", TABLE_JS)

# replace the old pickCol with the new column machinery (drag + reset + picker sync)
OLD_PICK = "function pickCol(row){var on=row.classList.toggle('on');var cls=row.dataset.col;document.querySelectorAll('.'+cls+'-h').forEach(function(el){el.classList.toggle('col-hidden',!on);});fitTable();}"
NEW_PICK = """function pickCol(row){var key=row.dataset.col.replace('col-','');var col=COLS.find(function(c){return c.k===key;});if(!col)return;col.vis=!col.vis;row.classList.toggle('on',col.vis);renderScreener();}
function syncPicker(){Array.prototype.forEach.call(document.querySelectorAll('.col-picker-item'),function(row){var key=row.dataset.col.replace('col-','');var col=COLS.find(function(c){return c.k===key;});row.classList.toggle('on',!!(col&&col.vis));});}
function resetCols(){COLS=DEFAULT_COLS.map(function(c){return Object.assign({},c);});syncPicker();renderScreener();}
function thStart(e,k){DRAG_K=k;if(e.dataTransfer){e.dataTransfer.effectAllowed='move';try{e.dataTransfer.setData('text/plain',k);}catch(_){}}}
function thOver(e){e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect='move';e.currentTarget.classList.add('drag-over');}
function thLeave(e){e.currentTarget.classList.remove('drag-over');}
function thEnd(e){Array.prototype.forEach.call(document.querySelectorAll('.drag-over'),function(x){x.classList.remove('drag-over');});}
function thDrop(e,k){e.preventDefault();e.currentTarget.classList.remove('drag-over');var from=COLS.findIndex(function(c){return c.k===DRAG_K;}),to=COLS.findIndex(function(c){return c.k===k;});if(from>=0&&to>=0&&from!==to){var m=COLS.splice(from,1)[0];COLS.splice(to,0,m);}DRAG_K=null;renderScreener();}"""
repl(OLD_PICK, NEW_PICK)

# picker menu: reset button at the bottom
repl('<span class="cp-label">Origin</span></div>\n        </div>',
     '<span class="cp-label">Origin</span></div>\n          <div class="col-picker-divider"></div>\n          <button class="cp-reset" onclick="resetCols()">Reset to default view</button>\n        </div>')

# ── C. AI badge -> model name ────────────────────────────────────────────────────
repl('<span class="ai-badge">Claude Code · local · no API fees</span>',
     '<span class="ai-badge">Sonnet 4.6</span>')

# ── D. interactive strat-sheet chart (replace phaseSvg+sheetChartPhases) ─────────
CHART_JS = r"""var SHEET={ph:{},def:null};
function phaseSeries(ret,days,seed){
  var N=44,start=100,end=100*(1+ret/100),vals=[],labels=[],dd=days||40;
  for(var i=0;i<N;i++){var f=i/(N-1);var w=Math.sin(i*0.6+seed)*Math.abs(end-start)*0.13+Math.sin(i*0.31+1)*Math.abs(end-start)*0.06;vals.push(start+(end-start)*f+w);labels.push('day '+Math.round(f*dd));}
  vals[0]=start;vals[N-1]=end;return {vals:vals,labels:labels};
}
function curveInto(box,vals,labels,col){
  var n=vals.length,mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rng=(mx-mn)||1;
  var lo=mn-rng*0.28,hi=mx+rng*0.28,R=hi-lo,W=1000,H=200,PT=12,PB=12;
  function X(i){return n>1?i/(n-1)*W:0;}function Y(v){return PT+(H-PT-PB)*(1-(v-lo)/R);}
  var line=vals.map(function(v,i){return X(i).toFixed(1)+','+Y(v).toFixed(1);}).join(' ');
  var area='M0,'+Y(vals[0]).toFixed(1)+' L'+line.split(' ').join(' L')+' L'+W+','+H+' L0,'+H+'Z';
  var gy=(PT+(H-PT-PB)*0.5).toFixed(1),gln='<line x1="0" y1="'+gy+'" x2="'+W+'" y2="'+gy+'" stroke="var(--hairline)" stroke-width="1" vector-effect="non-scaling-stroke"/>';
  var gid='shc'+Math.floor(Math.random()*1e6);
  box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:100%;display:block"><defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+col+'" stop-opacity=".2"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+gln+'<path d="'+area+'" fill="url(#'+gid+')"/><polyline points="'+line+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg><div class="xh-line"></div><div class="xh-dot"></div><div class="xh-tip"><div class="tv"></div><div class="td"></div></div>';
  var svg=box.querySelector('svg'),xl=box.querySelector('.xh-line'),xd=box.querySelector('.xh-dot'),xt=box.querySelector('.xh-tip');
  xd.style.background=col;
  svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect();var ratio=Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width));var idx=Math.max(0,Math.min(n-1,Math.round(ratio*(n-1))));var xp=(n>1?idx/(n-1):0)*100,yp=Y(vals[idx])/H*100;box.classList.add('on');xl.style.left=xp+'%';xd.style.left=xp+'%';xd.style.top=yp+'%';var tx=Math.max(7,Math.min(xp,93)),above=yp>30;xt.style.left=tx+'%';xt.style.top='calc('+yp+'% '+(above?'- 10px':'+ 14px')+')';xt.style.transform='translate(-50%,'+(above?'-100%':'0')+')';var pc=vals[idx]-100;xt.querySelector('.tv').textContent=(pc>=0?'+':'')+pc.toFixed(1)+'%';xt.querySelector('.td').textContent=labels[idx];});
  svg.addEventListener('mouseleave',function(){box.classList.remove('on');});
}
function sheetChartSection(cfg,def){
  SHEET={ph:{},def:def};
  var cols={bt:'oklch(0.62 0.05 286)',pa:'oklch(0.66 0.19 290)',li:'oklch(0.78 0.16 160)'};
  ['bt','pa','li'].forEach(function(k){var p=cfg[k];if(p&&p.enabled){var s=phaseSeries(p.ret,p.days,k.charCodeAt(0));SHEET.ph[k]={vals:s.vals,labels:s.labels,color:cols[k]};}});
  function btn(k,lbl){var p=cfg[k];return (p&&p.enabled)?'<button class="'+(def===k?'on':'')+'" onclick="setPhase(\''+k+'\',this)">'+lbl+'</button>':'<button class="ph-off" data-tip="'+((p&&p.tip)||'')+'">'+lbl+'</button>';}
  var titles={bt:'Backtest',pa:'Paper',li:'Live'};
  return '<div class="psec"><div class="eq-head"><span class="eq-title-txt" id="eq-title">Equity — '+titles[def]+'</span><div class="phase-sel">'+btn('bt','Backtest')+btn('pa','Paper')+btn('li','Live')+'</div></div><div class="eqwrap sheet-eq" id="sheet-eq" style="height:120px"></div><div class="eq-axis"><span id="sheet-ax0"></span><span id="sheet-ax1"></span></div></div>';
}
function drawSheetPhase(ph){
  var d=SHEET.ph[ph];if(!d)return;var box=document.getElementById('sheet-eq');if(!box)return;
  var titles={bt:'Backtest',pa:'Paper',li:'Live'},ti=document.getElementById('eq-title');if(ti)ti.textContent='Equity — '+titles[ph];
  curveInto(box,d.vals,d.labels,d.color);
  var a0=document.getElementById('sheet-ax0'),a1=document.getElementById('sheet-ax1');if(a0)a0.textContent=d.labels[0];if(a1)a1.textContent=d.labels[d.labels.length-1];
}
function tplChart(s){
  var hasBt=s.oos&&s.oos!=='—'&&s.oos!=='';
  var reachedPa=['paper','paper-ready','live'].indexOf(s.stage)>=0,reachedLi=s.stage==='live';
  if(!hasBt&&!reachedPa)return '<div class="psec"><div class="psec-title">Equity</div><div class="eq-empty">No equity curve yet — this strategy is still in the backtest queue.</div></div>';
  var o=parseFloat((s.oos||'').replace(/[^-0-9.]/g,'')),btRet=isNaN(o)?2:o;
  var cfg={bt:{enabled:hasBt,ret:btRet,days:60,tip:'No backtest data yet'},
    pa:{enabled:reachedPa,ret:reachedPa?(s.pnlNum||1):0,days:s.days||30,tip:'Never reached paper'+(s.killReason?' — killed at backtest':'')},
    li:{enabled:reachedLi,ret:reachedLi?(s.pnlNum||1):0,days:s.days||18,tip:'Never went live'+(s.killReason?' — killed at backtest':'')}};
  return sheetChartSection(cfg,reachedLi?'li':reachedPa?'pa':'bt');
}
"""
cut("function phaseSvg(id,ret,col,caption,show){", "function aiSummary(s){", CHART_JS)

# setPhase -> dynamic redraw
repl("""function setPhase(ph,btn){
  if(btn.classList.contains('ph-off'))return;
  document.querySelectorAll('.phase-sel button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  ['bt','pa','li'].forEach(k=>{const el=document.getElementById('eq-'+k);if(el)el.style.display=k===ph?'block':'none'});
  const ti=document.getElementById('eq-title');if(ti&&btn.dataset.title)ti.innerHTML=btn.dataset.title;
}""",
"""function setPhase(ph,btn){if(btn.classList.contains('ph-off'))return;document.querySelectorAll('.phase-sel button').forEach(function(b){b.classList.remove('on');});btn.classList.add('on');drawSheetPhase(ph);}""")

repl("${sheetChartPhases(s)}", "${tplChart(s)}")

# funding panel: replace the static phase-chart psec with the interactive one.
# (that static psec also WRAPPED the phase-comparison table; give the table its own psec so the
#  trailing </div> that used to close the big psec now closes the table's psec — keeps divs balanced)
cut('<div class="psec">\n  <div class="eq-head">', "  ${aiSummary(strategies.find(x=>x.id==='funding-carry-btc')",
    "${sheetChartSection({bt:{enabled:true,ret:8.2,days:300},pa:{enabled:true,ret:9.3,days:47},li:{enabled:true,ret:21,days:18}},'li')}\n")
repl('  <!-- PHASE COMPARISON TABLE per spec -->\n  <table class="phase-tbl">',
     '  <div class="psec">\n  <div class="psec-title">Phase comparison</div>\n  <table class="phase-tbl">')

# openPanel: draw the default phase after the panel mounts
repl("""  document.getElementById('panel-body').innerHTML=panelContent(id);
  document.getElementById('side-panel').classList.add('open');""",
"""  document.getElementById('panel-body').innerHTML=panelContent(id);
  if(document.getElementById('sheet-eq')&&SHEET.def)drawSheetPhase(SHEET.def);
  document.getElementById('side-panel').classList.add('open');""")

# ── E. costs chart: HTML-overlay labels (no stretched SVG text) ──────────────────
a = html.index("function spark(){")
b = html.index("\nfunction renderChart(", a)
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
  var area='M'+X(0).toFixed(1)+','+Y(0).toFixed(1)+' L'+poly.split(' ').join(' L')+' L'+lastx.toFixed(1)+','+(H-PB)+' L'+X(0).toFixed(1)+','+(H-PB)+'Z';
  var svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" width="100%" height="'+H+'" style="display:block">'+
   '<defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--iris)" stop-opacity=".22"/><stop offset="100%" stop-color="var(--iris)" stop-opacity="0"/></linearGradient></defs>'+
   '<path d="'+area+'" fill="url(#cg)"/>'+
   '<polyline points="'+poly+'" fill="none" stroke="var(--iris)" stroke-width="1.8" vector-effect="non-scaling-stroke"/>'+
   '<line x1="'+lastx.toFixed(1)+'" y1="'+lasty.toFixed(1)+'" x2="'+projx.toFixed(1)+'" y2="'+projy.toFixed(1)+'" stroke="var(--quiet)" stroke-width="1.3" stroke-dasharray="4,3" vector-effect="non-scaling-stroke"/>'+
   '<circle cx="'+lastx.toFixed(1)+'" cy="'+lasty.toFixed(1)+'" r="3" fill="var(--iris)"/></svg>';
  function lx(c){return (c/W*100).toFixed(2)+'%';}
  var labels='<span class="cspark-lbl" style="left:'+lx(X(0))+';top:'+(H-12)+'px">Apr 1</span>'+
   '<span class="cspark-lbl cs-today" style="left:'+lx(lastx)+';top:'+(lasty-15).toFixed(0)+'px;transform:translateX(-50%)">today '+fmt(life)+'</span>'+
   '<span class="cspark-lbl" style="left:'+lx(projx)+';top:'+(projy-15).toFixed(0)+'px;transform:translateX(-100%)">proj. '+fmt(projVal)+'</span>';
  return '<div class="cspark">'+svg+labels+'</div>';
}
"""
html = html[:a] + NEW_SPARK + html[b:]

# ── F. CSS ───────────────────────────────────────────────────────────────────────
CSS = """
/* ── v7: scrollbars, picker polish, drag, reset, model badge, sheet chart, cost labels ── */
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:color-mix(in oklab,var(--muted) 28%,transparent);border-radius:8px;border:2px solid transparent;background-clip:padding-box}
::-webkit-scrollbar-thumb:hover{background:color-mix(in oklab,var(--muted) 44%,transparent);background-clip:padding-box}
::-webkit-scrollbar-corner{background:transparent}
html{scrollbar-width:thin;scrollbar-color:color-mix(in oklab,var(--muted) 30%,transparent) transparent}
.col-picker-menu{display:block;opacity:0;visibility:hidden;transform:translateY(-5px) scale(.97);transform-origin:top right;transition:opacity 150ms ease,transform 150ms cubic-bezier(.16,1,.3,1),visibility 150ms;pointer-events:none}
.col-picker-menu.open{opacity:1;visibility:visible;transform:none;pointer-events:auto}
.col-picker-item{transition:background 120ms,color 120ms}
.cp-1 .col-picker-item.on{background:var(--iris-dim);color:var(--fg)}
.cp-1 .col-picker-item.on .cp-ind{background:var(--iris);border-color:var(--iris)}
.cp-reset{display:block;width:100%;text-align:left;padding:6px 9px;margin-top:1px;border:none;background:transparent;color:var(--quiet);font-family:inherit;font-size:11px;cursor:pointer;border-radius:var(--r-xs);transition:background 120ms,color 120ms}
.cp-reset:hover{background:var(--surf3);color:var(--fg)}
th[draggable=true]{cursor:pointer}
.screener-table thead th.drag-over{box-shadow:inset 2px 0 0 var(--iris)}
.screener-table thead th.drag-over .th-inner{opacity:.6}
.ai-badge{font-size:9px;color:var(--muted);background:transparent;border:1px solid var(--border);border-radius:999px;padding:1px 8px;font-weight:600;letter-spacing:.01em}
.sheet-eq{position:relative;width:100%}
.cspark{position:relative;width:100%}
.cspark-lbl{position:absolute;font-size:9px;color:var(--quiet);font-variant-numeric:tabular-nums;pointer-events:none;white-space:nowrap;letter-spacing:.02em}
.cspark-lbl.cs-today{color:var(--iris-s);font-weight:600}
"""
repl("\n</style>", CSS + "\n</style>")

pathlib.Path("mockups/cosmu-final-v7.html").write_text(html)
print("wrote mockups/cosmu-final-v7.html", len(html), "bytes")
