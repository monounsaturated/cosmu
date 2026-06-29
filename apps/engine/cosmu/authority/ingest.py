# intent: the DATA-AGNOSTIC ingest seam of the AUTHORITY feature — the single clean function the LOCAL ingestion
# feeds, regardless of WHERE the account-call data came from: a pasted/JSON dump, an xAI/Grok timeline fetch, or a
# Claude-in-Chrome scrape. Each upstream hands us loosely-shaped records (different field names, direction
# phrasings, timestamp formats); `parse_calls` normalizes them into typed `AccountCall`s. invariants: the LLM /
# scraper only EXTRACTS the shape — this layer does the deterministic normalization (the SCORE downstream is pure
# math, so a mis-extracted field can only drop a row, never fabricate a number); LENIENT by design — an
# un-parseable record is DROPPED and the batch survives (a malformed dump never aborts ingestion); a record
# missing any of {account, asset, direction, ts} is dropped (we never guess a call); direction is mapped through
# a synonym table to the controlled vocab; assets are upper-cased; timestamps are coerced to tz-aware UTC.

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from cosmu.authority.models import AccountCall

# Direction synonyms → the controlled vocab. Anything not here (after lower-casing) drops the record (never
# guessed). Deliberately broad on the bullish/bearish vocab social posts actually use.
DIRECTION_SYNONYMS: dict[str, str] = {
    # up
    "up": "up", "bull": "up", "bullish": "up", "long": "up", "buy": "up", "moon": "up",
    "higher": "up", "breakout": "up", "pump": "up", "calls": "up", "+": "up", "1": "up",
    # down
    "down": "down", "bear": "down", "bearish": "down", "short": "down", "sell": "down", "dump": "down",
    "lower": "down", "breakdown": "down", "puts": "down", "-": "down", "-1": "down",
    # flat
    "flat": "flat", "neutral": "flat", "chop": "flat", "sideways": "flat", "range": "flat", "0": "flat",
}

# Candidate field names per logical field — first present (and truthy) wins. Lets one parser absorb the schemas
# of a hand JSON dump, the xAI/Grok response shape, and a Chrome scrape without per-source branching.
_ACCOUNT_KEYS = ("account", "handle", "author", "username", "screen_name", "user")
_PLATFORM_KEYS = ("platform", "source_platform", "network")
_ASSET_KEYS = ("asset", "ticker", "symbol", "coin", "entity")
_DIRECTION_KEYS = ("direction", "stance", "sentiment", "call", "side", "signal")
_TS_KEYS = ("ts", "timestamp", "created_at", "date", "time", "posted_at")
_CONVICTION_KEYS = ("conviction", "confidence", "strength", "score")
_ID_KEYS = ("call_id", "id", "tweet_id", "post_id", "status_id")
_TEXT_KEYS = ("text", "quote", "content", "body", "tweet")
_URL_KEYS = ("url", "link", "permalink", "href")


def _first(record: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return None


def _norm_account(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _norm_asset(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper().lstrip("$")
    return s or None


def _norm_direction(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    return DIRECTION_SYNONYMS.get(s)


def _norm_ts(value: Any) -> datetime | None:
    """Coerce a timestamp to tz-aware UTC. Accepts ISO strings (with or without offset / trailing 'Z') and
    epoch seconds/millis (int or numeric str). Returns None on anything un-parseable (the record drops)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    # Epoch numbers.
    if isinstance(value, (int, float)):
        secs = float(value)
        if secs > 1e12:  # millis
            secs /= 1000.0
        try:
            return datetime.fromtimestamp(secs, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return _norm_ts(int(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _norm_conviction(value: Any) -> float:
    if value is None:
        return 0.5
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    if c > 1.0:  # a 0..100 confidence → 0..1
        c = c / 100.0
    return min(1.0, max(0.0, c))


def parse_call(record: Mapping[str, Any], *, source: str = "manual", default_platform: str = "x") -> AccountCall | None:
    """Normalize ONE loosely-shaped record into a typed `AccountCall`, or None if it lacks any of the four
    required fields (account, asset, direction, ts) or they don't normalize. LENIENT — drop, never raise."""
    if not isinstance(record, Mapping):
        return None
    account = _norm_account(_first(record, _ACCOUNT_KEYS))
    asset = _norm_asset(_first(record, _ASSET_KEYS))
    direction = _norm_direction(_first(record, _DIRECTION_KEYS))
    ts = _norm_ts(_first(record, _TS_KEYS))
    if account is None or asset is None or direction is None or ts is None:
        return None
    platform_raw = _first(record, _PLATFORM_KEYS)
    platform = str(platform_raw).strip().lower() if platform_raw else default_platform
    call_id = _first(record, _ID_KEYS)
    return AccountCall(
        account=account,
        platform=platform or default_platform,
        asset=asset,
        direction=direction,  # type: ignore[arg-type]
        ts=ts,
        conviction=_norm_conviction(_first(record, _CONVICTION_KEYS)),
        call_id=str(call_id).strip() if call_id is not None else "",
        text=str(_first(record, _TEXT_KEYS) or "").strip(),
        url=str(_first(record, _URL_KEYS) or "").strip(),
        source=source,
    )


def parse_calls(payload: Any, *, source: str = "manual", default_platform: str = "x") -> list[AccountCall]:
    """Parse a whole dump into typed calls. Accepts: a JSON STRING, a LIST of record dicts, or a DICT wrapping the
    list under "calls" / "data" / "results" (the shapes a JSON dump, an xAI/Grok response, or a Chrome scrape
    arrive in). Un-parseable records are DROPPED (the batch survives); the result is de-duplicated on
    (account, platform, call_id, asset, direction, ts) and ordered by (ts, account, asset)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if isinstance(payload, Mapping):
        for key in ("calls", "data", "results", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]  # a single record dict
    if not isinstance(payload, list):
        return []

    seen: set[tuple] = set()
    out: list[AccountCall] = []
    for record in payload:
        call = parse_call(record, source=source, default_platform=default_platform)
        if call is None:
            continue
        key = (call.account, call.platform, call.call_id, call.asset, call.direction, call.ts.isoformat())
        if key in seen:
            continue
        seen.add(key)
        out.append(call)
    out.sort(key=lambda c: (c.ts, c.account, c.asset, c.direction))
    return out


__all__ = ["DIRECTION_SYNONYMS", "parse_call", "parse_calls"]
