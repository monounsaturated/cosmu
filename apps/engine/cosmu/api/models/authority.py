# intent: typed contract for the AUTHORITY dashboard — the authority_scoreboard table served flat over
# GET /authority. PROPRIETARY DATA, not a strategy: one composite row per account, derived from whether its past
# asset calls corroborated the later tape. inputs: authority_scoreboard rows written by the LOCAL authority pass
# (cosmu/authority); outputs: AuthorityResponse for the generated TS contract; invariants: nullable metrics stay
# null (an UNTESTED account — calls on record but none resolved yet — is NEVER rendered as 0); read-only, no LLM
# on this path, the Gate/money path is deterministic and separate (a high score later powers an LLM strategy —
# out of scope here).

from __future__ import annotations

from pydantic import BaseModel


class AuthorityMover(BaseModel):
    """One of an account's biggest calls by PAYOFF — the "wrong most of the time but huge on a few" surface.
    `signed_return` is the raw direction-mapped return; `payoff` is the echo-discounted contribution to EV."""

    asset: str
    ts: str
    direction: str
    signed_return: float
    payoff: float
    is_echo: bool = False


class AuthorityRow(BaseModel):
    """One account's flat COMPOSITE row. `n_calls` is volume (NOT skill); `n_resolved` is how many calls were old
    enough to score against the tape; `n_echo` is how many of those were late/echo (discounted). Every derived
    metric is nullable — an account with zero resolved calls carries NULL everything (honest UNTESTED, not 0).
    `ev` is the cumulative return trading each call small (the payoff headline, weighted highest in the
    composite); `composite` is the [0,1] authority score; `top_movers` is the top-3 calls by payoff;
    `consistency` is the gain spread (LOW when one spike carries the account — interesting, not bad)."""

    account: str
    platform: str
    n_calls: int
    n_resolved: int
    n_echo: int
    hit_rate: float | None = None
    base_hit_rate: float | None = None
    brier: float | None = None
    brier_skill_score: float | None = None
    calibration_error: float | None = None
    ev: float | None = None
    avg_move_when_right: float | None = None
    avg_lead_days: float | None = None
    consistency: float | None = None
    composite: float | None = None
    top_movers: list[AuthorityMover] = []
    last_call_ts: str | None = None
    updated_at: str


class AuthorityResponse(BaseModel):
    """The authority dashboard: one row per scored account, ordered composite DESC with UNTESTED (null composite)
    last. `n_accounts` is the row count; `as_of` is the latest scoreboard update (null when empty — the proprietary
    store fills once the local ingest + score pass has run on real account-call data)."""

    as_of: str | None = None
    n_accounts: int
    rows: list[AuthorityRow]
