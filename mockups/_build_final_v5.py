#!/usr/bin/env python3
"""Final polish — base = cosmu-final-v3. Emits 2 near-identical finals (differ only in
sidebar width) with this batch of tweaks:
 - paper dashboard: 'Tracks' -> 'Strategies' (KPI + paper-stop modal + live-modal mention)
 - sidebar a touch narrower (the A/B variable: 190px vs 184px)
 - costs chart now fills its box (preserveAspectRatio=none — was letterboxed/centered)
 - Commands ranked most-used/impactful -> rare
 - fixed the right-side shade on every page: the off-screen side panel's left-shadow was
   bleeding onto the viewport edge; shadow now only applies when the panel is open
 - sidebar engine status -> a real On/Off button: green 'On', red 'Off', amber 'Issue'
   (hover shows the error), click cycles; collapsed shows only the coloured dot
"""
import pathlib

html = pathlib.Path("mockups/cosmu-final-v3.html").read_text()

def repl(old, new, n=1):
    global html
    c = html.count(old)
    assert c == n, f"expected {n} of [{old[:55]!r}], found {c}"
    html = html.replace(old, new)

# ── paper 'Tracks' -> 'Strategies' ───────────────────────────────────────────────
repl("kbox('Tracks',d.tracks,'running','')", "kbox('Strategies',d.tracks,'running','')")
repl("<div class=\"modal-title\">Stop all paper tracks</div>",
     "<div class=\"modal-title\">Stop all paper strategies</div>")
repl("Halt every running paper track and close their simulated positions. <strong>No real money is involved</strong> — this only stops the simulations and frees their virtual capital. Each track <strong>keeps its stats</strong>",
     "Halt every running paper strategy and close their simulated positions. <strong>No real money is involved</strong> — this only stops the simulations and frees their virtual capital. Each one <strong>keeps its stats</strong>")
repl(">Stop paper tracks</button>", ">Stop paper strategies</button>")
repl("Paper tracks are not affected.", "Paper strategies are not affected.")

# ── costs chart fills its box (was centered/letterboxed) ─────────────────────────
repl("'<svg viewBox=\"0 0 '+W+' '+H+'\" width=\"100%\" height=\"'+H+'\" style=\"display:block\">'",
     "'<svg viewBox=\"0 0 '+W+' '+H+'\" preserveAspectRatio=\"none\" width=\"100%\" height=\"'+H+'\" style=\"display:block\">'")

# ── right-side shade: panel shadow only when open ────────────────────────────────
repl("  box-shadow:-16px 0 48px -8px rgba(0,0,0,.80);\n  display:flex;flex-direction:column;",
     "  display:flex;flex-direction:column;")
repl(".side-panel.open{transform:translateX(0)}",
     ".side-panel.open{transform:translateX(0);box-shadow:-16px 0 48px -8px rgba(0,0,0,.55)}")

# ── Commands ranked: most used / impactful -> rare ───────────────────────────────
OLD_CMDS = """        <div class="cmd-row"><span class="cmd-name">cosmu gate run</span><span class="cmd-desc">Run the Gate on all queued strategies in inbox/</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu paper start &lt;id&gt;</span><span class="cmd-desc">Start a paper track for a gate-passed strategy</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu paper stop &lt;id&gt;</span><span class="cmd-desc">Stop a paper track (keeps history)</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu live launch &lt;id&gt;</span><span class="cmd-desc">Fund and arm a paper strategy for live trading</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu live liquidate</span><span class="cmd-desc">Market-sell all live positions to USDC and disarm</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu data fetch</span><span class="cmd-desc">Backfill and refresh all data sources</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu strategy list</span><span class="cmd-desc">Print all strategies with stage and key metrics</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu strategy inspect &lt;id&gt;</span><span class="cmd-desc">Show full spec and metrics for a strategy</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu verify</span><span class="cmd-desc">Run pnpm verify (lint + types + tests) — pre-push gate</span></div>"""
NEW_CMDS = """        <div class="cmd-row"><span class="cmd-name">cosmu strategy list</span><span class="cmd-desc">Print all strategies with stage and key metrics — your at-a-glance status</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu gate run</span><span class="cmd-desc">Run the Gate on all queued strategies in inbox/ — the core loop</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu live launch &lt;id&gt;</span><span class="cmd-desc">Fund and arm a paper strategy for live trading — real money</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu live liquidate</span><span class="cmd-desc">Market-sell all live positions to USDC and disarm — the safety lever</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu paper start &lt;id&gt;</span><span class="cmd-desc">Start paper trading for a gate-passed strategy</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu strategy inspect &lt;id&gt;</span><span class="cmd-desc">Show full spec and metrics for a strategy</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu paper stop &lt;id&gt;</span><span class="cmd-desc">Stop a strategy's paper run (keeps history)</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu data fetch</span><span class="cmd-desc">Backfill and refresh all data sources — periodic maintenance</span></div>
        <div class="cmd-row"><span class="cmd-name">cosmu verify</span><span class="cmd-desc">Run pnpm verify (lint + types + tests) — pre-push gate, dev only</span></div>"""
repl(OLD_CMDS, NEW_CMDS)

# ── sidebar engine status -> On/Off button ───────────────────────────────────────
repl('<div class="sb-alive" data-tip="Engine running — executor ticked today 22:10 UTC, marks 38 min old. This dot turns amber if a heartbeat goes stale."><span class="alive-dot"></span><span>running</span></div>',
     '<button class="sb-power on" id="sb-power" onclick="togglePower()" data-tip="Engine On — executor ticked today 22:10 UTC, marks 38 min old."><span class="power-dot"></span><span class="power-lbl">On</span></button>')

repl("if(location.hash)nav(location.hash.replace('#/',''));",
"""if(location.hash)nav(location.hash.replace('#/',''));

// engine On/Off button (green On · red Off · amber Issue w/ error on hover)
var PWR=['on','warn','off'];
var PWR_I={on:{l:'On',t:'Engine On — executor ticked today 22:10 UTC, marks 38 min old.'},warn:{l:'Issue',t:'Heartbeat stale — last executor tick ~3h ago. Marks may be outdated; check the engine logs before trusting live numbers.'},off:{l:'Off',t:'Engine Off — autonomy paused. Nothing is trading or marking.'}};
var pwrI=0;
function togglePower(){pwrI=(pwrI+1)%PWR.length;var s=PWR[pwrI],el=document.getElementById('sb-power');if(!el)return;el.className='sb-power '+s;el.setAttribute('data-tip',PWR_I[s].t);el.querySelector('.power-lbl').textContent=PWR_I[s].l;}""")

CSS = """
/* ── sidebar engine On/Off button ── */
.sb-power{display:flex;align-items:center;gap:7px;width:100%;padding:6px 10px;font-size:10.5px;font-weight:600;font-family:inherit;color:var(--fg);background:transparent;border:1px solid var(--border);border-radius:var(--r-xs);cursor:pointer;transition:all var(--tr)}
.sb-power:hover{background:var(--surf2)}
.power-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;transition:all var(--tr)}
.sb-power.on{color:var(--up);border-color:oklch(0.78 0.16 160 / 0.30)}
.sb-power.on .power-dot{background:var(--up);box-shadow:0 0 0 3px var(--up-dim);animation:alive-p 2.4s ease-in-out infinite}
.sb-power.warn{color:var(--gold);border-color:oklch(0.82 0.14 85 / 0.32)}
.sb-power.warn .power-dot{background:var(--gold);box-shadow:0 0 0 3px var(--gold-dim)}
.sb-power.off{color:var(--down);border-color:oklch(0.70 0.17 18 / 0.30)}
.sb-power.off .power-dot{background:var(--down);box-shadow:0 0 0 3px var(--down-dim)}
body.sb-collapsed .sb-power{justify-content:center;gap:0;padding:6px;border-color:transparent;background:transparent}
body.sb-collapsed .sb-power .power-lbl{display:none}
"""
repl("\n</style>", CSS + "\n</style>")

# ── emit 2 finals: only the sidebar width differs ────────────────────────────────
assert html.count("  --sidebar-w: 206px;") == 1
for name, w in [("cosmu-final-v4a", 190), ("cosmu-final-v4b", 184)]:
    out = html.replace("  --sidebar-w: 206px;", "  --sidebar-w: %dpx;" % w, 1)
    pathlib.Path("mockups/%s.html" % name).write_text(out)
    print("wrote mockups/%s.html  sidebar=%dpx  %d bytes" % (name, w, len(out)))
