# intent: the typed domain objects of the AUTHORITY feature. `AccountCall` is the data-agnostic INGEST unit (one
# account's directional call on one asset at one time) — what the LOCAL ingestion (JSON dump / xAI-Grok fetch /
# Claude-in-Chrome) feeds in. `PricePoint` is the tape a call is resolved against. `ResolvedCall` is one call
# joined to its forward move (the deterministic resolution). `Mover` is one outsized call (the top-3 surface).
# `AuthorityScore` is the per-account COMPOSITE row the dashboard serves. invariants: pure data (no I/O, no LLM);
# every resolved-only metric is Optional and stays None for an UNTESTED account (no resolved calls yet) — never a
# fabricated 0; direction is the controlled vocab {up, down, flat}; timestamps are tz-aware UTC.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# The predicted move. A flat call is a no-direction/range call — it counts for calibration + hit-rate but carries
# no tradeable payoff (you cannot "trade small" a flat call), so it never contributes to EV.
Direction = Literal["up", "down", "flat"]

# How a direction maps to the sign of a profitable move: +1 means "profit when price rises".
DIR_SIGN: dict[str, float] = {"up": 1.0, "down": -1.0, "flat": 0.0}


# --------------------------------------------------------------------------- the ingest unit (data-agnostic)


@dataclass(frozen=True)
class AccountCall:
    """ONE directional call: account X said asset A goes `direction` at time `ts`. The atom of the proprietary
    store, fed by ANY upstream (a pasted/JSON dump, an xAI/Grok timeline fetch, a Claude-in-Chrome scrape) — the
    LLM only EXTRACTS this shape, never scores it. `ts` is when the call was MADE (a public post is knowable when
    posted == availability, so there is no look-ahead). `conviction` (0..1) is how strongly it was asserted;
    `call_id` is a stable per-platform id used for dedup; `source` is provenance (json|xai|chrome|manual)."""

    account: str            # the handle, e.g. "@punk6529", "u/spez", a channel slug — normalized upstream
    platform: str           # "x" | "reddit" | "youtube" | "telegram" | "substack" | ...
    asset: str              # UPPERCASE ticker the call is about, e.g. "BTC", "ETH", "AAPL"
    direction: Direction    # predicted move: up | down | flat
    ts: datetime            # when the call was MADE == availability (point-in-time; tz-aware UTC)
    conviction: float = 0.5
    call_id: str = ""       # stable id within the platform (tweet id / url) — dedup key
    text: str = ""          # the verbatim call (provenance / display only — NEVER scored)
    url: str = ""           # canonical url (provenance)
    source: str = "manual"  # how this row reached us: json | xai | chrome | manual

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "platform": self.platform,
            "asset": self.asset,
            "direction": self.direction,
            "ts": self.ts.isoformat(),
            "conviction": self.conviction,
            "call_id": self.call_id,
            "text": self.text,
            "url": self.url,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AccountCall:
        return cls(
            account=str(d["account"]),
            platform=str(d["platform"]),
            asset=str(d["asset"]),
            direction=str(d["direction"]),  # type: ignore[arg-type]
            ts=datetime.fromisoformat(str(d["ts"])),
            conviction=float(d.get("conviction", 0.5)),
            call_id=str(d.get("call_id", "")),
            text=str(d.get("text", "")),
            url=str(d.get("url", "")),
            source=str(d.get("source", "manual")),
        )


# --------------------------------------------------------------------------- the tape (price series to resolve against)


@dataclass(frozen=True)
class PricePoint:
    """One (ts, price) sample of an asset's tape — the unit the scorer resolves a call against. A real run adapts
    OHLC bars to these (see store.prices_from_bars); a test injects them directly. tz-aware UTC, ascending."""

    ts: datetime
    price: float


# --------------------------------------------------------------------------- one resolved call (call ⋈ forward move)


ResolveStatus = Literal["resolved", "pending", "no_data"]


@dataclass(frozen=True)
class ResolvedCall:
    """ONE call joined to its forward price move. `signed_return` is the realized return mapped to the CLAIMED
    direction (positive == the call was right-ward) — the basis of EV/payoff. `hit` is the flat-band-aware
    direction correctness; `base_rate` is how often that direction happens UNCONDITIONALLY over the same horizon
    (the bar a real call must clear). `is_echo` is the lean echo discard — the claimed-direction move was already
    underway BEFORE the call (a late/echo call). `lead_days` is genuine foresight: days from the call until the
    market confirmed the move (0 for a non-winning or echo call). `status` is resolved / pending (horizon extends
    past `now`) / no_data (no tape)."""

    call: AccountCall
    status: ResolveStatus
    horizon_days: int
    entry_ts: datetime | None = None
    exit_ts: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    raw_return: float | None = None     # (exit - entry) / entry, unsigned
    signed_return: float | None = None  # raw_return mapped to the claimed direction (profit-positive)
    abs_move: float | None = None       # |raw_return|
    hit: bool | None = None
    base_rate: float | None = None
    base_abs_move: float | None = None
    is_echo: bool = False
    prior_move_frac: float = 0.0        # claimed-direction move already realized in the echo lookback before the call
    lead_days: float = 0.0


# --------------------------------------------------------------------------- one outsized call (the top-3 surface)


@dataclass(frozen=True)
class Mover:
    """One of an account's biggest calls by PAYOFF — the "wrong 90% but huge on 10%" surface. `payoff` is the
    echo-discounted contribution to EV (the money the call would have made traded small); `signed_return` is the
    raw direction-mapped return for display."""

    asset: str
    ts: datetime
    direction: Direction
    signed_return: float
    payoff: float
    is_echo: bool = False

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "ts": self.ts.isoformat(),
            "direction": self.direction,
            "signed_return": round(self.signed_return, 6),
            "payoff": round(self.payoff, 6),
            "is_echo": self.is_echo,
        }


# --------------------------------------------------------------------------- the per-account composite score (output row)


@dataclass(frozen=True)
class AuthorityScore:
    """One account's COMPOSITE authority row — the proprietary-data dashboard surface. Brier alone is NOT enough
    (it ignores payoff), so the composite fuses calibration (`brier`/`brier_skill_score`/`calibration_error`),
    being-right (`hit_rate`), PROFIT (`ev` — cumulative return trading each call small, net of the echo discount;
    weighted highest), magnitude (`avg_move_when_right`), foresight (`avg_lead_days`), and gain spread
    (`consistency` — LOW when one spike carries the account). `top_movers` surfaces the 3 most profitable calls
    (an account wrong most of the time but huge on a few is interesting — profit > hit-rate). Every resolved-only
    metric is None for an UNTESTED account (calls on record but none resolved yet) — never a fabricated 0."""

    account: str
    platform: str
    n_calls: int                 # calls attributed (volume, NOT skill)
    n_resolved: int              # calls old enough to score against the tape
    n_echo: int                  # of the resolved, how many were late/echo (discounted)
    hit_rate: float | None = None
    base_hit_rate: float | None = None
    brier: float | None = None
    brier_skill_score: float | None = None
    calibration_error: float | None = None
    ev: float | None = None              # cumulative compounded return, calls traded small (the payoff headline)
    avg_move_when_right: float | None = None
    avg_lead_days: float | None = None
    consistency: float | None = None     # [0,1] — gain spread; low = one call dominates the EV
    composite: float | None = None       # [0,1] headline authority score
    rank: int | None = None              # 1-based composite rank within the TESTED roster (relative, not absolute)
    percentile: float | None = None      # [0,1] standing within the tested roster (1.0 = best)
    composite_z: float | None = None     # z-score of the composite vs the roster mean (None when std == 0 / roster of 1)
    top_movers: tuple[Mover, ...] = field(default_factory=tuple)
    last_call_ts: datetime | None = None

    def to_row(self) -> dict:
        """Flat dict for persistence / the API contract (top_movers serialized to a list of dicts)."""
        return {
            "account": self.account,
            "platform": self.platform,
            "n_calls": self.n_calls,
            "n_resolved": self.n_resolved,
            "n_echo": self.n_echo,
            "hit_rate": self.hit_rate,
            "base_hit_rate": self.base_hit_rate,
            "brier": self.brier,
            "brier_skill_score": self.brier_skill_score,
            "calibration_error": self.calibration_error,
            "ev": self.ev,
            "avg_move_when_right": self.avg_move_when_right,
            "avg_lead_days": self.avg_lead_days,
            "consistency": self.consistency,
            "composite": self.composite,
            "rank": self.rank,
            "percentile": self.percentile,
            "composite_z": self.composite_z,
            "top_movers": [m.to_dict() for m in self.top_movers],
            "last_call_ts": self.last_call_ts.isoformat() if self.last_call_ts else None,
        }


__all__ = [
    "AccountCall",
    "AuthorityScore",
    "DIR_SIGN",
    "Direction",
    "Mover",
    "PricePoint",
    "ResolveStatus",
    "ResolvedCall",
]
