# Web↔engine route reconciliation guard. The web app calls the engine through two seams only:
# `engineFetch("/path")` (client, via the Next proxy) and `getJson("/path", ...)` (server). A path that
# the UI fetches but the engine doesn't serve renders an empty/errored page — the exact class of bug this
# test exists to PREVENT (history: /strategies, /lab/strategies, /research/verdicts once 404'd here).
#
# It is deliberately static (no running web server): it imports the FastAPI app for the ground-truth route
# table, scans apps/web source for every engine call site, and asserts each resolves to a real route.
# Dynamic segments are handled honestly — `${rec.id}` → a wildcard segment, and an inline ternary
# `${x ? "pause" : "resume"}` is expanded to both literal paths — so the check is precise, not hand-wavy.

from __future__ import annotations

import re
from pathlib import Path

import cosmu.api.app as app_mod

# Repo layout: this file is apps/engine/tests/<f>.py → repo root is parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WEB_ROOT = _REPO_ROOT / "apps" / "web"

# Non-route paths the engine mounts for free (docs/schema) — never called by the product, ignored if they were.
_DOC_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

# Files that legitimately mention the seams without being a real call site (the helper definition + the proxy).
_SKIP_FILES = {
    _WEB_ROOT / "lib" / "engine.ts",
    _WEB_ROOT / "app" / "api" / "engine" / "[...path]" / "route.ts",
}

# Call-site patterns. Group 1 = the quote char, group 2 = the literal path. We capture the FIRST string/template
# literal argument of each seam. `post(` is included for the one local forwarder (universe-settings.tsx) that
# does `engineFetch(path)` over a literal passed to a local `post("/universe/...", ...)`; we require a leading
# slash so it can never capture an unrelated `.post(...)`.
_CALL_PATTERNS = [
    re.compile(r"""engineFetch\s*\(\s*(['"`])(/[^'"`]*)\1"""),
    re.compile(r"""getJson\s*(?:<[^>]*>)?\s*\(\s*(['"`])(/[^'"`]*)\1"""),
    re.compile(r"""\bpost\s*\(\s*(['"`])(/[^'"`]*)\1"""),
]

# An inline ternary over two string literals inside a template slot: ${ cond ? "a" : "b" }.
_TERNARY = re.compile(r"""\$\{[^}]*\?\s*['"]([^'"]+)['"]\s*:\s*['"]([^'"]+)['"][^}]*\}""")
# Any remaining template slot (a real interpolated value) → a single wildcard segment.
_SLOT = re.compile(r"\$\{[^}]*\}")


def _engine_routes() -> set[tuple[str, ...]]:
    """Ground-truth route templates as segment tuples, params normalized to the '{}' wildcard."""
    routes: set[tuple[str, ...]] = set()
    for r in app_mod.app.routes:
        path = getattr(r, "path", None)
        if not path or not getattr(r, "methods", None) or path in _DOC_PATHS:
            continue
        routes.add(_segments(path))
    return routes


def _segments(path: str) -> tuple[str, ...]:
    """Split a path into segments, collapsing every param/wildcard segment to '{}'."""
    out = []
    for seg in path.strip("/").split("/"):
        out.append("{}" if (seg.startswith("{") and seg.endswith("}")) else seg)
    return tuple(out)


def _expand(raw: str) -> list[str]:
    """A captured literal → the concrete path(s) it can resolve to. Expands inline string ternaries to both
    branches, turns other template slots into a wildcard, then drops any query string."""
    variants = [raw]
    while True:
        grew: list[str] = []
        changed = False
        for v in variants:
            m = _TERNARY.search(v)
            if m:
                changed = True
                grew.append(v[: m.start()] + m.group(1) + v[m.end() :])
                grew.append(v[: m.start()] + m.group(2) + v[m.end() :])
            else:
                grew.append(v)
        variants = grew
        if not changed:
            break
    out = []
    for v in variants:
        v = _SLOT.sub("{}", v)  # remaining real interpolations → wildcard segment
        v = v.split("?", 1)[0]  # strip query string (safe: ternary '?'s are already resolved)
        out.append(v)
    return out


def _matches(web: tuple[str, ...], route: tuple[str, ...]) -> bool:
    """Segment-wise unify: same length, and each pair compatible where '{}' on EITHER side is a wildcard."""
    if len(web) != len(route):
        return False
    return all(w == "{}" or r == "{}" or w == r for w, r in zip(web, route))


def _web_call_sites() -> list[tuple[Path, int, str]]:
    sites: list[tuple[Path, int, str]] = []
    for path in sorted(_WEB_ROOT.rglob("*.ts*")):
        if path in _SKIP_FILES or "node_modules" in path.parts or ".next" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pat in _CALL_PATTERNS:
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                sites.append((path, line, m.group(2)))
    return sites


def test_every_web_engine_call_hits_a_real_route():
    routes = _engine_routes()
    sites = _web_call_sites()
    assert sites, "found no engine call sites in apps/web — the extractor or paths moved"

    unmatched: list[str] = []
    for file, line, raw in sites:
        for concrete in _expand(raw):
            segs = _segments(concrete)
            if not any(_matches(segs, route) for route in routes):
                rel = file.relative_to(_REPO_ROOT)
                unmatched.append(f"  {rel}:{line}  →  {concrete!r}  (no engine route)")

    assert not unmatched, (
        "Web calls an engine path that does not exist (would 404 → empty/errored page):\n"
        + "\n".join(sorted(set(unmatched)))
        + "\n\nFix the path in apps/web, or add the route in apps/engine/cosmu/api/routers/."
    )
