# intent: the APPEND-ONLY, point-in-time sink for the Deribit forward logger. Every poll flattens one ChainSnapshot
# into one row PER instrument (carrying the PIT `capture_ts` WE stamped) and APPENDS it as newline-delimited JSON,
# partitioned `deribit_options/currency=<CCY>/date=<YYYY-MM-DD>/quotes.jsonl`. Forward-only & never-re-pull is the
# logger's contract; the sink only ever appends — it never rewrites a prior row, so the on-disk file is an immutable
# capture log (a vendor revision would be a NEW row at a later capture_ts, never an overwrite). The row schema is
# 1:1 with the NOT-yet-applied migration (knowledge/migrations/2026-06-29_deribit_option_quotes.sql) so the operator
# can COPY the JSONL straight into Postgres, and the R2 mirror reuses the EXACT boto3 client the cold tier uses
# (cosmu.data.bar_archive._r2_client). Local JSONL is the default $0 substrate; the R2 upload is operator-run (the
# cron is registered-but-not-deployed). Lazy boto3 import keeps the base deps lean.

from __future__ import annotations

import json
from pathlib import Path

from cosmu.options.chain import ChainSnapshot

_PREFIX = "deribit_options"


def snapshot_to_rows(snapshot: ChainSnapshot) -> list[dict]:
    """Flatten a ChainSnapshot into append-ready rows (one per instrument). Greeks are spread into nullable
    columns; an unenriched quote simply has null sizes/greeks. `capture_ts` is the PIT stamp on every row."""
    asof = snapshot.asof_iso
    rows: list[dict] = []
    for q in snapshot.quotes:
        g = q.greeks or {}
        rows.append(
            {
                "capture_ts": asof,
                "currency": snapshot.currency,
                "index_price": snapshot.index_price,
                "dvol": snapshot.dvol,
                "instrument": q.instrument,
                "expiry": q.expiry.isoformat(),
                "strike": q.strike,
                "option_type": "C" if q.is_call else "P",
                "bid_price": q.bid_price,
                "ask_price": q.ask_price,
                "mark_price": q.mark_price,
                "mark_iv": q.mark_iv,
                "bid_size": q.bid_size,
                "ask_size": q.ask_size,
                "open_interest": q.open_interest,
                "volume": q.volume,
                "underlying_price": q.underlying_price,
                "delta": g.get("delta"),
                "gamma": g.get("gamma"),
                "vega": g.get("vega"),
                "theta": g.get("theta"),
            }
        )
    return rows


class LocalJsonlSink:
    """Append-only local JSONL sink, partitioned by currency + UTC capture date. `append` returns the number of
    rows written and NEVER rewrites an existing file — re-running a poll simply appends more capture rows (the
    forward-only logger is what guarantees we don't re-pull the same instant)."""

    def __init__(self, root: str | Path = ".cosmu/deribit_options") -> None:
        self.root = Path(root)

    def path_for(self, currency: str, capture_date: str) -> Path:
        return self.root / _PREFIX / f"currency={currency.upper()}" / f"date={capture_date}" / "quotes.jsonl"

    def append(self, snapshot: ChainSnapshot) -> int:
        rows = snapshot_to_rows(snapshot)
        if not rows:
            return 0
        capture_date = snapshot.asof_iso[:10]
        path = self.path_for(snapshot.currency, capture_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        return len(rows)


def r2_key(currency: str, capture_date: str) -> str:
    """The R2 object key mirroring the local partition: deribit_options/currency=<CCY>/date=<YYYY-MM-DD>/quotes.jsonl."""
    return f"{_PREFIX}/currency={currency.upper()}/date={capture_date}/quotes.jsonl"


def upload_day_to_r2(settings, root: str | Path, currency: str, capture_date: str) -> int:
    """Mirror ONE local day-partition to R2 (operator-run; NOT wired to a cron). Reuses the cold-tier boto3 client.
    Returns the byte count uploaded, or 0 if the local file is absent or R2 is not configured. Append-only on R2
    too: a re-upload OVERWRITES the object with the (superset) local file — the local JSONL is the source of truth.
    Lazy import of the cold-tier client keeps boto3 out of the base deps."""
    path = LocalJsonlSink(root).path_for(currency, capture_date)
    if not path.exists():
        return 0
    if not getattr(settings, "r2_bucket", None) or not getattr(settings, "r2_account_id", None):
        return 0
    from cosmu.data.bar_archive import (
        _r2_client,  # lazy: boto3 only where the operator runs the upload
    )

    body = path.read_bytes()
    s3 = _r2_client(settings)
    s3.put_object(Bucket=settings.r2_bucket, Key=r2_key(currency, capture_date), Body=body,
                  ContentType="application/x-ndjson")
    return len(body)
