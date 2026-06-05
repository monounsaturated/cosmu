# intent: the STANDARDIZED scrape path for sources with NO API (niche sentiment sites, project docs, forum
# threads) — a documented seam where a Claude-Code / Cowork agent does the messy fetch+extract ONCE, writes
# point-in-time structured rows, and those rows flow through the EXACT SAME ingest/dedup/point-in-time store
# as every API source; inputs: agent-written `ScrapedRecord` JSONL; outputs: AltDataPoints conforming to the
# AltDataProvider seam; invariants: the scrape stamps `available_at` = when the agent actually read the page
# (point-in-time, no back-dating → no look-ahead), records are append-only, a missing/empty scrape dir yields
# [] (honest 'no data', never a fabricated read), and NO live scraping happens here — the fetch+extract is a
# deliberately-stubbed manual/agent step (see `.claude/skills/manage-data` "Scrape path"). This file is the
# CONTRACT + the store-side adapter; it is offline-testable (point it at a fixture dir).

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from cosmu.data.altdata import AltDataPoint

# Bump when the scrape record schema or the extraction convention changes, so a gate-passed survivor built on
# a scraped feature stays reproducible (mirrors the standardize.py TRANSFORM_VERSION discipline).
SCRAPE_TRANSFORM_VERSION = "scrape-stub-v1"


class ScrapedRecord(BaseModel):
    """The ONE structured row a Claude-Code / Cowork scrape must emit per observation. The agent's job is to
    turn an unstructured page into a list of these — nothing downstream needs to know the page existed.

    `available_at` MUST be the moment the agent read the page (point-in-time). Never back-date it to the
    article's own timestamp unless you can prove you'd have seen it then — back-dating manufactures
    look-ahead. `value` is the already-numeric feature (the agent does the text→number step at scrape time,
    the LLM-adapter discipline: standardize ONCE, never on the gate path)."""

    source: str  # e.g. "glassnode_docs", "obscure_sentiment_site"
    symbol: str  # the instrument, or "MARKET" for a market-wide read
    metric: str  # the SEMANTIC feature name (must be a feature_registry name to be gate-usable)
    ts: datetime  # the observation time the value refers to
    available_at: datetime  # when the agent actually read it (point-in-time stamp)
    value: float
    url: str = ""  # provenance: the page scraped (audit trail)
    note: str = Field(default="", description="optional extraction note for audit")


class ScrapedAltDataProvider:
    """Store-side adapter: reads append-only `ScrapedRecord` JSONL from a scrape dir and serves it through the
    standard `AltDataProvider` seam, so a scraped feature ingests via the SAME `ingest_numeric` → dedup →
    point-in-time store path as any API source. One file per source: `<scrape_dir>/<source>.jsonl`, each line
    one record. A missing dir / no matching rows → [] (honest degradation). NO network — the fetch+extract is
    done out-of-band by an agent (stubbed; see the skill)."""

    def __init__(self, scrape_dir: Path | str = ".cosmu/scrape") -> None:
        self.scrape_dir = Path(scrape_dir)

    def fetch_series(self, symbol: str, metric: str, *, limit: int, since: "datetime | None" = None) -> list[AltDataPoint]:
        if not self.scrape_dir.exists():
            return []
        out: list[AltDataPoint] = []
        for path in sorted(self.scrape_dir.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    rec = ScrapedRecord.model_validate_json(line)
                except Exception:  # noqa: BLE001 — one malformed row never aborts the read
                    continue
                if rec.symbol != symbol or rec.metric != metric:
                    continue
                out.append(AltDataPoint(ts=rec.ts, available_at=rec.available_at, value=float(rec.value)))
        out.sort(key=lambda p: p.ts)
        return out[-limit:] if limit and len(out) > limit else out


def write_scraped_records(scrape_dir: Path | str, source: str, records: list[ScrapedRecord]) -> int:
    """Append agent-extracted records to `<scrape_dir>/<source>.jsonl` (append-only, the same discipline as
    the alt store). This is the ONE function the scrape step calls after extraction. Returns rows written."""
    base = Path(scrape_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{source}.jsonl"
    with path.open("a") as fh:
        for rec in records:
            fh.write(rec.model_dump_json() + "\n")
    return len(records)


def stub_scrape(source: str, symbol: str, metric: str, url: str) -> list[ScrapedRecord]:
    """STUB — the deliberately-unbuilt fetch+extract step. In production a Claude-Code / Cowork agent fetches
    `url`, extracts observations, and returns `ScrapedRecord`s (stamping `available_at = now`). Here it
    returns [] so the path is wired end-to-end without doing live scraping. Replace the body with the agent
    call when a specific no-API source is needed (see the manage-data skill's "Scrape path")."""
    _ = (source, symbol, metric, url, datetime.now(tz=UTC))  # documented signature; intentionally inert
    return []
