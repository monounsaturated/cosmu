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
)


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
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
