# intent: PERSIST + READ the authority-conviction review queue. The producer upserts proposals by their
# deterministic proposal_id (idempotent — re-running a pass over the same call updates the same row, never a
# duplicate); the /conviction API reads them back, highest-authority first. Schema-probe gated: when the
# `conviction_proposals` table is absent (pre-migration prod) every write NO-OPS and every read returns [] — so
# the feature degrades to an honest-empty queue, byte-identical to before. NOTHING here arms or moves money; the
# stored `status` is always 'proposed'.

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from cosmu.conviction.models import (
    AuthorityEvidence,
    ConvictionProposal,
    Direction,
    TopMover,
    quantize_usd,
)
from cosmu.knowledge.store import Store, conviction_proposals_available, utcnow


def upsert_proposals(store: Store, proposals: list[ConvictionProposal]) -> int:
    """Upsert proposals by proposal_id (idempotent). No-ops (returns 0) when the table is absent. Returns the
    number of rows written."""
    if not proposals or not conviction_proposals_available(store):
        return 0
    now = utcnow()
    written = 0
    with store.batch() as writer:
        for p in proposals:
            evidence_json = json.dumps(p.to_dict()["evidence"], sort_keys=True)
            writer.execute(
                """
                INSERT INTO conviction_proposals (proposal_id, account, asset, direction, size_usd,
                  max_loss_usd, authority_score, expiry, thesis, status, source, evidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (proposal_id) DO UPDATE SET
                  account = excluded.account, asset = excluded.asset, direction = excluded.direction,
                  size_usd = excluded.size_usd, max_loss_usd = excluded.max_loss_usd,
                  authority_score = excluded.authority_score, expiry = excluded.expiry,
                  thesis = excluded.thesis, source = excluded.source, evidence = excluded.evidence,
                  updated_at = excluded.updated_at
                """,
                (
                    p.proposal_id, p.account, p.asset, p.direction.value, str(p.size_usd),
                    str(p.max_loss_usd), float(p.authority_score), p.expiry.isoformat(), p.thesis,
                    p.status, p.source, evidence_json, p.created_at.isoformat(), now,
                ),
            )
            written += 1
    return written


def read_proposals(
    store: Store,
    *,
    limit: int = 50,
    include_expired: bool = False,
    now: datetime | None = None,
) -> list[ConvictionProposal]:
    """The review queue, highest authority first then newest. Honest-empty ([]) when the table is absent. By
    default drops expired proposals (a stale call the human never armed); pass include_expired to see them all."""
    if not conviction_proposals_available(store):
        return []
    with store.reading():
        rows = store.rows(
            "SELECT * FROM conviction_proposals ORDER BY authority_score DESC, created_at DESC, proposal_id "
            "LIMIT ?",
            (max(1, min(limit, 500)),),
        )
    out = [_proposal_from_row(r) for r in rows]
    if not include_expired:
        out = [p for p in out if not p.is_expired(now)]
    return out


def _proposal_from_row(row: dict) -> ConvictionProposal:
    ev = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else (row["evidence"] or {})
    movers = tuple(
        TopMover(
            entity=str(m["entity"]),
            direction=str(m["direction"]),
            realized_return=float(m["realized_return"]),
            ts=datetime.fromisoformat(m["ts"]),
        )
        for m in ev.get("top_movers", [])
    )
    evidence = AuthorityEvidence(
        account=str(ev.get("account", row["account"])),
        authority_score=float(ev.get("authority_score", row["authority_score"])),
        skill=float(ev.get("skill", 0.0)),
        ev_per_call=float(ev.get("ev_per_call", 0.0)),
        brier_skill_score=float(ev.get("brier_skill_score", 0.0)),
        avg_hit_magnitude=float(ev.get("avg_hit_magnitude", 0.0)),
        n_resolved=int(ev.get("n_resolved", 0)),
        citation_authority=float(ev.get("citation_authority", 0.0)),
        top_movers=movers,
        source_quote=str(ev.get("source_quote", "")),
        source_url=str(ev.get("source_url", "")),
        is_primary=bool(ev.get("is_primary", True)),
        lead_lag=str(ev.get("lead_lag", "none")),
    )
    return ConvictionProposal(
        proposal_id=str(row["proposal_id"]),
        account=str(row["account"]),
        asset=str(row["asset"]),
        direction=Direction(str(row["direction"])),
        # Re-quantize to cents: SQLite's NUMERIC affinity coerces "12.00"→12.0 on store, so round-trip through
        # the canonical cents form to keep the displayed amount stable across SQLite (tests) and Postgres (prod).
        size_usd=quantize_usd(Decimal(str(row["size_usd"]))),
        max_loss_usd=quantize_usd(Decimal(str(row["max_loss_usd"]))),
        expiry=datetime.fromisoformat(str(row["expiry"])),
        thesis=str(row["thesis"]),
        evidence=evidence,
        created_at=datetime.fromisoformat(str(row["created_at"])),
        status="proposed",
        source=str(row["source"]),
    )
