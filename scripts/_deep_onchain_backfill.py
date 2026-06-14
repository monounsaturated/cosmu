"""One-off DEEP backfill of blockchain.com BTC on-chain fundamentals into the alt-data store.

The catalog's ingest BRIDGE (OnchainBlockchainIngestProvider) collapses the provider to a
single snapshot, so the scheduled `fetch onchain_blockchain` only forward-accrues. The provider
ITSELF (OnchainBlockchainSource.fetch_raw_series) returns the full daily series for any timespan.
This script pulls `timespan="all"` once and appends every historical point through the SAME
idempotent, point-in-time dedup primitive the production ingest uses (`_append_fresh`), with each
point's honest available_at = obs_day + 1 (the provider's PIT contract — NOT look-ahead).

Re-runnable: a second run appends 0 (dedup on (ts, available_at)). Reversible: every row is tagged
provider="blockchain.com". Free, no key.
"""
from __future__ import annotations

from datetime import UTC, datetime

from cosmu.data.sources.onchain_blockchain import METRIC_CHART_MAP, OnchainBlockchainSource
from cosmu.ingest.manage import DataManager
from cosmu.ingest.pipeline import _append_fresh

TIMESPAN = "all"  # blockchain.com returns full history since 2009 in one call


def main() -> None:
    mgr = DataManager()
    alt_store = mgr._get_store()  # prod PgAltDataStore (DATABASE_URL) or local AltDataStore
    now = datetime.now(UTC)
    print(f"deep on-chain backfill | timespan={TIMESPAN} | store={type(alt_store).__name__}")
    grand = 0
    for metric in METRIC_CHART_MAP:
        src = OnchainBlockchainSource(metric=metric, lookback_timespan=TIMESPAN)
        points = src.fetch_raw_series(now, limit=8000)
        if not points:
            print(f"  {metric:22} 0 points (API empty/unreachable) — skipped")
            continue
        before = len(points)
        first, last = points[0].ts.date().isoformat(), points[-1].ts.date().isoformat()
        _append_fresh(alt_store, "blockchain.com", "MARKET", metric, points)
        grand += before
        print(f"  {metric:22} served {before:5} pts  span {first}..{last}  (new rows deduped on append)")
    print(f"done. served {grand} total on-chain points (only genuinely-new (ts,available_at) rows persisted).")


if __name__ == "__main__":
    main()
