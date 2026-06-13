#!/usr/bin/env python3
"""Branding exploration — name + accent-colour variants of the chosen design (cp1 base).
Swaps: logo name, <title>, CLI prefix, domain, logo-mark gradient, the iris accent family
(both the var tokens and the 9 inline literals), and retints the dark base to the brand hue.
Semantic colours (up/down/gold) are left intact.
"""
import pathlib

BASE = pathlib.Path("mockups/cosmu-final-v6-cp1.html").read_text()

# color spec: acc "L C H", accS "L C H", logo hi/lo hex, base hue, base chroma, darken
COLORS = {
    "green":     {"acc":"0.70 0.15 150", "accS":"0.79 0.11 150", "hi":"#3ddc84","lo":"#10984f","bh":155,"bc":0.012,"dk":0.0,  "lbl":"green"},
    "orange":    {"acc":"0.72 0.16 58",  "accS":"0.81 0.12 62",  "hi":"#ffb24d","lo":"#e07b1a","bh":60, "bc":0.012,"dk":0.0,  "lbl":"orange"},
    "bloomberg": {"acc":"0.63 0.10 242", "accS":"0.75 0.08 242", "hi":"#5b9bd5","lo":"#356a9e","bh":243,"bc":0.012,"dk":0.0,  "lbl":"steel (bloomberg)"},
    "current":   {"acc":"0.66 0.19 290", "accS":"0.74 0.135 290","hi":"#7c5cff","lo":"#5331c9","bh":286,"bc":0.017,"dk":0.0,  "lbl":"iris (current)"},
    "mocha":     {"acc":"0.58 0.075 62", "accS":"0.71 0.06 66",  "hi":"#b07d52","lo":"#7a4f30","bh":55, "bc":0.013,"dk":0.0,  "lbl":"chocolate mocha"},
    "darkred":   {"acc":"0.57 0.17 22",  "accS":"0.68 0.15 24",  "hi":"#e0556a","lo":"#a32338","bh":18, "bc":0.013,"dk":0.0,  "lbl":"dark red"},
    "navy":      {"acc":"0.55 0.13 262", "accS":"0.68 0.11 262", "hi":"#5b78d6","lo":"#33489e","bh":262,"bc":0.015,"dk":0.01, "lbl":"navy"},
    "black":     {"acc":"0.82 0.0 0",    "accS":"0.92 0.0 0",    "hi":"#cfcfcf","lo":"#8a8a8a","bh":0,  "bc":0.0,  "dk":0.025,"lbl":"plain black"},
    "revolut":   {"acc":"0.74 0.05 255", "accS":"0.84 0.04 255", "hi":"#a7b4d8","lo":"#6b76a0","bh":255,"bc":0.006,"dk":0.035,"lbl":"black (revolut-ish)"},
}

LADDER = {"bg":0.155,"surf":0.196,"surf2":0.230,"surf3":0.268,"surf4":0.308,
          "hairline":0.240,"border":0.280,"border-s":0.370}

def root_css(c):
    acc, accS, bh, bc, dk = c["acc"], c["accS"], c["bh"], c["bc"], c["dk"]
    L = [f"  --iris:oklch({acc});",
         f"  --iris-s:oklch({accS});",
         f"  --iris-dim:oklch({acc} / 0.12);",
         f"  --iris-mid:oklch({acc} / 0.26);"]
    for k, v in LADDER.items():
        L.append(f"  --{k}:oklch({round(max(v-dk,0.04),3)} {bc} {bh});")
    L.append(f"  --fg:oklch(0.965 {min(bc,0.005)} {bh});")
    L.append(f"  --muted:oklch(0.68 {bc} {bh});")
    L.append(f"  --quiet:oklch(0.52 {bc} {bh});")
    return "\n/* ── brand theme ── */\n:root{\n" + "\n".join(L) + "\n}\n"

def build(name, color):
    c = COLORS[color]
    h = BASE
    # name swaps
    h = h.replace("<div class=\"sb-name\">Cosmu</div>", f"<div class=\"sb-name\">{name}</div>")
    h = h.replace("<title>Cosmu · Remix 02 · Iris Bento</title>", f"<title>{name} · {c['lbl']}</title>")
    h = h.replace("cmd-name\">cosmu ", f"cmd-name\">{name} ")
    h = h.replace("cosmu.app", f"{name}.app")
    # logo mark gradient
    h = h.replace("#7c5cff", c["hi"]).replace("#5331c9", c["lo"])
    # accent: the 9 inline iris literals
    h = h.replace("oklch(0.66 0.19 290", "oklch(" + c["acc"])
    # accent + base retint via an overriding :root (cascade wins)
    h = h.replace("\n</style>", root_css(c) + "</style>", 1)
    return h

PLAN = [("grovepool", ["green","orange","bloomberg","current"]),
        ("thorow",    ["green","orange","bloomberg","current","mocha","darkred","navy","black","revolut"])]

n = 0
for name, cols in PLAN:
    for col in cols:
        out = build(name, col)
        fn = f"mockups/brand-{name}-{col}.html"
        pathlib.Path(fn).write_text(out)
        n += 1
        print(f"wrote {fn}")
print(f"{n} files")
