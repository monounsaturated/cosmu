#!/usr/bin/env python3
"""Build 3 final dashboard mockups from dash-03-stripe.html.

Fixes vs the 10-dash round:
 - chart no longer cropped / over-zoomed: 30% y-padding, taller (210px), 2px line,
   gridlines, tooltip clamped + flips below when near the top, axis date labels.
 - KPI numbers slightly smaller on the dashboards.
 - guardrails: plain text "amount / limit" (no arc, no %-of-cap), editable caps, compact strip.
 - chart ALWAYS on top of the screen, above every other box.
 - paper dashboard = chart + KPIs + recent trades (paper-tracks table removed).
 - live keeps open positions + recent trades + guardrails (the "more data" specificity).
 - 3 versions share the same chart/KPI/trades skeleton so paper & live look most alike.
"""
import re, pathlib

SRC = pathlib.Path("mockups/dash-03-stripe.html")
html = SRC.read_text()

# ── 1. CSS additions (before </style>) ──────────────────────────────────────────
CSS = """
/* ── final dashboards: smaller KPIs, fixed chart, text guardrails ── */
#dash-live .kpi-val,#dash-paper .kpi-val{font-size:21px}
#dash-live .kpi-box,#dash-paper .kpi-box{padding:11px 13px}
.eqwrap{overflow:visible}
.eq-axis{display:flex;justify-content:space-between;font-size:9.5px;color:var(--quiet);margin-top:7px;font-variant-numeric:tabular-nums}
.guard-strip{display:flex;align-items:center;gap:9px 20px;flex-wrap:wrap;padding:11px 16px}
.guard-strip .gtitle{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--quiet);font-weight:700;margin-right:2px}
.gmetric{display:inline-flex;align-items:baseline;gap:6px;font-size:12.5px}
.gmetric .gl{color:var(--muted)}
.gmetric .gu{font-weight:700;font-variant-numeric:tabular-nums}
.gmetric .gc{color:var(--quiet);font-variant-numeric:tabular-nums;cursor:pointer;border-bottom:1px dashed transparent}
.gmetric .gc:hover{color:var(--muted);border-bottom-color:var(--border-s)}
"""
assert html.count("\n</style>") == 1, "expected exactly one </style>"
html = html.replace("\n</style>", CSS + "\n</style>", 1)

# ── 2. replace the dashboard engine span ────────────────────────────────────────
START = "window.DASH_MODE='stripe';"
END = "renderDash('paper');renderDash('live');"
s = html.index(START)
e = html.index(END) + len(END)

ENGINE = r"""window.DASH_MODE='__MODE__';

// ── interactive dashboards (final) ──
var DASH={
 live:{equity:9419,invested:1700,free:7300,pnl:419,pnlPct:21,days:18,
   guards:{dailyLoss:{used:34,cap:180,unit:'$'},maxDD:{used:3.1,cap:25,unit:'%'},exposure:{used:18.9,cap:80,unit:'%'}},
   positions:[{n:'Funding Carry BTC',sym:'BTC/USDC',qty:'0.026 BTC',mark:'$9,419',pnl:'+$419',pct:'+21%'}],
   trades:[['2026-06-12','14:22','Funding Carry BTC','Buy','$67,200',''],['2026-06-04','09:11','Funding Carry BTC','Sell','$69,840','+$88'],['2026-05-28','17:46','Funding Carry BTC','Buy','$65,100',''],['2026-05-20','08:03','Funding Carry BTC','Sell','$66,900','+$60'],['2026-05-14','21:30','Funding Carry BTC','Buy','$63,500',''],['2026-05-06','11:55','Funding Carry BTC','Sell','$65,200','+$58']]},
 paper:{equity:19784,invested:18392,free:0,pnl:1392,pnlPct:9.27,tracks:4,ready:2,
   trades:[['2026-06-11','22:10','Cross-Sect Momentum','Buy','$3,210',''],['2026-06-10','22:10','GTAA Monthly','Sell','$2,901','+2.1%'],['2026-06-09','22:10','Stablecoin Flows ETH','Buy','$1,141','+1.9%'],['2026-06-07','22:10','Fear & Greed ETH','Buy','$971','-0.9%'],['2026-06-05','22:10','Cross-Sect Momentum','Sell','$3,114','+2.8%'],['2026-06-03','22:10','GTAA Monthly','Buy','$2,840','']]}
};
var SER={};
function buildSeries(which){var d=DASH[which];var N=which==='live'?50:55;var start=which==='live'?9000:18392;var end=d.equity;var a=[],ds=[];var e=new Date('2026-06-13T00:00:00');
 for(var i=0;i<N;i++){var f=i/(N-1);var w=Math.sin(i*0.85)*(Math.abs(end-start)*0.05)+Math.sin(i*0.33+1)*(Math.abs(end-start)*0.03);a.push(Math.round(start+(end-start)*f+w));var dd=new Date(e);dd.setDate(e.getDate()-(N-1-i));ds.push(dd);}
 a[0]=start;a[N-1]=end;
 var intr=[],ids=[];for(var h=0;h<24;h++){var w2=Math.sin(h*0.55)*(end*0.0013);intr.push(Math.round(a[N-2]+(end-a[N-2])*(h/23)+w2));var hd=new Date('2026-06-13T00:00:00');hd.setHours(h);ids.push(hd);}intr[23]=end;
 return {all:a,dates:ds,intr:intr,idates:ids};}
function tf(which,t){var s=SER[which];if(t==='1D')return {v:s.intr,d:s.idates,intra:true};var n=t==='7D'?7:t==='30D'?30:s.all.length;return {v:s.all.slice(-n),d:s.dates.slice(-n),intra:false};}
function dfmt(n){return '$'+Math.round(n).toLocaleString('en-US');}
function dfmtDate(d,intra){return intra?d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}):d.toLocaleDateString('en-US',{month:'short',day:'numeric'});}

function mkChart(which,t){var box=document.getElementById('eq-'+which);if(!box)return;var dat=tf(which,t),v=dat.v,ds=dat.d,n=v.length;
 var mn=Math.min.apply(null,v),mx=Math.max.apply(null,v),rng=(mx-mn)||Math.abs(mx)*0.01||1;
 var lo=mn-rng*0.30,hi=mx+rng*0.30,R=hi-lo;var W=1000,H=210,PT=14,PB=14;
 function X(i){return n>1?i/(n-1)*W:0;}function Y(val){return PT+(H-PT-PB)*(1-(val-lo)/R);}
 var up=v[n-1]>=v[0],col=up?'var(--up)':'var(--down)';
 var line=v.map(function(val,i){return X(i).toFixed(1)+','+Y(val).toFixed(1);}).join(' ');
 var area='M0,'+Y(v[0]).toFixed(1)+' L'+line.split(' ').join(' L')+' L'+W+','+H+' L0,'+H+'Z';
 var gln='';[0.25,0.5,0.75].forEach(function(g){var gy=(PT+(H-PT-PB)*g).toFixed(1);gln+='<line x1="0" y1="'+gy+'" x2="'+W+'" y2="'+gy+'" stroke="var(--hairline)" stroke-width="1" vector-effect="non-scaling-stroke"/>';});
 box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:210px;display:block"><defs><linearGradient id="eg-'+which+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+col+'" stop-opacity=".22"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+gln+'<path d="'+area+'" fill="url(#eg-'+which+')"/><polyline points="'+line+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg><div class="xh-line"></div><div class="xh-dot"></div><div class="xh-tip"><div class="tv"></div><div class="td"></div></div>';
 var svg=box.querySelector('svg'),xl=box.querySelector('.xh-line'),xd=box.querySelector('.xh-dot'),xt=box.querySelector('.xh-tip');
 xd.style.background=col;
 var hd=document.getElementById('hd-'+which),dl=document.getElementById('dl-'+which);
 var ax0=document.getElementById('ax0-'+which),ax1=document.getElementById('ax1-'+which);
 if(ax0)ax0.textContent=dfmtDate(ds[0],dat.intra);if(ax1)ax1.textContent=dfmtDate(ds[n-1],dat.intra);
 function setHd(val,base){if(hd)hd.textContent=dfmt(val);if(dl){var d=val-base;dl.textContent=(d>=0?'+':'-')+dfmt(Math.abs(d)).slice(1)+' ('+(d>=0?'+':'')+(d/base*100).toFixed(1)+'%)';dl.className='hero-delta tab '+(d>=0?'up':'dn');}}
 function restore(){box.classList.remove('on');setHd(v[n-1],v[0]);}
 svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect();var ratio=(ev.clientX-r.left)/r.width;var idx=Math.max(0,Math.min(n-1,Math.round(ratio*(n-1))));var px=idx/(n-1)*r.width,py=Y(v[idx])/H*r.height;box.classList.add('on');xl.style.left=px+'px';xd.style.left=px+'px';xd.style.top=py+'px';var tx=Math.max(48,Math.min(px,r.width-48)),above=py>52;xt.style.left=tx+'px';xt.style.top=(py+(above?-10:14))+'px';xt.style.transform='translate(-50%,'+(above?'-100%':'0')+')';xt.querySelector('.tv').textContent=dfmt(v[idx]);xt.querySelector('.td').textContent=dfmtDate(ds[idx],dat.intra);setHd(v[idx],v[0]);});
 svg.addEventListener('mouseleave',restore);restore();}
function setTF(which,t,btn){Array.prototype.forEach.call(btn.parentNode.children,function(b){b.classList.toggle('on',b===btn);});mkChart(which,t);}

// guardrails — compact text, editable caps, no arc, no %-of-cap
function gcol(o){var r=Math.min(o.used/o.cap,1);return r>=0.85?'var(--down)':r>=0.6?'var(--gold)':'var(--up)';}
function gv(o,w){return o.unit==='$'?'$'+o[w]:o[w]+'%';}
function gmetric(key,label){var o=DASH.live.guards[key];return '<span class="gmetric"><span class="gl">'+label+'</span><span class="gu" style="color:'+gcol(o)+'">'+gv(o,'used')+'</span><span class="gc" onclick="editCap(event,\''+key+'\')" title="Click to edit the limit">/ '+gv(o,'cap')+'</span></span>';}
function guardStrip(){return '<div class="card dh"><div class="guard-strip"><span class="gtitle">Guardrails · auto-halt if breached</span>'+gmetric('dailyLoss','Daily loss')+gmetric('maxDD','Max drawdown')+gmetric('exposure','Exposure')+'</div></div>';}
function editCap(ev,key){var sp=ev.currentTarget;var o=DASH.live.guards[key];var inp=document.createElement('input');inp.className='cap-in';inp.value=o.cap;
 inp.onkeydown=function(e){if(e.key==='Enter')inp.blur();if(e.key==='Escape'){inp.value=o.cap;inp.blur();}};
 inp.onblur=function(){var nn=parseFloat(inp.value);if(!isNaN(nn)&&nn>0)o.cap=nn;renderDash('live');};
 sp.replaceWith(inp);inp.focus();inp.select();}

// components
function equityBlock(which,defTf){var d=DASH[which],lab=which==='live'?'Total equity':'Paper equity';defTf=defTf||'30D';
 return '<div class="card dh" style="padding:14px 16px">'+
  '<div class="hero-top"><div><div class="hero-label">'+lab+'</div><div><span class="hero-val tab" id="hd-'+which+'">'+dfmt(d.equity)+'</span><span class="hero-delta tab up" id="dl-'+which+'">+'+dfmt(d.pnl).slice(1)+' (+'+d.pnlPct+'%)</span></div></div>'+
  '<div class="tf-seg">'+['1D','7D','30D','All'].map(function(x){return '<button'+(x===defTf?' class="on"':'')+' onclick="setTF(\''+which+'\',\''+x+'\',this)">'+x+'</button>';}).join('')+'</div></div>'+
  '<div class="eqwrap" id="eq-'+which+'"></div>'+
  '<div class="eq-axis"><span id="ax0-'+which+'"></span><span id="ax1-'+which+'"></span></div></div>';}
function allocDonut(){var inv=DASH.live.invested,fr=DASH.live.free,tot=inv+fr,pi=inv/tot;var C=2*Math.PI*30;
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Capital allocation</span></div><div class="card-body"><div class="donut-wrap"><svg width="80" height="80" viewBox="0 0 80 80"><circle cx="40" cy="40" r="30" fill="none" stroke="var(--surf3)" stroke-width="11"/><circle cx="40" cy="40" r="30" fill="none" stroke="var(--iris)" stroke-width="11" stroke-dasharray="'+(C*pi).toFixed(1)+' '+C.toFixed(1)+'" transform="rotate(-90 40 40)" stroke-linecap="round"/><text x="40" y="44" text-anchor="middle" font-size="14" font-weight="700" fill="var(--fg)">'+Math.round(pi*100)+'%</text></svg><div class="alloc-legend" style="flex-direction:column;gap:6px"><span><i class="alloc-inv"></i>Invested '+dfmt(inv)+' · '+Math.round(pi*100)+'%</span><span><i class="alloc-free"></i>Free '+dfmt(fr)+' · '+Math.round((1-pi)*100)+'%</span></div></div></div></div>';}
function kbox(label,val,sub,cls){return '<div class="kpi-box"><div class="kpi-label">'+label+'</div><div class="kpi-val tab'+(cls?' '+cls:'')+'">'+val+'</div><div class="kpi-sub '+(cls||'muted')+'">'+sub+'</div></div>';}
function kpiLive(){var d=DASH.live,tot=d.invested+d.free;
 return kbox('Invested',dfmt(d.invested),Math.round(d.invested/tot*100)+'% of capital · 1 strategy','')+
  kbox('Free',dfmt(d.free),Math.round(d.free/tot*100)+'% idle','')+
  kbox('P&L','+'+dfmt(d.pnl).slice(1),'+'+d.pnlPct+'% · '+d.days+'d live','up');}
function kpiPaper(){var d=DASH.paper;
 return kbox('Invested',dfmt(d.invested),'across '+d.tracks+' strategies','')+
  kbox('P&L','+'+dfmt(d.pnl).slice(1),'+'+d.pnlPct+'% avg','up')+
  kbox('Tracks',d.tracks,'running','')+
  kbox('Live-ready',d.ready,'≥30 net-positive days','gold');}
function tradesBox(which){var tr=DASH[which].trades;var rows=tr.map(function(x){return '<tr><td class="muted" style="white-space:nowrap">'+new Date(x[0]+'T00:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})+' <span style="color:var(--quiet)">'+x[1]+'</span></td><td>'+x[2]+'</td><td class="side-'+(x[3]==='Buy'?'buy':'sell')+'">'+x[3]+'</td><td class="r tab">'+x[4]+'</td><td class="r tab '+(x[5]?(x[5][0]==='-'?'dn':'up'):'muted')+'">'+(x[5]||'open')+'</td></tr>';}).join('');
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Recent trades</span></div><div class="card-body" style="max-height:260px;overflow-y:auto"><table class="mini-tbl"><thead><tr><th>Date · time</th><th>Strategy</th><th>Side</th><th class="r">Price</th><th class="r">P&L</th></tr></thead><tbody>'+rows+'</tbody></table></div></div>';}
function positions(){var p=DASH.live.positions.map(function(x){return '<tr><td>'+x.n+'</td><td class="muted">'+x.sym+'</td><td class="r tab">'+x.qty+'</td><td class="r tab">'+x.mark+'</td><td class="r tab up">'+x.pnl+' '+x.pct+'</td></tr>';}).join('');
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Open positions</span></div><div class="card-body"><table class="mini-tbl"><thead><tr><th>Strategy</th><th>Pair</th><th class="r">Size</th><th class="r">Value</th><th class="r">P&L</th></tr></thead><tbody>'+p+'</tbody></table></div></div>';}
function grid(cols,html){return '<div class="kgrid" style="grid-template-columns:'+cols+'">'+html+'</div>';}

var MODE=(window.DASH_MODE||'clean');
function renderDash(which){
 var live=which==='live';var kpi=live?kpiLive():kpiPaper();var kcols=live?'repeat(3,1fr)':'repeat(4,1fr)';
 var H=equityBlock(which);  // chart ALWAYS on top
 if(MODE==='donut'){
   if(live){H+=grid('1.55fr 1fr','<div class="kgrid" style="grid-template-columns:repeat(3,1fr);margin:0">'+kpi+'</div>'+allocDonut());}
   else{H+=grid(kcols,kpi);}
   if(live){H+=guardStrip()+positions();}
   H+=tradesBox(which);
 }else if(MODE==='split'){
   H+=grid(kcols,kpi);
   if(live){H+=guardStrip()+grid('1fr 1fr',positions()+tradesBox(which));}
   else{H+=tradesBox(which);}
 }else{ // clean
   H+=grid(kcols,kpi);
   if(live){H+=guardStrip()+positions();}
   H+=tradesBox(which);
 }
 document.getElementById('dash-'+which).innerHTML=H;
 SER[which]=buildSeries(which);mkChart(which,'30D');
}
renderDash('paper');renderDash('live');"""

base = html[:s] + ENGINE + html[e:]

# ── 3. emit the 3 versions ──────────────────────────────────────────────────────
VERSIONS = {
    "final-1-clean": "clean",
    "final-2-donut": "donut",
    "final-3-split": "split",
}
for name, mode in VERSIONS.items():
    out = base.replace("window.DASH_MODE='__MODE__';", "window.DASH_MODE='%s';" % mode, 1)
    assert "__MODE__" not in out
    pathlib.Path("mockups/%s.html" % name).write_text(out)
    print("wrote mockups/%s.html  (mode=%s)  %d bytes" % (name, mode, len(out)))
