# intent: assemble a point-in-time news/intel panel from ingested news_event_score data.
# Inputs: the append-only alt_data store. Outputs: a list of recent ScoredNewsEvent-like dicts
# (headline, event_type, sign, magnitude, confidence, ts, available_at) sorted newest-first.
# Invariants: read-only; offline-safe (returns [] on missing table); never fabricates;
# no LLM on this path (events were scored at ingest). Honest empty state when no data.

from __future__ import annotations

from typing import Any


_EMPTY: list[dict] = []


def recent_news_events(store: Any, *, symbol: str = "BTCUSDT", limit: int = 20) -> list[dict[str, Any]]:
    """Return the `limit` most-recent scored news events for `symbol`, newest first.

    Each row has: ts, available_at, value (signed magnitude in [-1,1]), metric="news_event_score".
    Reconstructs direction from value sign. Returns [] when no data (honest empty state)."""
    try:
        rows = store.rows(
            "SELECT ts, available_at, value FROM alt_data "
            "WHERE provider = 'news' AND symbol = ? AND metric = 'news_event_score' "
            "ORDER BY available_at DESC LIMIT ?",
            (symbol, limit),
        )
    except Exception:  # noqa: BLE001
        return _EMPTY

    out: list[dict[str, Any]] = []
    for r in rows:
        value = r.get("value")
        if value is None:
            continue
        v = float(value)
        if v > 0.05:
            event_type = "bullish"
        elif v < -0.05:
            event_type = "bearish"
        else:
            event_type = "neutral"
        out.append({
            "ts": r.get("ts"),
            "available_at": r.get("available_at"),
            "value": round(v, 4),
            "event_type": event_type,
            "symbol": symbol,
        })
    return out
