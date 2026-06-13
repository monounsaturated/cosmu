#!/usr/bin/env python3
"""Round 2 of the final dashboards — base = final-3-split (the winner).

Changes the user asked for:
 - chart a bit smaller (CH=150); keep ONE big-chart version (CH=210) too.
 - guardrails decluttered: drop the "auto-halt if breached" subtitle, airier spacing.
 - add Open positions to the PAPER dashboard as well (paper & live now mirror each
   other: chart -> KPIs -> [positions | trades], live adds the guardrails strip).
 - same exact version rendered with different chart libraries to compare display:
   hand-SVG, Chart.js, ApexCharts, uPlot.
 - one version with a neutral "medium light black" background (less purple).
"""
import pathlib

SRC = pathlib.Path("mockups/final-3-split.html")
html = SRC.read_text()

# ── 1. CSS: declutter guardrails + library containers ───────────────────────────
OLD_CSS = """.guard-strip{display:flex;align-items:center;gap:9px 20px;flex-wrap:wrap;padding:11px 16px}
.guard-strip .gtitle{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--quiet);font-weight:700;margin-right:2px}
.gmetric{display:inline-flex;align-items:baseline;gap:6px;font-size:12.5px}
.gmetric .gl{color:var(--muted)}
.gmetric .gu{font-weight:700;font-variant-numeric:tabular-nums}
.gmetric .gc{color:var(--quiet);font-variant-numeric:tabular-nums;cursor:pointer;border-bottom:1px dashed transparent}
.gmetric .gc:hover{color:var(--muted);border-bottom-color:var(--border-s)}"""
NEW_CSS = """.guard-strip{display:flex;align-items:center;gap:26px;flex-wrap:wrap;padding:12px 18px}
.guard-strip .gtitle{font-size:9.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--quiet);font-weight:700}
.gmetric{display:inline-flex;align-items:baseline;gap:8px;font-size:13px}
.gmetric .gl{color:var(--muted);font-size:11.5px}
.gmetric .gu{font-weight:700;font-variant-numeric:tabular-nums}
.gmetric .gc{color:var(--quiet);font-variant-numeric:tabular-nums;cursor:pointer;border-bottom:1px dashed transparent}
.gmetric .gc:hover{color:var(--muted);border-bottom-color:var(--border-s)}
.eqwrap canvas,.eqwrap .apx,.eqwrap .uplot{width:100%!important}
.eqwrap .uplot{font-family:inherit}
.apexcharts-tooltip{background:var(--surf4)!important;border:1px solid var(--border)!important;color:var(--fg)!important;box-shadow:var(--cell-shadow)!important}
.apexcharts-tooltip-title{background:var(--surf3)!important;border-bottom:1px solid var(--border)!important}"""
assert html.count(OLD_CSS) == 1, "guard CSS not found uniquely"
html = html.replace(OLD_CSS, NEW_CSS, 1)

# ── 1b. strip the dead old-guardrails block (renderLive → #live-kpis never exists) ──
dead_s = html.index("window.GUARD_LAYOUT='onerow6';")
dead_e = html.index("window.DASH_MODE='split';")
assert dead_s < dead_e
html = html[:dead_s] + html[dead_e:]

# ── 2. replace the dashboard engine span ────────────────────────────────────────
START = "window.DASH_MODE='split';"
END = "renderDash('paper');renderDash('live');"
s = html.index(START)
e = html.index(END) + len(END)

ENGINE = r"""window.CHART_LIB='__LIB__';   // svg | chartjs | apex | uplot
window.CHART_H=__CH__;

// ── interactive dashboards (final v2 — split layout, paper+live mirror) ──
var DASH={
 live:{equity:9419,invested:1700,free:7300,pnl:419,pnlPct:21,days:18,
   guards:{dailyLoss:{used:34,cap:180,unit:'$'},maxDD:{used:3.1,cap:25,unit:'%'},exposure:{used:18.9,cap:80,unit:'%'}},
   positions:[{n:'Funding Carry BTC',sym:'BTC/USDC',qty:'0.026 BTC',mark:'$9,419',pnl:'+$419',pct:'+21%'}],
   trades:[['2026-06-12','14:22','Funding Carry BTC','Buy','$67,200',''],['2026-06-04','09:11','Funding Carry BTC','Sell','$69,840','+$88'],['2026-05-28','17:46','Funding Carry BTC','Buy','$65,100',''],['2026-05-20','08:03','Funding Carry BTC','Sell','$66,900','+$60'],['2026-05-14','21:30','Funding Carry BTC','Buy','$63,500',''],['2026-05-06','11:55','Funding Carry BTC','Sell','$65,200','+$58']]},
 paper:{equity:19784,invested:18392,free:0,pnl:1392,pnlPct:9.27,tracks:4,ready:2,
   positions:[{n:'Cross-Sect Momentum',sym:'Multi · 5 names',qty:'$5,140',mark:'$5,351',pnl:'+$211',pct:'+4.1%'},{n:'GTAA Monthly',sym:'Multi · 4 ETPs',qty:'$4,980',mark:'$5,124',pnl:'+$144',pct:'+2.9%'},{n:'Stablecoin Flows ETH',sym:'ETH/USDC',qty:'1.8 ETH',mark:'$4,361',pnl:'+$52',pct:'+1.2%'},{n:'Fear & Greed ETH',sym:'ETH/USDC',qty:'1.2 ETH',mark:'$3,556',pnl:'-$28',pct:'-0.8%'}],
   trades:[['2026-06-11','22:10','Cross-Sect Momentum','Buy','$3,210',''],['2026-06-10','22:10','GTAA Monthly','Sell','$2,901','+2.1%'],['2026-06-09','22:10','Stablecoin Flows ETH','Buy','$1,141','+1.9%'],['2026-06-07','22:10','Fear & Greed ETH','Buy','$971','-0.9%'],['2026-06-05','22:10','Cross-Sect Momentum','Sell','$3,114','+2.8%'],['2026-06-03','22:10','GTAA Monthly','Buy','$2,840','']]}
};
var SER={},CHARTS={},CUR={};
var CLIB=(window.CHART_LIB||'svg'),CH=(window.CHART_H||210);
function buildSeries(which){var d=DASH[which];var N=which==='live'?50:55;var start=which==='live'?9000:18392;var end=d.equity;var a=[],ds=[];var e=new Date('2026-06-13T00:00:00');
 for(var i=0;i<N;i++){var f=i/(N-1);var w=Math.sin(i*0.85)*(Math.abs(end-start)*0.05)+Math.sin(i*0.33+1)*(Math.abs(end-start)*0.03);a.push(Math.round(start+(end-start)*f+w));var dd=new Date(e);dd.setDate(e.getDate()-(N-1-i));ds.push(dd);}
 a[0]=start;a[N-1]=end;
 var intr=[],ids=[];for(var h=0;h<24;h++){var w2=Math.sin(h*0.55)*(end*0.0013);intr.push(Math.round(a[N-2]+(end-a[N-2])*(h/23)+w2));var hd=new Date('2026-06-13T00:00:00');hd.setHours(h);ids.push(hd);}intr[23]=end;
 return {all:a,dates:ds,intr:intr,idates:ids};}
function tf(which,t){var s=SER[which];if(t==='1D')return {v:s.intr,d:s.idates,intra:true};var n=t==='7D'?7:t==='30D'?30:s.all.length;return {v:s.all.slice(-n),d:s.dates.slice(-n),intra:false};}
function dfmt(n){return '$'+Math.round(n).toLocaleString('en-US');}
function dfmtDate(d,intra){return intra?d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}):d.toLocaleDateString('en-US',{month:'short',day:'numeric'});}
function getCss(v){try{return getComputedStyle(document.documentElement).getPropertyValue(v).trim();}catch(e){return v;}}
function oklchA(s,a){return s&&s.indexOf('oklch')===0?s.replace(/\)\s*$/,' / '+a+')'):s;}

// headline scrub (shared by every chart lib)
function setHead(which,val){var c=CUR[which];if(!c)return;var hd=document.getElementById('hd-'+which),dl=document.getElementById('dl-'+which);if(hd)hd.textContent=dfmt(val);if(dl){var d=val-c.base;dl.textContent=(d>=0?'+':'-')+dfmt(Math.abs(d)).slice(1)+' ('+(d>=0?'+':'')+(d/c.base*100).toFixed(1)+'%)';dl.className='hero-delta tab '+(d>=0?'up':'dn');}}
function restoreHead(which){var c=CUR[which];if(c)setHead(which,c.v[c.n-1]);}
function setAxis(which,ds,intra){var a0=document.getElementById('ax0-'+which),a1=document.getElementById('ax1-'+which);if(a0)a0.textContent=dfmtDate(ds[0],intra);if(a1)a1.textContent=dfmtDate(ds[ds.length-1],intra);}

function mkChart(which,t){var dat=tf(which,t),v=dat.v,n=v.length;CUR[which]={v:v,base:v[0],n:n};setAxis(which,dat.d,dat.intra);
 var box=document.getElementById('eq-'+which);if(!box)return;box.style.height=CH+'px';
 if(CHARTS[which]&&CHARTS[which].destroy){try{CHARTS[which].destroy();}catch(e){}CHARTS[which]=null;}
 if(CLIB==='chartjs'&&typeof Chart!=='undefined')return chartJS(which,dat,box);
 if(CLIB==='apex'&&typeof ApexCharts!=='undefined')return chartApex(which,dat,box);
 if(CLIB==='uplot'&&typeof uPlot!=='undefined')return chartUplot(which,dat,box);
 return chartSVG(which,dat,box);}
function setTF(which,t,btn){Array.prototype.forEach.call(btn.parentNode.children,function(b){b.classList.toggle('on',b===btn);});mkChart(which,t);}

// ---- hand-rolled SVG (default) ----
function chartSVG(which,dat,box){var v=dat.v,ds=dat.d,n=v.length;
 var mn=Math.min.apply(null,v),mx=Math.max.apply(null,v),rng=(mx-mn)||Math.abs(mx)*0.01||1;
 var lo=mn-rng*0.30,hi=mx+rng*0.30,R=hi-lo;var W=1000,H=CH,PT=14,PB=14;
 function X(i){return n>1?i/(n-1)*W:0;}function Y(val){return PT+(H-PT-PB)*(1-(val-lo)/R);}
 var up=v[n-1]>=v[0],col=up?'var(--up)':'var(--down)';
 var line=v.map(function(val,i){return X(i).toFixed(1)+','+Y(val).toFixed(1);}).join(' ');
 var area='M0,'+Y(v[0]).toFixed(1)+' L'+line.split(' ').join(' L')+' L'+W+','+H+' L0,'+H+'Z';
 var gln='';[0.25,0.5,0.75].forEach(function(g){var gy=(PT+(H-PT-PB)*g).toFixed(1);gln+='<line x1="0" y1="'+gy+'" x2="'+W+'" y2="'+gy+'" stroke="var(--hairline)" stroke-width="1" vector-effect="non-scaling-stroke"/>';});
 box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:'+H+'px;display:block"><defs><linearGradient id="eg-'+which+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+col+'" stop-opacity=".22"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'+gln+'<path d="'+area+'" fill="url(#eg-'+which+')"/><polyline points="'+line+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg><div class="xh-line"></div><div class="xh-dot"></div><div class="xh-tip"><div class="tv"></div><div class="td"></div></div>';
 var svg=box.querySelector('svg'),xl=box.querySelector('.xh-line'),xd=box.querySelector('.xh-dot'),xt=box.querySelector('.xh-tip');
 xd.style.background=col;
 svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect();var ratio=(ev.clientX-r.left)/r.width;var idx=Math.max(0,Math.min(n-1,Math.round(ratio*(n-1))));var px=idx/(n-1)*r.width,py=Y(v[idx])/H*r.height;box.classList.add('on');xl.style.left=px+'px';xd.style.left=px+'px';xd.style.top=py+'px';var tx=Math.max(48,Math.min(px,r.width-48)),above=py>52;xt.style.left=tx+'px';xt.style.top=(py+(above?-10:14))+'px';xt.style.transform='translate(-50%,'+(above?'-100%':'0')+')';xt.querySelector('.tv').textContent=dfmt(v[idx]);xt.querySelector('.td').textContent=dfmtDate(ds[idx],dat.intra);setHead(which,v[idx]);});
 svg.addEventListener('mouseleave',function(){box.classList.remove('on');restoreHead(which);});
 restoreHead(which);}

// ---- Chart.js ----
function chartJS(which,dat,box){var v=dat.v,ds=dat.d,n=v.length;box.innerHTML='<canvas></canvas>';var cv=box.querySelector('canvas');
 var up=v[n-1]>=v[0],c=getCss(up?'--up':'--down');
 CHARTS[which]=new Chart(cv,{type:'line',data:{labels:ds.map(function(d){return dfmtDate(d,dat.intra);}),datasets:[{data:v,borderColor:c,backgroundColor:oklchA(c,0.12),borderWidth:2,pointRadius:0,pointHoverRadius:4,pointHoverBackgroundColor:c,fill:true,tension:.25}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{enabled:true,displayColors:false,backgroundColor:getCss('--surf4'),borderColor:getCss('--border'),borderWidth:1,titleColor:getCss('--quiet'),bodyColor:getCss('--fg'),callbacks:{title:function(it){return it[0].label;},label:function(it){return dfmt(it.parsed.y);}}}},
   scales:{x:{display:false},y:{display:false}},
   onHover:function(e,els){if(els&&els.length){setHead(which,v[els[0].index]);}else{restoreHead(which);}}}});
 cv.addEventListener('mouseleave',function(){restoreHead(which);});restoreHead(which);}

// ---- ApexCharts ----
function chartApex(which,dat,box){var v=dat.v,ds=dat.d,n=v.length;box.innerHTML='<div class="apx"></div>';var host=box.querySelector('.apx');
 var up=v[n-1]>=v[0],c=getCss(up?'--up':'--down');
 CHARTS[which]=new ApexCharts(host,{chart:{type:'area',height:CH,animations:{enabled:false},toolbar:{show:false},zoom:{enabled:false},fontFamily:'inherit',foreColor:getCss('--quiet'),
   events:{mouseMove:function(ev,ctx,cfg){var i=cfg.dataPointIndex;if(i>=0)setHead(which,v[i]);},mouseLeave:function(){restoreHead(which);}}},
  series:[{name:'Equity',data:v}],colors:[c],stroke:{width:2,curve:'smooth'},
  fill:{type:'gradient',gradient:{shadeIntensity:1,opacityFrom:.28,opacityTo:0,stops:[0,100]}},
  dataLabels:{enabled:false},
  xaxis:{categories:ds.map(function(d){return dfmtDate(d,dat.intra);}),labels:{show:false},axisBorder:{show:false},axisTicks:{show:false},tooltip:{enabled:false},crosshairs:{show:true,stroke:{color:getCss('--border-s'),width:1,dashArray:0}}},
  yaxis:{show:false},
  grid:{borderColor:getCss('--hairline'),strokeDashArray:0,xaxis:{lines:{show:false}},padding:{left:6,right:6,top:0,bottom:0}},
  tooltip:{theme:'dark',x:{show:true},y:{formatter:function(val){return dfmt(val);}},marker:{show:false}}});
 CHARTS[which].render();restoreHead(which);}

// ---- uPlot ----
function chartUplot(which,dat,box){var v=dat.v,ds=dat.d,n=v.length;box.innerHTML='';
 var up=v[n-1]>=v[0],c=getCss(up?'--up':'--down');
 var xs=v.map(function(_,i){return i;});
 var opts={width:box.clientWidth||760,height:CH,
   cursor:{x:true,y:false,points:{show:true,size:7,fill:c}},legend:{show:false},
   scales:{x:{time:false},y:{range:function(u,min,max){var p=(max-min)*0.3||1;return [min-p,max+p];}}},
   axes:[{show:false},{show:false}],
   series:[{},{stroke:c,width:2,fill:oklchA(c,0.16),points:{show:false}}],
   hooks:{setCursor:[function(u){var i=u.cursor.idx;if(i!=null)setHead(which,v[i]);else restoreHead(which);}]}};
 CHARTS[which]=new uPlot(opts,[xs,v],box);restoreHead(which);}

// guardrails — compact text, editable caps, no arc, decluttered (no subtitle)
function gcol(o){var r=Math.min(o.used/o.cap,1);return r>=0.85?'var(--down)':r>=0.6?'var(--gold)':'var(--up)';}
function gv(o,w){return o.unit==='$'?'$'+o[w]:o[w]+'%';}
function gmetric(key,label){var o=DASH.live.guards[key];return '<span class="gmetric"><span class="gl">'+label+'</span><span class="gu" style="color:'+gcol(o)+'">'+gv(o,'used')+'</span><span class="gc" onclick="editCap(event,\''+key+'\')" title="Click to edit the limit">/ '+gv(o,'cap')+'</span></span>';}
function guardStrip(){return '<div class="card dh"><div class="guard-strip"><span class="gtitle">Guardrails</span>'+gmetric('dailyLoss','Daily loss')+gmetric('maxDD','Max DD')+gmetric('exposure','Exposure')+'</div></div>';}
function editCap(ev,key){var sp=ev.currentTarget;var o=DASH.live.guards[key];var inp=document.createElement('input');inp.className='cap-in';inp.value=o.cap;
 inp.onkeydown=function(e){if(e.key==='Enter')inp.blur();if(e.key==='Escape'){inp.value=o.cap;inp.blur();}};
 inp.onblur=function(){var nn=parseFloat(inp.value);if(!isNaN(nn)&&nn>0)o.cap=nn;renderDash('live');};
 sp.replaceWith(inp);inp.focus();inp.select();}

// components
function equityBlock(which){var d=DASH[which],lab=which==='live'?'Total equity':'Paper equity';
 return '<div class="card dh" style="padding:14px 16px">'+
  '<div class="hero-top"><div><div class="hero-label">'+lab+'</div><div><span class="hero-val tab" id="hd-'+which+'">'+dfmt(d.equity)+'</span><span class="hero-delta tab up" id="dl-'+which+'">+'+dfmt(d.pnl).slice(1)+' (+'+d.pnlPct+'%)</span></div></div>'+
  '<div class="tf-seg">'+['1D','7D','30D','All'].map(function(x){return '<button'+(x==='30D'?' class="on"':'')+' onclick="setTF(\''+which+'\',\''+x+'\',this)">'+x+'</button>';}).join('')+'</div></div>'+
  '<div class="eqwrap" id="eq-'+which+'"></div>'+
  '<div class="eq-axis"><span id="ax0-'+which+'"></span><span id="ax1-'+which+'"></span></div></div>';}
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
function positions(which){var arr=DASH[which].positions||[];var p=arr.map(function(x){var cls=x.pnl[0]==='-'?'dn':'up';return '<tr><td>'+x.n+'</td><td class="muted">'+x.sym+'</td><td class="r tab">'+x.qty+'</td><td class="r tab">'+x.mark+'</td><td class="r tab '+cls+'">'+x.pnl+' '+x.pct+'</td></tr>';}).join('');
 return '<div class="card dh"><div class="card-hdr"><span class="card-lbl">Open positions</span></div><div class="card-body"><table class="mini-tbl"><thead><tr><th>Strategy</th><th>Pair</th><th class="r">Size</th><th class="r">Value</th><th class="r">P&L</th></tr></thead><tbody>'+p+'</tbody></table></div></div>';}
function grid(cols,h){return '<div class="kgrid" style="grid-template-columns:'+cols+'">'+h+'</div>';}

function renderDash(which){var live=which==='live';var kpi=live?kpiLive():kpiPaper();var kcols=live?'repeat(3,1fr)':'repeat(4,1fr)';
 var H=equityBlock(which);             // chart ALWAYS on top
 H+=grid(kcols,kpi);
 if(live)H+=guardStrip();
 H+=grid('1fr 1fr',positions(which)+tradesBox(which));   // positions | trades — paper & live alike
 document.getElementById('dash-'+which).innerHTML=H;
 SER[which]=buildSeries(which);mkChart(which,'30D');
}
renderDash('paper');renderDash('live');"""

base = html[:s] + ENGINE + html[e:]
assert "auto-halt" not in base, "auto-halt still present after rebuild"

# ── 3. neutral "medium light black" palette (less purple) ───────────────────────
NEUTRAL = [
    ("--bg:        oklch(0.155 0.017 285);", "--bg:        oklch(0.170 0.004 265);"),
    ("--surf:      oklch(0.196 0.019 286);", "--surf:      oklch(0.208 0.004 265);"),
    ("--surf2:     oklch(0.230 0.020 286);", "--surf2:     oklch(0.242 0.005 265);"),
    ("--surf3:     oklch(0.268 0.021 287);", "--surf3:     oklch(0.278 0.005 265);"),
    ("--surf4:     oklch(0.308 0.022 287);", "--surf4:     oklch(0.318 0.006 265);"),
    ("--hairline:  oklch(0.240 0.013 286);", "--hairline:  oklch(0.252 0.004 265);"),
    ("--border:    oklch(0.280 0.015 286);", "--border:    oklch(0.292 0.005 265);"),
    ("--border-s:  oklch(0.370 0.017 286);", "--border-s:  oklch(0.380 0.006 265);"),
    ("--muted:     oklch(0.68  0.014 286);", "--muted:     oklch(0.68  0.004 265);"),
    ("--quiet:     oklch(0.52  0.013 286);", "--quiet:     oklch(0.52  0.004 265);"),
    ("radial-gradient(900px 480px at 92% -8%, oklch(0.66 0.19 290 / 0.09) 0%, transparent 65%),",
     "radial-gradient(900px 480px at 92% -8%, oklch(0.5 0.01 265 / 0.05) 0%, transparent 65%),"),
]
def neutralize(doc):
    for a, b in NEUTRAL:
        assert doc.count(a) == 1, "neutral anchor missing: " + a[:30]
        doc = doc.replace(a, b, 1)
    return doc

# ── 4. CDN head injection per library ───────────────────────────────────────────
CDN = {
    "chartjs": '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>\n',
    "apex": '<script src="https://cdn.jsdelivr.net/npm/apexcharts@3.45.1/dist/apexcharts.min.js"></script>\n',
    "uplot": '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/uplot@1.6.30/dist/uPlot.min.css">\n<script src="https://cdn.jsdelivr.net/npm/uplot@1.6.30/dist/uPlot.iife.min.js"></script>\n',
}

# ── 5. emit versions ────────────────────────────────────────────────────────────
#  name                     lib       chart-h  neutral
VERSIONS = [
    ("final-A-big-svg",     "svg",     210,    False),
    ("final-B-svg",         "svg",     150,    False),
    ("final-C-neutral",     "svg",     150,    True),
    ("final-D-chartjs",     "chartjs", 150,    False),
    ("final-E-apex",        "apex",    150,    False),
    ("final-F-uplot",       "uplot",   150,    False),
]
for name, lib, ch, neutral in VERSIONS:
    out = base.replace("window.CHART_LIB='__LIB__';", "window.CHART_LIB='%s';" % lib, 1)
    out = out.replace("window.CHART_H=__CH__;", "window.CHART_H=%d;" % ch, 1)
    assert "__LIB__" not in out and "__CH__" not in out
    if lib in CDN:
        out = out.replace("</head>", CDN[lib] + "</head>", 1)
    if neutral:
        out = neutralize(out)
    pathlib.Path("mockups/%s.html" % name).write_text(out)
    print("wrote mockups/%s.html  lib=%-7s ch=%d neutral=%s  %d bytes" % (name, lib, ch, neutral, len(out)))
