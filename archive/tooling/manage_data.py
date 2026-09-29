#!/usr/bin/env python3
# intent: the operator entrypoint for the MANAGED-DATA capability — one CLI to fetch / backfill / verify /
# update both the alt-data store and the multi-venue bar cache, so data is a managed surface (not a pile of
# one-off scripts); inputs: the free providers (NO keys required; key-gated sources degrade to []) + the
# operator's stores (Postgres in prod, JSONL + bar cache locally); outputs: append counts (fetch/backfill/
# update) and a coverage report (verify); invariants: append-only + idempotent + point-in-time (a re-run
# writes 0), each (source,symbol,window) fetched ONCE, offline-safe (no network in tests). This is a THIN
# wrapper over cosmu.ingest.manage — the real RUN happens post-merge via cron/manual.
#
# Run (from the repo root):
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py list
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py verify                 # coverage report
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py verify --json          # machine-readable
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py update                 # one incremental pass (all sources)
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py fetch funding          # one source, incremental
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py backfill funding --days 730
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py backfill bars --days 730 --timeframe 1d
#   PYTHONPATH=apps/engine python3 scripts/manage_data.py backfill bars:kraken --symbols BTCUSDT

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python3 scripts/manage_data.py` without an explicit PYTHONPATH (mirrors the documented run).
_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.ingest.manage import _main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_main())
