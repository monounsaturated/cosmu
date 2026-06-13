#!/usr/bin/env python3
"""Add a coherent, view-only Services page INSIDE the full app (cosmu-final-v12) — reusing the
app's own cards / mini-tbl / badges / tokens — and emit 5 complete builds that differ only in the
Services-page microcopy + layout. Output: mockups/cosmu-v12-{services,apis,connections,integrations,keys}.html
"""
import pathlib

V12 = pathlib.Path("mockups/cosmu-final-v12.html").read_text()
THEME_BTN = ('<button class="theme-btn" style="margin-left:auto" onclick="toggleTheme()" title="Light / dark mode" aria-label="Toggle theme">'
 '<svg class="ic-moon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'
 '<svg class="ic-sun" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>')

# ── CSS (token-based, sits on top of the app's classes) ──────────────────────────
CSS = """
/* ── Services page (view-only key index) ── */
.svc-sum{display:flex;gap:13px;align-items:center;margin-left:14px}
.svc-sum span{font-size:11px;color:var(--quiet);font-variant-numeric:tabular-nums}
.svc-banner{font-size:11px;color:var(--quiet);background:var(--surf);border:1px solid var(--hairline);border-radius:var(--r-sm);padding:9px 13px;margin-bottom:var(--gap)}
.svc-banner strong{color:var(--muted)}.svc-banner code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--iris-s);font-size:10.5px}
.svc-dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex-shrink:0}
.svc-pill{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-weight:600;padding:2px 9px;border-radius:999px;white-space:nowrap}
.svc-host{font-size:9.5px;color:var(--muted);background:var(--surf3);border:1px solid var(--hairline);border-radius:5px;padding:1px 7px;white-space:nowrap}
.svc-cat-tag{font-size:9px;color:var(--iris-s);background:var(--iris-dim);border-radius:5px;padding:1px 7px}
.svc-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px;color:var(--quiet)}
.svc-note{font-size:10.5px;color:var(--gold);margin-top:7px}
.svc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--gap);margin-bottom:var(--gap)}
.svc-card-top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}
.svc-card-pow{font-size:11.5px;color:var(--muted);line-height:1.4;margin-bottom:9px}
.svc-card-meta{display:flex;gap:6px;margin-bottom:8px}
.svc-cat-name{font-size:9.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--quiet);font-weight:700;margin:16px 2px 7px}
.svc-cat-name:first-child{margin-top:2px}
.svc-cat-row{display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--surf2);border:1px solid var(--hairline);border-radius:var(--r-sm);padding:11px 14px;margin-bottom:6px;box-shadow:var(--cell-shadow)}
.svc-cat-r{display:flex;align-items:center;gap:11px}
.svc-sw{width:30px;height:17px;border-radius:999px;background:var(--surf4);position:relative;flex-shrink:0}
.svc-sw .vk{position:absolute;top:2px;left:2px;width:13px;height:13px;border-radius:50%;background:var(--quiet)}
.svc-sw.v-live{background:var(--up-dim)}.svc-sw.v-live .vk{left:15px;background:var(--up)}
.svc-sw.v-error{background:var(--down-dim)}.svc-sw.v-error .vk{left:15px;background:var(--down)}
.svc-sw.v-pending{background:var(--gold-dim)}.svc-sw.v-pending .vk{left:15px;background:var(--gold)}
.svc-env{background:color-mix(in oklab,var(--bg) 78%,#000);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;box-shadow:var(--cell-shadow)}
.svc-env-top{color:var(--quiet);font-size:10.5px;margin-bottom:9px}
.svc-env-line{display:flex;align-items:center;gap:9px;padding:3.5px 0;white-space:nowrap;overflow:hidden}
.svc-env-key{color:var(--iris-s)}.svc-env-eq{color:var(--quiet)}.svc-env-val{color:var(--up)}.svc-env-empty{color:var(--down)}.svc-env-note{color:var(--muted)}
.svc-env-where{margin-left:auto;color:var(--quiet);font-size:10px}
#page-services .mini-tbl td{padding:9px 4px}#page-services .mini-tbl th{padding:0 4px 7px}
@media(max-width:880px){.svc-grid{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.svc-grid{grid-template-columns:1fr}}
"""

# ── JS (data + renders, reusing the app's coherent classes) ──────────────────────
SVC_JS = r"""
// ── Services page (view-only .env index) ──
var SVC=[
 {name:'Binance',cat:'Trading',powers:'Spot market data + live execution',host:'Railway',vars:['BINANCE_API_KEY','BINANCE_API_SECRET'],status:'live',note:'live trading stays OFF until armed'},
 {name:'Alpaca',cat:'Data',powers:'US-equities data + paper fills',host:'Railway',vars:['ALPACA_API_KEY','ALPACA_API_SECRET','ALPACA_PAPER_API_KEY'],status:'off',note:'paper keys not set — equity lane keyless (Yahoo) for now'},
 {name:'Supabase · Postgres',cat:'Infra',powers:'The store — strategies, tracks, fills, marks',host:'Railway · Supabase',vars:['DATABASE_URL'],status:'live'},
 {name:'Cloudflare R2',cat:'Infra',powers:'Cold data lake (Parquet hoard)',host:'Railway',vars:['R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET'],status:'off',note:'cold tier default-off — flip ALT_DATA_BACKEND when set'},
 {name:'OpenRouter',cat:'AI',powers:'LLM strategy authoring',host:'Railway',vars:['OPENROUTER_API_KEY'],status:'live'},
 {name:'xAI · Grok',cat:'Data',powers:'LiveSearch — tweets / news accrual',host:'Railway',vars:['XAI_API_KEY'],status:'error',note:'last call 401 — rotate the key'},
 {name:'LunarCrush',cat:'Data',powers:'Social-dominance signal',host:'Railway',vars:['LUNARCRUSH_API_KEY'],status:'off'},
 {name:'FRED',cat:'Data',powers:'Macro — VIX, rates',host:'Railway',vars:['FRED_API_KEY'],status:'live'},
 {name:'CryptoPanic',cat:'Data',powers:'News headlines',host:'Railway',vars:['CRYPTOPANIC_API_KEY'],status:'pending',note:'key set — not verified live yet'},
 {name:'DeFiLlama',cat:'Data',powers:'TVL / on-chain flows',host:'— (keyless)',vars:['(no key — public API)'],status:'live'},
 {name:'Slack',cat:'Notify',powers:'Alerts + daily summary',host:'Railway',vars:['SLACK_WEBHOOK_URL'],status:'live'},
 {name:'Railway',cat:'Infra',powers:'Engine + cron hosting',host:'Railway',vars:['(project-linked)'],status:'live'},
 {name:'Vercel',cat:'Infra',powers:'Web-app hosting',host:'Vercel',vars:['(project-linked)'],status:'live'}
];
var SVCST={live:{lbl:'Live',c:'var(--up)',bg:'var(--up-dim)'},off:{lbl:'Not set',c:'var(--quiet)',bg:'var(--surf3)'},error:{lbl:'Error',c:'var(--down)',bg:'var(--down-dim)'},pending:{lbl:'Set · unverified',c:'var(--gold)',bg:'var(--gold-dim)'}};
function svcDot(s){return '<span class="svc-dot" style="background:'+SVCST[s].c+'"></span>';}
function svcPill(s){var m=SVCST[s];return '<span class="svc-pill" style="color:'+m.c+';background:'+m.bg+'">'+svcDot(s)+m.lbl+'</span>';}
function svcCount(s){return SVC.filter(function(x){return x.status===s;}).length;}
function svcTable(){return '<div class="card"><div class="card-hdr"><span class="card-lbl">All services · '+SVC.length+'</span></div><div class="card-body"><table class="mini-tbl" style="font-size:12px"><thead><tr><th style="width:14px"></th><th>Service</th><th>Powers</th><th>Set in</th><th>Env var</th><th class="r">Status</th></tr></thead><tbody>'+SVC.map(function(s){return '<tr><td>'+svcDot(s.status)+'</td><td style="font-weight:600">'+s.name+'</td><td class="muted">'+s.powers+'</td><td><span class="svc-host">'+s.host+'</span></td><td class="svc-mono">'+s.vars.join(', ')+'</td><td class="r">'+svcPill(s.status)+'</td></tr>';}).join('')+'</tbody></table></div></div>';}
function svcCards(){return '<div class="svc-grid">'+SVC.map(function(s){return '<div class="card" style="padding:13px 14px"><div class="svc-card-top"><span style="font-weight:600">'+s.name+'</span>'+svcPill(s.status)+'</div><div class="svc-card-pow">'+s.powers+'</div><div class="svc-card-meta"><span class="svc-host">'+s.host+'</span><span class="svc-cat-tag">'+s.cat+'</span></div><div class="svc-mono" style="word-break:break-all">'+s.vars.join('  ·  ')+'</div>'+(s.note?'<div class="svc-note">'+s.note+'</div>':'')+'</div>';}).join('')+'</div>';}
function svcGroups(){var hosts={},order=[];SVC.forEach(function(s){if(!hosts[s.host]){hosts[s.host]=[];order.push(s.host);}hosts[s.host].push(s);});return order.map(function(h){return '<div class="card" style="margin-bottom:var(--gap)"><div class="card-hdr"><span class="card-lbl">'+h+'</span><span class="muted" style="font-size:10px">set these here · '+hosts[h].length+'</span></div><div class="card-body" style="padding-top:4px">'+hosts[h].map(function(s){return '<div style="display:grid;grid-template-columns:8px 1.1fr 1.6fr auto;align-items:center;gap:11px;padding:8px 0;border-bottom:1px solid var(--hairline)">'+svcDot(s.status)+'<span style="font-weight:600">'+s.name+'</span><span class="muted" style="font-size:11.5px">'+s.powers+' · <span class="svc-mono">'+s.vars.join(', ')+'</span></span>'+svcPill(s.status)+'</div>';}).join('')+'</div></div>';}).join('');}
function svcCats(){var cats={},order=['Trading','Data','AI','Infra','Notify'];SVC.forEach(function(s){(cats[s.cat]=cats[s.cat]||[]).push(s);});return order.filter(function(c){return cats[c];}).map(function(c){return '<div class="svc-cat-name">'+c+'</div>'+cats[c].map(function(s){return '<div class="svc-cat-row"><div><div style="font-weight:600">'+s.name+'</div><div class="muted" style="font-size:11px;margin-top:1px">'+s.powers+' · <span class="svc-mono">'+s.vars.join(', ')+'</span></div></div><div class="svc-cat-r"><span class="svc-host">'+s.host+'</span><span class="svc-sw v-'+s.status+'" title="'+SVCST[s.status].lbl+' · view-only"><span class="vk"></span></span></div></div>';}).join('');}).join('');}
function svcEnv(){var lines=SVC.map(function(s){return s.vars.map(function(v){var key=v.indexOf('(')===0;var val=key?'<span class="svc-env-note">'+v+'</span>':(s.status==='off'?'<span class="svc-env-empty"># unset</span>':'<span class="svc-env-val">••••••••••••••••</span>');return '<div class="svc-env-line">'+svcDot(s.status)+'<span class="svc-env-key">'+(key?s.name:v)+'</span><span class="svc-env-eq">'+(key?'':'=')+'</span>'+val+'<span class="svc-env-where">→ '+s.host+'</span></div>';}).join('');}).join('');return '<div class="svc-env"><div class="svc-env-top"># .env.local — view-only index · '+SVC.length+' services · values masked</div>'+lines+'</div>';}
function renderServices(){
  var m=document.getElementById('services-mount');if(!m)return;
  m.innerHTML=({table:svcTable,cards:svcCards,groups:svcGroups,cats:svcCats,env:svcEnv})['__MODE__']();
  var sm=document.getElementById('svc-sum');if(sm)sm.innerHTML='<span><b style="color:var(--up)">'+svcCount('live')+'</b> live</span><span><b style="color:var(--gold)">'+svcCount('pending')+'</b> unverified</span><span><b style="color:var(--down)">'+svcCount('error')+'</b> error</span><span><b style="color:var(--quiet)">'+svcCount('off')+'</b> not set</span>';
}
renderServices();
"""

NAV_ICON = '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"><circle cx="4.6" cy="4.6" r="2.4"/><path d="M6.3 6.3l6 6M10.4 12.4l1.8-1.8M9.2 13.6l1.8-1.8"/></svg>'

#  file-name           nav-label      page-title                 banner
VERSIONS = [
 ("cosmu-v12-services","table","Services","Services","<strong>View only.</strong> Every key the machine uses — connected or not, and where to set it. Add vars in <code>.env.local</code> (local) · <code>Railway</code> (engine) · <code>Vercel</code> (web)."),
 ("cosmu-v12-apis","cards","APIs","APIs &amp; keys","<strong>Read-only.</strong> Green = live · grey = not set · amber = set-but-unverified · red = failing. No secret values are shown."),
 ("cosmu-v12-connections","groups","Connections","Connections","<strong>View only.</strong> Grouped by where you set them — open that project, add the var, it goes live here."),
 ("cosmu-v12-integrations","cats","Integrations","Integrations","<strong>View only.</strong> The coloured switch is <strong>status, not a control</strong>. Set keys in Railway · Vercel · Supabase · Cloudflare."),
 ("cosmu-v12-keys","env","Keys","Environment · keys","<strong>View only.</strong> The literal <code>.env</code> index — values masked. <code>→ host</code> tells you where to add each key."),
]

for fname, mode, navlabel, title, banner in VERSIONS:
    h = V12
    # 1. nav item (after Commands, before </nav>)
    h = h.replace("    </button>\n  </nav>",
        "    </button>\n    <button class=\"nav-item\" onclick=\"nav('services')\" id=\"nav-services\">\n      <span class=\"nav-left\">\n        "+NAV_ICON+"\n        "+navlabel+"\n      </span>\n    </button>\n  </nav>", 1)
    # 2. page (before /main)
    page = ('  <!-- SERVICES PAGE -->\n  <div class="page" id="page-services">\n'
            '    <div class="toolbar-row"><span class="page-title">'+title+'</span><div class="svc-sum" id="svc-sum"></div>'+THEME_BTN+'</div>\n'
            '    <div class="svc-banner">'+banner+'</div>\n'
            '    <div id="services-mount"></div>\n  </div>\n\n')
    h = h.replace("\n</div><!-- /main -->", "\n"+page+"</div><!-- /main -->", 1)
    # 3. JS (before the last </script>)
    js = SVC_JS.replace("__MODE__", mode)
    idx = h.rfind("</script>")
    h = h[:idx] + js + "\n" + h[idx:]
    # 4. CSS (before </style>)
    h = h.replace("\n</style>", CSS + "\n</style>", 1)
    pathlib.Path("mockups/"+fname+".html").write_text(h)
    print("wrote mockups/"+fname+".html  ("+mode+", nav='"+navlabel+"')  "+str(len(h))+" bytes")
