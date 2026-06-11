# intent: the EVENT CORPUS bridge (realtime-data-lane epic §4.3) — turn raw text corpora into the typed,
# CLUSTERED MarketEvent timeline the event-study harness and the credibility pipeline consume. Three jobs:
# (1) load generic JSONL corpora (the GDELT GKG pull, a voices dump, a Polymarket-move log) into MarketEvent
# records with HONEST availability (a historical feed with true publish stamps may declare available_at = ts;
# a scraped archive must declare available_at = scrape time — the loader forces the caller to choose, no
# silent default backdating); (2) adapt the existing NewsItem provider shape; (3) cluster events into ROOT
# events RavenPack-style — the earliest member of a similarity×time cluster is the BREAKER (novelty 1.0),
# later members are ECHOES with decaying novelty — using the deterministic keyless embedding the graveyard
# memory already owns (knowledge/memory.embed). invariants: PURE + offline + deterministic (no LLM, no
# network, no wall clock); clustering is greedy in (ts, content_hash) order so a re-run reproduces the same
# root ids; echoes are never dropped (staleness is a SIGNAL — Tetlock 2011 — not noise to discard).

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from cosmu.data.events_store import MarketEvent
from cosmu.data.providers._types import NewsItem
from cosmu.knowledge.memory import cosine, embed

__all__ = ["cluster_root_events", "events_from_jsonl", "events_from_news_items"]


def events_from_news_items(
    items: list[NewsItem], *, symbol: str, provider: str = "gdelt", source: str = ""
) -> list[MarketEvent]:
    """Adapt the existing NewsProvider shape. NewsItem already carries its own honest available_at."""
    return [
        MarketEvent(
            provider=provider, source=source, symbols=(symbol,),
            ts=i.ts, available_at=i.available_at, title=i.headline,
        ).hydrated()
        for i in items
    ]


def events_from_jsonl(
    path: Path | str,
    *,
    provider: str,
    availability: Literal["publish-time"] | datetime,
) -> list[MarketEvent]:
    """Load a generic corpus: one JSON object per line with `ts` (ISO), `title`, and optionally `symbol` or
    `symbols`, `source`, `event_type`, `available_at` (ISO).

    `availability` is DELIBERATELY required: pass "publish-time" ONLY for a feed whose stamps are true
    point-in-time publish times (GDELT seendate); pass the scrape datetime for any archive collected after
    the fact (the local-Chrome tweet lane) — backdating a scrape into a trading feature is the look-ahead
    this argument exists to prevent. A row's own `available_at` field, when present, wins over either."""
    out: list[MarketEvent] = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ts = datetime.fromisoformat(str(row["ts"]))
        if row.get("available_at"):
            available = datetime.fromisoformat(str(row["available_at"]))
        elif availability == "publish-time":
            available = ts
        else:
            available = availability
        symbols = row.get("symbols") or ([row["symbol"]] if row.get("symbol") else [])
        out.append(
            MarketEvent(
                provider=provider, source=str(row.get("source") or ""),
                symbols=tuple(str(s) for s in symbols), ts=ts, available_at=available,
                title=str(row["title"]), event_type=row.get("event_type"),
            ).hydrated()
        )
    return sorted(out, key=lambda e: (e.ts, e.content_hash))


def cluster_root_events(
    events: list[MarketEvent],
    *,
    window_hours: float = 24.0,
    threshold: float = 0.60,
) -> list[MarketEvent]:
    """Assign `root_event_id` + `novelty` by greedy similarity×time clustering: an event joins the most
    similar OPEN cluster (cosine vs the BREAKER's title embedding ≥ threshold, breaker within window_hours);
    otherwise it founds a new cluster as its own root. Novelty decays 1/(1+k) for the k-th echo. The
    centroid is pinned to the breaker (never drifts), so 'is this the same story?' is always judged against
    the first report. Deterministic: events are processed in (ts, content_hash) order."""
    ordered = sorted((e.hydrated() for e in events), key=lambda e: (e.ts, e.content_hash))
    window = timedelta(hours=window_hours)
    # Open clusters: (root_id, breaker_vec, breaker_ts, n_members) — pruned as time advances.
    open_clusters: list[tuple[str, list[float], datetime, int]] = []
    out: list[MarketEvent] = []
    for e in ordered:
        open_clusters = [c for c in open_clusters if e.ts - c[2] <= window]
        vec = embed(e.title)
        best_i, best_sim = -1, threshold
        for i, (_root, bvec, _bts, _n) in enumerate(open_clusters):
            sim = cosine(vec, bvec)
            if sim >= best_sim:
                best_i, best_sim = i, sim
        if best_i >= 0:
            root, bvec, bts, n = open_clusters[best_i]
            open_clusters[best_i] = (root, bvec, bts, n + 1)
            out.append(replace(e, root_event_id=root, novelty=1.0 / (1.0 + n)))
        else:
            open_clusters.append((e.content_hash, vec, e.ts, 1))
            out.append(replace(e, root_event_id=e.content_hash, novelty=1.0))
    return out
