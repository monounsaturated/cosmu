# intent: the engine-side SINGLE SOURCE OF TRUTH for which control-plane routes move (or arm) real money;
# inputs: an HTTP method + request path; outputs: a deny-by-default bool; invariants: the set MUST mirror the
# web's apps/web/lib/money-routes.ts MONEY_MUTATION_PATHS so the two enforcement tiers can never drift.

from __future__ import annotations

from urllib.parse import unquote

# The money-mutating engine routes (grepped from cosmu/api/routers/{toggle,live,ops}.py). Kept byte-identical
# to apps/web/lib/money-routes.ts MONEY_MUTATION_PATHS. EXCLUDES the pure reduce-only SAFETY exits
# (/ops/killswitch, /live/orders/{id}/cancel) — those must always route (closing exposure IS the safety move).
MONEY_MUTATION_PATHS: frozenset[str] = frozenset(
    {
        "/toggle/live",
        "/live/activate",
        "/live/launch",
        "/live/defund",
        "/live/liquidate",
        "/live/rules",
        "/live/jurisdiction",
        "/ops/breaker/rearm",
    }
)

_MUTATION_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _decode_all(s: str) -> str:
    """Repeatedly percent-decode until stable so a double/triple-encoded segment collapses before matching."""
    prev = s
    for _ in range(5):
        nxt = unquote(prev)
        if nxt == prev:
            return nxt
        prev = nxt
    return prev


def normalize_path(raw: str) -> str:
    """Canonicalize a request path to the ONE form the matcher set is keyed on — anti-evasion mirror of the
    web's normalizeEnginePath: strip query, fully %-decode, lowercase, backslash→slash, collapse repeated
    slashes, resolve . / .. segments, drop a trailing slash, single leading slash. FastAPI's request.url.path is
    already decoded + starts with '/', but we normalize defensively so a proxy that forwards a raw/odd path (or a
    direct-to-engine caller) is matched the same."""
    p = raw or ""
    for sep in ("?", "#"):
        i = p.find(sep)
        if i != -1:
            p = p[:i]
    p = _decode_all(p)
    p = p.lower()
    p = p.replace("\\", "/")
    out: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/" + "/".join(out)


def is_money_mutation(method: str, raw_path: str) -> bool:
    """Deny-by-default: True ONLY when a mutating method hits a KNOWN money-mutation route (after
    normalization). Anything unknown is not a money mutation — the second tier is additive and never a new way to
    block a legitimate read."""
    if (method or "").upper() not in _MUTATION_METHODS:
        return False
    return normalize_path(raw_path) in MONEY_MUTATION_PATHS
