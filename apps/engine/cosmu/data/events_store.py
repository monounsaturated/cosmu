# intent: the POINT-IN-TIME UNSTRUCTURED-EVENT store (realtime-data-lane epic §5) — typed MarketEvent records
# (news headline / tweet / Polymarket move / OSINT observation) persisted append-only with TWO clocks that are
# never conflated: `ts` = the event's OWN publish/claim time (the event-study x-axis) and `available_at` = when
# WE received it (the only honest trading-feature x-axis; a scraped archive is honestly "available at scrape
# time", never backdated). inputs: MarketEvent batches from ingest bridges / the future realtime worker;
# outputs: deduped, ts-ordered event timelines per provider. invariants: append-only; deduped by
# (provider, content_hash) so re-running ingest never double-counts; no fabrication (an empty pull appends
# nothing); offline-testable (JSONL twin mirrors the alt_data dual-store pattern); raw text stays SMALL
# (title-level — full bodies are scored-and-discarded elsewhere, HANDOFF §6b). Numeric features derived from
# events flow into alt_data as ordinary PIT features; this store is the EVIDENCE the event-study harness and
# the credibility pipeline (mind/authority.py's event timeline) read.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["MarketEvent", "EventsStore", "PgEventsStore", "content_hash_for"]


def content_hash_for(title: str, ts: datetime) -> str:
    """Stable dedup key: normalized title + calendar day. The same headline syndicated across outlets within a
    day collapses to one hash (RavenPack-style same-story dedup happens later via clustering — this only stops
    LITERAL re-ingestion duplicates), while a genuinely recurring headline on a later day is a new event."""
    norm = " ".join(title.lower().split())
    return hashlib.sha256(f"{norm}|{ts.date().isoformat()}".encode()).hexdigest()


@dataclass(frozen=True)
class MarketEvent:
    """One typed unstructured event. Extraction fields (event_type/direction/magnitude/confidence/novelty/
    root_event_id) are None until the LLM extractor / clusterer fills them — a raw recorded event is already
    valid and storable (record first, enrich later; the receipt timestamp must never wait on an LLM)."""

    provider: str                      # gdelt | cryptopanic | rss | xai_twitter | polymarket | voices | ...
    source: str                        # handle / outlet / author within the provider ("" = unknown)
    symbols: tuple[str, ...]           # affected symbols; () = market-wide
    ts: datetime                       # the event's own publish/claim time (event-study clock)
    available_at: datetime             # when WE knew it (receipt/scrape time — the trading clock)
    title: str                         # the small raw text (headline / tweet / move description)
    content_hash: str = ""             # filled from title+ts when empty (see content_hash_for)
    event_type: str | None = None      # typed taxonomy from the extractor (None = not yet extracted)
    root_event_id: str | None = None   # cluster id; the earliest member is the breaker
    novelty: float | None = None       # 1.0 = first report of its cluster, decaying for echoes
    direction: int | None = None       # extractor's claim: -1 | 0 | +1
    magnitude: float | None = None     # extractor's surprise/magnitude in [0, 1]
    confidence: float | None = None    # extractor's confidence in [0, 1]
    extractor_version: str | None = None  # frozen prompt/schema version (reproducibility pin)

    def hydrated(self) -> MarketEvent:
        return self if self.content_hash else replace(self, content_hash=content_hash_for(self.title, self.ts))


def _to_row(e: MarketEvent) -> dict[str, Any]:
    return {
        "provider": e.provider, "source": e.source, "symbols": list(e.symbols),
        "ts": e.ts.isoformat(), "available_at": e.available_at.isoformat(),
        "title": e.title, "content_hash": e.content_hash, "event_type": e.event_type,
        "root_event_id": e.root_event_id, "novelty": e.novelty, "direction": e.direction,
        "magnitude": e.magnitude, "confidence": e.confidence, "extractor_version": e.extractor_version,
    }


def _from_row(row: dict[str, Any]) -> MarketEvent:
    raw_symbols = row.get("symbols") or []
    if isinstance(raw_symbols, str):  # the PG column stores a JSON string
        raw_symbols = json.loads(raw_symbols) if raw_symbols else []
    return MarketEvent(
        provider=str(row["provider"]), source=str(row.get("source") or ""),
        symbols=tuple(str(s) for s in raw_symbols),
        ts=datetime.fromisoformat(str(row["ts"])),
        available_at=datetime.fromisoformat(str(row["available_at"])),
        title=str(row["title"]), content_hash=str(row["content_hash"]),
        event_type=row.get("event_type"), root_event_id=row.get("root_event_id"),
        novelty=float(row["novelty"]) if row.get("novelty") is not None else None,
        direction=int(row["direction"]) if row.get("direction") is not None else None,
        magnitude=float(row["magnitude"]) if row.get("magnitude") is not None else None,
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        extractor_version=row.get("extractor_version"),
    )


@dataclass
class EventsStore:
    """JSONL twin of the Postgres `market_events` table — one append-only file per provider, deduped by
    content_hash, so the event-study harness runs fully offline (the alt_data AltDataStore pattern)."""

    root: Path | str = ".cosmu/events"
    _hashes: dict[str, set[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str) -> Path:
        return Path(self.root) / f"{provider.replace('/', '')}.jsonl"

    def _known(self, provider: str) -> set[str]:
        if provider not in self._hashes:
            path = self._path(provider)
            hashes: set[str] = set()
            if path.exists():
                for line in path.read_text().splitlines():
                    if line:
                        hashes.add(json.loads(line)["content_hash"])
            self._hashes[provider] = hashes
        return self._hashes[provider]

    def append(self, events: list[MarketEvent]) -> int:
        """Append the NEW events (dedup on (provider, content_hash)); returns how many were actually written —
        a re-run over the same pull writes 0."""
        written = 0
        by_provider: dict[str, list[MarketEvent]] = {}
        for e in events:
            e = e.hydrated()
            by_provider.setdefault(e.provider, []).append(e)
        for provider, batch in by_provider.items():
            known = self._known(provider)
            with self._path(provider).open("a") as fh:
                for e in batch:
                    if e.content_hash in known:  # dedups within the batch too, not just vs disk
                        continue
                    fh.write(json.dumps(_to_row(e), separators=(",", ":")) + "\n")
                    known.add(e.content_hash)
                    written += 1
        return written

    def read(self, provider: str, *, since: datetime | None = None, until: datetime | None = None) -> list[MarketEvent]:
        """All stored events for a provider, ts-ascending, optionally clipped to [since, until]."""
        path = self._path(provider)
        if not path.exists():
            return []
        out: list[MarketEvent] = []
        for line in path.read_text().splitlines():
            if not line:
                continue
            e = _from_row(json.loads(line))
            if since is not None and e.ts < since:
                continue
            if until is not None and e.ts > until:
                continue
            out.append(e)
        return sorted(out, key=lambda e: (e.ts, e.content_hash))


class PgEventsStore:
    """Production twin backed by the `market_events` table (knowledge/schema*.sql). Same append/read contract
    as the JSONL store; dedup enforced both here (pre-filter) and by the table's UNIQUE(provider, content_hash)."""

    def __init__(self, store: Any) -> None:  # knowledge.store.Store (Any avoids the import cycle)
        self.store = store

    def append(self, events: list[MarketEvent]) -> int:
        from cosmu.knowledge.store import utcnow

        events = [e.hydrated() for e in events]
        if not events:
            return 0
        written = 0
        now = utcnow()
        by_provider: dict[str, list[MarketEvent]] = {}
        for e in events:
            by_provider.setdefault(e.provider, []).append(e)
        for provider, batch in by_provider.items():
            hashes = sorted({e.content_hash for e in batch})
            placeholders = ",".join("?" for _ in hashes)
            existing = {
                r["content_hash"]
                for r in self.store.rows(
                    f"SELECT content_hash FROM market_events WHERE provider = ? AND content_hash IN ({placeholders})",
                    (provider, *hashes),
                )
            }
            seen = set(existing)
            rows = []
            for e in batch:
                if e.content_hash in seen:
                    continue
                seen.add(e.content_hash)
                rows.append((
                    e.provider, e.source, json.dumps(list(e.symbols)), e.ts.isoformat(),
                    e.available_at.isoformat(), e.title, e.content_hash, e.event_type,
                    e.root_event_id, e.novelty, e.direction, e.magnitude, e.confidence,
                    e.extractor_version, now,
                ))
            if not rows:
                continue
            with self.store.batch() as writer:
                writer.insert_many(
                    "market_events",
                    ["provider", "source", "symbols", "ts", "available_at", "title", "content_hash",
                     "event_type", "root_event_id", "novelty", "direction", "magnitude", "confidence",
                     "extractor_version", "ingested_at"],
                    rows,
                )
            written += len(rows)
        return written

    def read(self, provider: str, *, since: datetime | None = None, until: datetime | None = None) -> list[MarketEvent]:
        sql = "SELECT * FROM market_events WHERE provider = ?"
        args: list[Any] = [provider]
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since.isoformat())
        if until is not None:
            sql += " AND ts <= ?"
            args.append(until.isoformat())
        sql += " ORDER BY ts, content_hash"
        return [_from_row(dict(r)) for r in self.store.rows(sql, tuple(args))]
