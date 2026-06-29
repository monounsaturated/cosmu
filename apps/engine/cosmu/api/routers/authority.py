# intent: the AUTHORITY dashboard endpoint — GET /authority serves the authority_scoreboard table flat and typed,
# one composite row per account, ordered composite DESC with UNTESTED (null composite) accounts last. PROPRIETARY
# DATA, not a strategy: a high score later powers an LLM strategy (separate lane, out of scope). invariants:
# read-only; no LLM and no recompute on the request path (the row is PRECOMPUTED by the local authority pass);
# nullable metrics pass through as null (untested ≠ unskilled — never coerced to 0); a DB without the additive
# authority_scoreboard migration yields the honest empty panel (rows=[], as_of=null), never a 500; AUTH is the
# app-level x-api-key middleware (no per-route check).

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import AuthorityMover, AuthorityResponse, AuthorityRow

router = APIRouter()


@router.get("/authority", response_model=AuthorityResponse)
def authority() -> AuthorityResponse:
    """The proprietary AUTHORITY scoreboard — one composite row per scored account (Brier · hit-rate · EV/payoff ·
    magnitude · lead-time · consistency · composite · top-3 movers), composite DESC, UNTESTED last. Read-only;
    served from the precomputed `authority_scoreboard` (no live recompute, no LLM on this path)."""
    from cosmu.authority.store import load_scoreboard

    with store.reading():
        rows = load_scoreboard(store)

    return AuthorityResponse(
        as_of=max((str(r["updated_at"]) for r in rows), default=None),
        n_accounts=len(rows),
        rows=[
            AuthorityRow(
                account=str(r["account"]),
                platform=str(r["platform"]),
                n_calls=int(r["n_calls"] or 0),
                n_resolved=int(r["n_resolved"] or 0),
                n_echo=int(r["n_echo"] or 0),
                hit_rate=_opt(r["hit_rate"]),
                base_hit_rate=_opt(r["base_hit_rate"]),
                brier=_opt(r["brier"]),
                brier_skill_score=_opt(r["brier_skill_score"]),
                calibration_error=_opt(r["calibration_error"]),
                ev=_opt(r["ev"]),
                avg_move_when_right=_opt(r["avg_move_when_right"]),
                avg_lead_days=_opt(r["avg_lead_days"]),
                consistency=_opt(r["consistency"]),
                composite=_opt(r["composite"]),
                top_movers=[
                    AuthorityMover(
                        asset=str(m.get("asset", "")),
                        ts=str(m.get("ts", "")),
                        direction=str(m.get("direction", "")),
                        signed_return=float(m.get("signed_return", 0.0)),
                        payoff=float(m.get("payoff", 0.0)),
                        is_echo=bool(m.get("is_echo", False)),
                    )
                    for m in (r.get("top_movers") or [])
                ],
                last_call_ts=_opt_str(r.get("last_call_ts")),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ],
    )


def _opt(value: object) -> float | None:
    """NULL-preserving float: an untested metric stays None — never coerced to 0.0."""
    return None if value is None else float(value)


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)
