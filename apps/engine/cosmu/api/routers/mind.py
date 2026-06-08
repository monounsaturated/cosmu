# intent: the Mind — the agent's standardized self-knowledge (KNOWS/THINKS/LEARNED) + source-trust + news intel; inputs: none/symbol; outputs: typed snapshots; invariants: reasons only, never funds or fires an order; abstains rather than fabricates; SERVES PRECOMPUTED/CACHED reasoning — NEVER computes it live in the request path.

from __future__ import annotations

import json
import time

from fastapi import APIRouter

from cosmu.api._shared import settings, store
from cosmu.api.models import (
    MindResponse,
    NewsEventRow,
    NewsIntelResponse,
    SourceTrustResponse,
    SourceTrustRow,
)

router = APIRouter()


@router.get("/mind", response_model=MindResponse)
def mind() -> MindResponse:
    """The Mind — the agent's standardized self-knowledge in one read: what it KNOWS (point-in-time data sources
    + freshness), how it THINKS (the analyst panel + the debate's consensus), and what it has LEARNED (memory,
    the ML survival model, regime coverage, gate efficiency). RAILGUARD: this reasons; it never funds or fires
    an order — the deterministic gate alone disposes.

    PRECOMPUTED, NEVER LIVE: the autonomy tick already persists the full snapshot to `mind_reflections` (it does
    the live Binance regime read + the optional LLM judge OUT OF BAND). This GET serves the LAST persisted
    reflection — no synchronous market fetch and no LLM call on the request path, which is what made it hang for
    35 s on prod (the regime read blocked on a geo-throttled Binance REST call inside the handler). When no
    reflection exists yet we fall back to an OFFLINE, deterministic rebuild (NO reference bars → the technical
    analyst honestly abstains; NO judge) — all-DB, fast, and never fabricated."""
    cached = _last_reflection()
    if cached is not None:
        return MindResponse(**cached)

    # Cold start (no reflection persisted yet): rebuild offline-only. Pass NO reference_bars (so we never touch
    # the network here) and NO judge (no LLM in the request path). The technical analyst abstains honestly.
    from cosmu.mind import build_mind

    return MindResponse(**build_mind(store))


def _last_reflection() -> dict | None:
    """The full payload of the most recent persisted Mind reflection, or None.

    The autonomy tick writes the entire `build_mind` dict to `mind_reflections.payload` as JSON, so the snapshot
    round-trips exactly into MindResponse with no recompute. Defensive: a prod DB that has not applied the
    additive `mind_reflections` migration (or a fresh store) simply yields None and we fall back to the offline
    rebuild — never an error, never fabricated."""
    try:
        with store.reading():
            row = store.row("SELECT payload FROM mind_reflections ORDER BY id DESC LIMIT 1")
    except Exception:  # noqa: BLE001 — table absent on a not-yet-migrated prod DB → fall back to offline rebuild
        return None
    if not row:
        return None
    raw = row.get("payload")
    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


# --- source-trust: a short in-process TTL cache. The scoreboard aggregates the WHOLE alt_data table (GROUP BY)
# + every gate-passed strategy spec; on prod Postgres that cold scan took ~23 s and blew the web's 5 s SSR
# budget. The data only changes when new alt-data is ingested or a backtest passes (minutes-to-hours cadence),
# so we compute it at most once per TTL and serve the cached typed rows to every other caller (the frontend
# re-renders + polls well inside the window). Read-only; honest-empty preserved; the value is the REAL compute. ---
_SOURCE_TRUST_TTL_S = 300.0
_source_trust_cache: dict[str, object] = {"at": 0.0, "rows": None}


@router.get("/mind/source-trust", response_model=SourceTrustResponse)
def mind_source_trust() -> SourceTrustResponse:
    """Source-trust scoreboard — for every registered data source, a plain-language trust score.

    Trust = freshness × realized gate contribution (how many gate-passed backtests used this source).
    Honest: a source with no data ingested shows trust_score=0, status="no data" — never fabricates.
    Read-only; no LLM on this path; the Gate/money path is deterministic and separate. SERVED FROM A SHORT
    TTL CACHE so the heavy full-table aggregation runs at most once per few minutes, never per request."""
    from cosmu.knowledge.store import utcnow

    rows = _source_trust_rows()
    return SourceTrustResponse(
        as_of=utcnow(),
        rows=[
            SourceTrustRow(
                source=r.source,
                features=r.features,
                last_at=r.last_at,
                freshness_label=r.freshness_label,
                status=r.status,
                gate_pass_count=r.gate_pass_count,
                trust_score=r.trust_score,
                summary=r.summary,
                tier=r.tier,
                hours_since=r.hours_since,
            )
            for r in rows
        ],
    )


def _source_trust_rows():
    """The trust scoreboard rows, recomputed at most once per `_SOURCE_TRUST_TTL_S`. The cached object is the
    real list of SourceTrustRow (the honest empty/no-data state included) — never a fabricated placeholder."""
    now = time.monotonic()
    cached = _source_trust_cache["rows"]
    if cached is not None and (now - float(_source_trust_cache["at"])) < _SOURCE_TRUST_TTL_S:
        return cached

    from cosmu.mind.source_trust import build_source_trust

    with store.reading():
        rows = build_source_trust(store)
    _source_trust_cache["rows"] = rows
    _source_trust_cache["at"] = now
    return rows


@router.get("/mind/news-intel", response_model=NewsIntelResponse)
def mind_news_intel(symbol: str = "BTCUSDT", limit: int = 20) -> NewsIntelResponse:
    """Recent scored news events for a symbol — the typed, dated, point-in-time news/intel panel.

    Each event has: ts, available_at, value (signed magnitude in [-1, 1]), event_type (bullish/bearish/neutral).
    Honest empty state when no news has been ingested yet. No LLM on this path — events were scored at ingest."""
    from cosmu.mind.news_intel import recent_news_events

    with store.reading():
        raw = recent_news_events(store, symbol=symbol, limit=min(limit, 100))
    return NewsIntelResponse(
        symbol=symbol,
        events=[
            NewsEventRow(
                ts=r.get("ts"),
                available_at=r.get("available_at"),
                value=float(r["value"]),
                event_type=r["event_type"],
                symbol=symbol,
            )
            for r in raw
        ],
    )
