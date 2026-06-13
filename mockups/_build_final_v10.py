#!/usr/bin/env python3
"""Final v10 — base = cosmu-final-v9. Output: cosmu-final-v10.html
 - sidebar order: Live · Paper · Strategies · Costs · Commands
 - default landing = Live
 - responsive sidebar fix: when it collapses on a narrow/half window it now hides the nav
   LABELS (not just the brand) — the cause of the clipped "Strateg…"/"Comma…" text
 - strat-sheet side panel a bit wider (720px / 54vw)
 - default view a touch more zoomed in (zoom:1.05; heights + tooltip clamp adjusted by /1.05)
"""
import pathlib

html = pathlib.Path("mockups/cosmu-final-v9.html").read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:55]!r}], found {c}"
    html = html.replace(old, new)

def cut(start, end_marker, new):
    global html
    a = html.index(start); b = html.index(end_marker, a)
    html = html[:a] + new + html[b:]

# ── zoom-safe heights first (5x 100vh -> /1.05), then add the zoom ──────────────
repl("100vh", "calc(100vh/1.05)", n=5)
repl("  font-size:13px;\n}", "  font-size:13px;\n  zoom:1.05;\n}")
repl("window.innerWidth-tw-8", "window.innerWidth/1.05-tw-8")
repl("window.innerHeight-th-8", "window.innerHeight/1.05-th-8")

# ── wider strat-sheet panel ──────────────────────────────────────────────────────
repl("--panel-w:   640px;", "--panel-w:   720px;")
repl("width:var(--panel-w);max-width:50vw;", "width:var(--panel-w);max-width:54vw;")

# ── sidebar order: Live · Paper · Strategies · Costs · Commands (Live active) ────
cut('    <button class="nav-item" onclick="nav(\'live\')" id="nav-live">', '\n  </nav>',
"""    <button class="nav-item active" onclick="nav('live')" id="nav-live">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 7.5h2.6l1.4-3 2.2 6 1.4-3h3.4"/></svg>
        Live
      </span>
      <span class="nav-count">1</span>
    </button>
    <button class="nav-item" onclick="nav('paper')" id="nav-paper">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="2.6" width="9" height="10.8" rx="1.6"/><rect x="5.4" y="1.5" width="4.2" height="2.3" rx="0.8"/><line x1="5.5" y1="7" x2="9.5" y2="7"/><line x1="5.5" y1="9.5" x2="9.5" y2="9.5"/></svg>
        Paper
      </span>
      <span class="nav-count">4</span>
    </button>
    <button class="nav-item" onclick="nav('strategies')" id="nav-strategies">
      <span class="nav-left">
        <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round"><circle cx="3.2" cy="4" r="1.1" fill="currentColor" stroke="none"/><line x1="6.2" y1="4" x2="13" y2="4"/><circle cx="3.2" cy="7.5" r="1.1" fill="currentColor" stroke="none"/><line x1="6.2" y1="7.5" x2="13" y2="7.5"/><circle cx="3.2" cy="11" r="1.1" fill="currentColor" stroke="none"/><line x1="6.2" y1="11" x2="13" y2="11"/></svg>
        Strategies
      </span>
      <span class="nav-count">12</span>
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

# ── default landing = Live ───────────────────────────────────────────────────────
repl('<div class="page active" id="page-strategies">', '<div class="page" id="page-strategies">')
repl('<div class="page" id="page-live">', '<div class="page active" id="page-live">')

# ── responsive: proper sidebar collapse (hide nav LABELS) + grid stacking ────────
repl(""".dash-split{align-items:start}
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
}""",
""".dash-split{align-items:start}
@media (max-width:1100px){ .dash-split{grid-template-columns:1fr!important} }
@media (max-width:880px){
  /* collapse the sidebar to icons — hide the nav LABELS, not just the brand */
  :root{--sidebar-w:60px}
  .sb-text,.nav-count{display:none}
  .nav-left{font-size:0;gap:0}
  .nav-left svg{width:17px;height:17px}
  .nav-item{justify-content:center;width:44px;margin:1px auto;padding:7px 0}
  .sb-tog{display:none}
  .sb-logo{justify-content:center;padding:0}
  .sb-power,.sb-dot-wrap{justify-content:center;gap:0}
  .sb-power .power-lbl{display:none}
  .kgrid,.kpi-grid,.cat-tiles,.money-band,.kpi-guard{grid-template-columns:repeat(2,1fr)!important}
  .dash-split{grid-template-columns:1fr!important}
  .summary-ribbon{flex-wrap:wrap;height:auto;row-gap:6px}
  .side-panel{max-width:94vw}
}
@media (max-width:520px){
  .kgrid,.kpi-grid,.cat-tiles,.money-band,.stat-strip,.kpi-guard,.dash-split{grid-template-columns:1fr!important}
}""")

pathlib.Path("mockups/cosmu-final-v10.html").write_text(html)
print("wrote mockups/cosmu-final-v10.html", len(html), "bytes")
