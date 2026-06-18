#!/usr/bin/env python3
"""Sync the Modal secret `cosmu-engine` from your local .env.local — one source of truth, no double-typing.

The Modal heavy-compute lane (apps/engine/remote/app.py) reads the SAME runtime env the Railway backend reads.
Rather than re-enter keys in the Modal dashboard, this reads .env.local, picks the keys the engine actually
needs, forces APP_ENV=production (so Settings reads process env only, like the deployed engine), and pushes
them into the Modal secret.

Usage:
    python3 scripts/sync_modal_secret.py            # sync from .env.local
    python3 scripts/sync_modal_secret.py --dry-run  # print the key names that would be pushed

Prereqs: `pip install modal` and `modal setup` (or MODAL_TOKEN_ID/MODAL_TOKEN_SECRET in env) done once.
Secrets are NEVER printed or committed — only key names are shown.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
SECRET_NAME = "cosmu-engine"

# The keys the Modal jobs need at runtime. DATABASE_URL is required; the rest are optional (the FREE gate runs
# with zero keys). Keep this list in step with cosmu/config/settings.py.
WANTED = (
    "DATABASE_URL",
    "DATABASE_SSL",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "FRED_API_KEY",
    "LUNARCRUSH_API_KEY",
    "POLYMARKET_TOKEN",
    # Cloudflare R2 creds — the cold tier needs these so the heavy lake jobs run on Modal compute, not the M2:
    # the DuckLake lane (cosmu.data.ducklake_store / age_out / retention → sync_lake, prune) AND the Parquet lane
    # (export_lake / lake_run / lake_smoke). Shipping the creds does NOT by itself flip a backend; ALT_DATA_BACKEND
    # is set explicitly below (=tiered for Modal research). Optional: absent → those lake jobs no-op.
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    # Runtime BARS-FROM-RAILWAY lane (cosmu/data/market.RemoteBarsProvider): when COSMU_BARS_URL is set the Modal
    # screen/paper clock fetches OHLCV from the Binance-reachable Railway EU engine instead of a bundled cache —
    # so the fleet is cacheless + account-swappable (no per-account bar cache to re-bundle). API_SECRET_KEY is the
    # x-api-key the provider presents to the (authed) /market/bars route. Absent → unchanged (keyless Binance).
    "COSMU_BARS_URL",
    "API_SECRET_KEY",
)


def _parse_env(path: Path) -> dict[str, str]:
    """Parse .env.local the SAME way python-dotenv / pydantic-settings does, so a synced secret matches what
    the local engine reads. The key fix over a naive split: an UNQUOTED value ends at its first ` #` inline
    comment (e.g. `DATABASE_URL=postgres://…   # Supabase` must NOT push the comment into the DB name — that
    breaks every Modal job). A quoted value is taken verbatim between the quotes (a literal `#` inside is kept)."""
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if val[:1] in ('"', "'"):
            quote = val[0]
            end = val.find(quote, 1)
            val = val[1:end] if end != -1 else val[1:]
        else:
            hash_pos = val.find(" #")  # inline comment on an unquoted value starts at the first space-hash
            if hash_pos != -1:
                val = val[:hash_pos]
            val = val.strip()
        out[key.strip()] = val
    return out


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if not ENV_FILE.exists():
        print(f"✗ {ENV_FILE} not found — create it from .env.example first.")
        return 1

    env = _parse_env(ENV_FILE)
    pairs = {k: env[k] for k in WANTED if env.get(k)}
    if not pairs.get("DATABASE_URL"):
        print("✗ DATABASE_URL missing/empty in .env.local — the Modal jobs need the Supabase URL.")
        return 1

    # Force production profile so the engine reads process env (the injected secret), never a file.
    pairs["APP_ENV"] = "production"
    # Modal is the HEAVY-RESEARCH lane: read the FULL-history cold tier (PG-hot ∪ DuckLake-cold). After the
    # Supabase prune, PG holds only the ~90d hot window, so research on the default 'pg' backend would see only
    # 90d — 'tiered' restores full history from the R2 lake. Money/UI read raw PG regardless; writes always go to
    # PG (hot_alt_store). Railway stays 'pg' (lean — no duckdb/R2 there).
    pairs["ALT_DATA_BACKEND"] = "tiered"

    print(f"→ syncing {len(pairs)} keys to Modal secret '{SECRET_NAME}': {', '.join(sorted(pairs))}")
    if dry_run:
        print("(dry-run — nothing pushed)")
        return 0

    cmd = ["modal", "secret", "create", "--force", SECRET_NAME, *[f"{k}={v}" for k, v in pairs.items()]]
    proc = subprocess.run(cmd)  # values passed as args to the modal CLI; not echoed by this script
    if proc.returncode == 0:
        print(f"✓ Modal secret '{SECRET_NAME}' updated. Run a job: modal run apps/engine/remote/app.py")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
