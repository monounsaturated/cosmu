# intent: PERSISTENCE for the AUTHORITY feature — the proprietary data store. Two tables: `authority_calls` (the
# raw, deduped account-call corpus the ingest seam fills) and `authority_scoreboard` (one flat composite row per
# account, the dashboard surface). This module persists/loads the corpus, runs the deterministic scorer over it
# (`build_scoreboard`), and persists the resulting rows; the API serves the persisted rows (PRECOMPUTED, never a
# live recompute on the request path). invariants: append-only-ish corpus deduped on a stable key (a re-fed dump
# never double-counts); DEFENSIVE reads — a prod DB without the additive migration yields the honest empty state,
# never a 500; the scorer is pure (no LLM, no money path); UNTESTED accounts persist with NULL metrics, never 0.

from __future__ import annotations

import json
from datetime import datetime
from typing import Mapping, Sequence

from cosmu.authority.models import AccountCall, AuthorityScore, PricePoint
from cosmu.authority.scoring import DEFAULT_HORIZON_DAYS, score_accounts
from cosmu.knowledge.store import Store, utcnow

_CALL_COLUMNS = (
    "account", "platform", "asset", "direction", "ts", "conviction", "call_id", "text", "url",
    "source", "ingested_at",
)

_SCOREBOARD_COLUMNS = (
    "account", "platform", "n_calls", "n_resolved", "n_echo", "hit_rate", "base_hit_rate", "brier",
    "brier_skill_score", "calibration_error", "ev", "avg_move_when_right", "avg_lead_days", "consistency",
    "composite", "top_movers", "last_call_ts", "updated_at",
)


# --------------------------------------------------------------------------- the raw call corpus


def persist_calls(store: Store, calls: Sequence[AccountCall]) -> int:
    """Insert NEW calls only (deduped on (account, platform, call_id, asset, direction, ts), pre-filtered here so
    the batch never trips the UNIQUE constraint). Returns the number written. A re-fed dump is free (no double
    count)."""
    if not calls:
        return 0
    accounts = sorted({c.account for c in calls})
    placeholders = ",".join("?" for _ in accounts)
    existing = {
        (r["account"], r["platform"], r["call_id"], r["asset"], r["direction"], str(r["ts"]))
        for r in store.rows(
            f"SELECT account, platform, call_id, asset, direction, ts FROM authority_calls "
            f"WHERE account IN ({placeholders})",
            tuple(accounts),
        )
    }
    now = utcnow()
    seen = set(existing)
    rows: list[tuple] = []
    for c in calls:
        key = (c.account, c.platform, c.call_id, c.asset, c.direction, c.ts.isoformat())
        if key in seen:
            continue
        seen.add(key)
        rows.append((c.account, c.platform, c.asset, c.direction, c.ts.isoformat(), float(c.conviction),
                     c.call_id, c.text, c.url, c.source, now))
    if rows:
        with store.batch() as writer:
            writer.insert_many("authority_calls", list(_CALL_COLUMNS), rows)
    return len(rows)


def load_calls(store: Store) -> list[AccountCall]:
    """Every stored call as a typed `AccountCall`, ordered (ts, account, asset). Defensive: a DB without the
    additive `authority_calls` migration yields [] (honest empty), never an error."""
    try:
        rows = store.rows("SELECT * FROM authority_calls ORDER BY ts, account, asset")
    except Exception:  # noqa: BLE001 — table absent on a not-yet-migrated DB → honest empty
        return []
    out: list[AccountCall] = []
    for r in rows:
        ts = datetime.fromisoformat(str(r["ts"]))
        out.append(AccountCall(
            account=str(r["account"]), platform=str(r["platform"]), asset=str(r["asset"]),
            direction=str(r["direction"]),  # type: ignore[arg-type]
            ts=ts, conviction=float(r["conviction"]),
            call_id=str(r.get("call_id") or ""), text=str(r.get("text") or ""),
            url=str(r.get("url") or ""), source=str(r.get("source") or "manual"),
        ))
    return out


# --------------------------------------------------------------------------- the composite scoreboard


def prices_from_bars(bars_by_asset: Mapping[str, Sequence]) -> dict[str, list[PricePoint]]:
    """Adapt OHLC bars (cosmu.data.market.Bar) to the scorer's `PricePoint` tape (close price). Lets a real run
    feed the same bar cache the rest of the engine uses; tests inject PricePoints directly and skip this."""
    out: dict[str, list[PricePoint]] = {}
    for asset, bars in bars_by_asset.items():
        out[asset] = [PricePoint(ts=b.ts, price=float(b.close)) for b in bars]
    return out


def build_scoreboard(
    store: Store,
    prices: Mapping[str, Sequence[PricePoint]],
    *,
    now: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> list[AuthorityScore]:
    """Load the corpus and score every account against the supplied tape. Pure given (corpus, prices, now) — the
    LLM is nowhere on this path. No calls → [] (honest)."""
    calls = load_calls(store)
    if not calls:
        return []
    return score_accounts(calls, prices, now=now, horizon_days=horizon_days)


def persist_scoreboard(store: Store, scores: Sequence[AuthorityScore], *, now: str | None = None) -> int:
    """Upsert one flat row per account into `authority_scoreboard` (the dashboard surface). top_movers is stored
    as JSON. UNTESTED accounts persist with NULL metrics (never 0). Returns rows written."""
    now = now or utcnow()
    written = 0
    with store.batch() as writer:
        for s in scores:
            row = s.to_row()
            writer.execute(
                """
                INSERT INTO authority_scoreboard (account, platform, n_calls, n_resolved, n_echo, hit_rate,
                  base_hit_rate, brier, brier_skill_score, calibration_error, ev, avg_move_when_right,
                  avg_lead_days, consistency, composite, top_movers, last_call_ts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (platform, account) DO UPDATE SET
                  n_calls = excluded.n_calls, n_resolved = excluded.n_resolved, n_echo = excluded.n_echo,
                  hit_rate = excluded.hit_rate, base_hit_rate = excluded.base_hit_rate, brier = excluded.brier,
                  brier_skill_score = excluded.brier_skill_score, calibration_error = excluded.calibration_error,
                  ev = excluded.ev, avg_move_when_right = excluded.avg_move_when_right,
                  avg_lead_days = excluded.avg_lead_days, consistency = excluded.consistency,
                  composite = excluded.composite, top_movers = excluded.top_movers,
                  last_call_ts = excluded.last_call_ts, updated_at = excluded.updated_at
                """,
                (
                    row["account"], row["platform"], row["n_calls"], row["n_resolved"], row["n_echo"],
                    row["hit_rate"], row["base_hit_rate"], row["brier"], row["brier_skill_score"],
                    row["calibration_error"], row["ev"], row["avg_move_when_right"], row["avg_lead_days"],
                    row["consistency"], row["composite"], json.dumps(row["top_movers"]), row["last_call_ts"], now,
                ),
            )
            written += 1
    return written


def load_scoreboard(store: Store) -> list[dict]:
    """The flat scoreboard rows for the API, composite DESC with UNTESTED (NULL composite) last, account as the
    stable tiebreak. top_movers JSON is parsed back to a list. Defensive: a DB without the additive migration
    yields [] (honest empty panel), never a 500."""
    try:
        rows = store.rows(
            """
            SELECT account, platform, n_calls, n_resolved, n_echo, hit_rate, base_hit_rate, brier,
                   brier_skill_score, calibration_error, ev, avg_move_when_right, avg_lead_days, consistency,
                   composite, top_movers, last_call_ts, updated_at
            FROM authority_scoreboard
            ORDER BY (composite IS NULL), composite DESC, account
            """
        )
    except Exception:  # noqa: BLE001 — table absent on a not-yet-migrated DB → honest empty panel
        return []
    for r in rows:
        raw = r.get("top_movers")
        try:
            r["top_movers"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (ValueError, TypeError):
            r["top_movers"] = []
    return rows


__all__ = [
    "build_scoreboard",
    "load_calls",
    "load_scoreboard",
    "persist_calls",
    "persist_scoreboard",
    "prices_from_bars",
]
