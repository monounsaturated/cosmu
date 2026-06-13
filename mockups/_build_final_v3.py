#!/usr/bin/env python3
"""Round 3 — base = final-B-svg (purple, hand-SVG, 150px chart; the live dash the user liked).

Change the user asked for:
 - keep the PURPLE background (drop the neutral one).
 - put the 3 guardrails as small boxes on the SAME single row as Invested/Free/P&L
   (6 boxes in one line on Live), instead of a separate guardrails strip below.
 - explore "other key data" (fees net of the north star, drift vs paper, Sharpe, win rate).

Five versions (all purple, split layout, paper & live still mirror each other):
  g1-row      6 boxes, plain "used / cap" guard boxes
  g2-divider  6 boxes with a vertical rule grouping the 3 guardrails
  g3-bar      guard boxes get a thin used/cap progress bar (no arc)
  g4-fees     g1 + the key extra data inline: P&L shown net of fees + a "tracking paper" drift badge
  g5-rich     g3 + a compact stat strip (Fees · Sharpe · Win rate · Drift) — the maximal version
"""
import pathlib

SRC = pathlib.Path("mockups/final-B-svg.html")
html = SRC.read_text()

def repl(old, new):
    global html
    assert html.count(old) == 1, "anchor not unique/found: " + old[:60]
    html = html.replace(old, new, 1)

# ── flags ───────────────────────────────────────────────────────────────────────
repl("window.CHART_H=150;",
     "window.CHART_H=150;\nwindow.GUARD_STYLE='__GSTYLE__';   // plain | divider | bar\nwindow.EXTRA='__EXTRA__';          // none | inline | strip")
repl("var CLIB=(window.CHART_LIB||'svg'),CH=(window.CHART_H||210);",
     "var CLIB=(window.CHART_LIB||'svg'),CH=(window.CHART_H||210);\nvar GSTYLE=(window.GUARD_STYLE||'plain'),EXTRA=(window.EXTRA||'none');")

# ── DASH.live: add the extra key-data fields ─────────────────────────────────────
repl(" live:{equity:9419,invested:1700,free:7300,pnl:419,pnlPct:21,days:18,",
     " live:{equity:9419,invested:1700,free:7300,pnl:419,pnlPct:21,days:18,feesLife:3,sharpe:1.6,winRate:64,nTrades:14,drift:'tracking',")

# ── guardrails as small boxes on the KPI row (replace guardStrip) ────────────────
OLD_GUARD = "function guardStrip(){return '<div class=\"card dh\"><div class=\"guard-strip\"><span class=\"gtitle\">Guardrails</span>'+gmetric('dailyLoss','Daily loss')+gmetric('maxDD','Max DD')+gmetric('exposure','Exposure')+'</div></div>';}"
NEW_GUARD = r"""function guardBox(key,label){var o=DASH.live.guards[key],col=gcol(o),r=Math.min(o.used/o.cap,1);
 var cap='<span class="gm-cap" onclick="editCap(event,\''+key+'\')" title="Click to edit the limit">/ '+gv(o,'cap')+'</span>';
 var bar=GSTYLE==='bar'?'<div class="gm-bar"><div class="gm-fill" style="width:'+(r*100).toFixed(0)+'%;background:'+col+'"></div></div>':'';
 return '<div class="kpi-box guard-mini"><div class="kpi-label">'+label+'</div><div class="gm-val"><span style="color:'+col+'">'+gv(o,'used')+'</span> '+cap+'</div>'+bar+'</div>';}
function guardKpiRow(){var k=kpiLive();var g=guardBox('dailyLoss','Daily loss')+guardBox('maxDD','Max DD')+guardBox('exposure','Exposure');
 if(GSTYLE==='divider')return '<div class="kgrid kpi-guard" style="grid-template-columns:repeat(3,1.05fr) 1px repeat(3,0.92fr)">'+k+'<div class="vrule"></div>'+g+'</div>';
 return '<div class="kgrid kpi-guard" style="grid-template-columns:repeat(3,1.05fr) repeat(3,0.92fr)">'+k+g+'</div>';}
function statBox(label,val,sub){return '<div class="ls"><div class="ls-label">'+label+'</div><div class="ls-val tab">'+val+'</div><div class="ls-sub">'+sub+'</div></div>';}
function statStripLive(){var d=DASH.live;return '<div class="card dh"><div class="livestat">'+
 statBox('Fees paid',dfmt(d.feesLife),'lifetime · live')+
 statBox('Sharpe',d.sharpe.toFixed(1),'annualized · live')+
 statBox('Win rate',d.winRate+'%',d.nTrades+' trades')+
 statBox('Drift','<span class="up">tracking</span>','vs paper expectation')+
 '</div></div>';}"""
repl(OLD_GUARD, NEW_GUARD)

# ── kpiLive: EXTRA-aware P&L sub (net of fees) ───────────────────────────────────
OLD_KPILIVE = """function kpiLive(){var d=DASH.live,tot=d.invested+d.free;
 return kbox('Invested',dfmt(d.invested),Math.round(d.invested/tot*100)+'% of capital · 1 strategy','')+
  kbox('Free',dfmt(d.free),Math.round(d.free/tot*100)+'% idle','')+
  kbox('P&L','+'+dfmt(d.pnl).slice(1),'+'+d.pnlPct+'% · '+d.days+'d live','up');}"""
NEW_KPILIVE = """function kpiLive(){var d=DASH.live,tot=d.invested+d.free;
 var psub=EXTRA==='none'?('+'+d.pnlPct+'% · '+d.days+'d live'):('+'+d.pnlPct+'% · net of '+dfmt(d.feesLife)+' fees');
 return kbox('Invested',dfmt(d.invested),Math.round(d.invested/tot*100)+'% of capital · 1 strategy','')+
  kbox('Free',dfmt(d.free),Math.round(d.free/tot*100)+'% idle','')+
  kbox('P&L','+'+dfmt(d.pnl).slice(1),psub,'up');}"""
repl(OLD_KPILIVE, NEW_KPILIVE)

# ── equityBlock: drift badge next to the delta (live + extra) ────────────────────
OLD_EQ = """  '<div class="hero-top"><div><div class="hero-label">'+lab+'</div><div><span class="hero-val tab" id="hd-'+which+'">'+dfmt(d.equity)+'</span><span class="hero-delta tab up" id="dl-'+which+'">+'+dfmt(d.pnl).slice(1)+' (+'+d.pnlPct+'%)</span></div></div>'+"""
NEW_EQ = """  '<div class="hero-top"><div><div class="hero-label">'+lab+'</div><div><span class="hero-val tab" id="hd-'+which+'">'+dfmt(d.equity)+'</span><span class="hero-delta tab up" id="dl-'+which+'">+'+dfmt(d.pnl).slice(1)+' (+'+d.pnlPct+'%)</span>'+((which==='live'&&EXTRA!=='none')?'<span class="drift-badge ok">tracking paper</span>':'')+'</div></div>'+"""
repl(OLD_EQ, NEW_EQ)

# ── renderDash: guardrails fold into the KPI row on live ─────────────────────────
OLD_RENDER = """function renderDash(which){var live=which==='live';var kpi=live?kpiLive():kpiPaper();var kcols=live?'repeat(3,1fr)':'repeat(4,1fr)';
 var H=equityBlock(which);             // chart ALWAYS on top
 H+=grid(kcols,kpi);
 if(live)H+=guardStrip();
 H+=grid('1fr 1fr',positions(which)+tradesBox(which));   // positions | trades — paper & live alike
 document.getElementById('dash-'+which).innerHTML=H;
 SER[which]=buildSeries(which);mkChart(which,'30D');
}"""
NEW_RENDER = """function renderDash(which){var live=which==='live';
 var H=equityBlock(which);             // chart ALWAYS on top
 if(live){H+=guardKpiRow();if(EXTRA==='strip')H+=statStripLive();}   // 3 KPIs + 3 guard boxes, one line
 else{H+=grid('repeat(4,1fr)',kpiPaper());}
 H+=grid('1fr 1fr',positions(which)+tradesBox(which));   // positions | trades — paper & live alike
 document.getElementById('dash-'+which).innerHTML=H;
 SER[which]=buildSeries(which);mkChart(which,'30D');
}"""
repl(OLD_RENDER, NEW_RENDER)

# ── CSS for the new pieces ───────────────────────────────────────────────────────
CSS = """
/* ── guardrails folded into the KPI row (small boxes) ── */
.kpi-guard .guard-mini{display:flex;flex-direction:column;justify-content:center}
.kpi-guard .guard-mini .kpi-label{margin-bottom:5px}
.gm-val{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.gm-cap{font-size:11px;color:var(--quiet);font-weight:400;cursor:pointer;border-bottom:1px dashed transparent;white-space:nowrap}
.gm-cap:hover{color:var(--muted);border-bottom-color:var(--border-s)}
.gm-bar{height:3px;border-radius:2px;background:var(--surf3);margin-top:8px;overflow:hidden}
.gm-fill{height:100%;border-radius:2px}
.vrule{background:var(--hairline);align-self:stretch;width:1px;margin:3px 0;justify-self:center}
.drift-badge{font-size:9.5px;font-weight:600;padding:2px 8px 2px 7px;border-radius:20px;margin-left:9px;display:inline-flex;align-items:center;gap:5px;vertical-align:middle}
.drift-badge.ok{background:var(--up-dim);color:var(--up)}
.drift-badge.ok::before{content:"";width:5px;height:5px;border-radius:50%;background:var(--up)}
.livestat{display:flex;padding:11px 16px}
.livestat .ls{flex:1;padding:0 16px;border-left:1px solid var(--hairline)}
.livestat .ls:first-child{border-left:none;padding-left:0}
.ls-label{font-size:9px;text-transform:uppercase;letter-spacing:.09em;color:var(--quiet);font-weight:700;margin-bottom:3px}
.ls-val{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.ls-sub{font-size:9.5px;color:var(--quiet);margin-top:1px}
"""
repl("\n</style>", CSS + "\n</style>")

assert "__GSTYLE__" in html and "__EXTRA__" in html
base = html

# ── emit versions ────────────────────────────────────────────────────────────────
#  name                 GSTYLE     EXTRA
VERSIONS = [
    ("final-g1-row",     "plain",   "none"),
    ("final-g2-divider", "divider", "none"),
    ("final-g3-bar",     "bar",     "none"),
    ("final-g4-fees",    "plain",   "inline"),
    ("final-g5-rich",    "bar",     "strip"),
]
for name, gstyle, extra in VERSIONS:
    out = base.replace("__GSTYLE__", gstyle).replace("__EXTRA__", extra)
    assert "__GSTYLE__" not in out and "__EXTRA__" not in out
    pathlib.Path("mockups/%s.html" % name).write_text(out)
    print("wrote mockups/%s.html  guard=%-8s extra=%-7s  %d bytes" % (name, gstyle, extra, len(out)))
