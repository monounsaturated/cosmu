# intent: the Modal HEAVY-COMPUTE lane — run beefy engine jobs (cohort gate sweeps, the ML-ordered
# autonomous cycle, ingest, paper-mark) off the M2 and off the small Railway box. Same code, same DB,
# bigger CPU/RAM, scale-to-zero (~$0 idle). Driven by `modal run` from Claude Code or a cloud session.
# inputs: a Modal Secret named "cosmu-engine" (DATABASE_URL, XAI_API_KEY, FRED_API_KEY, APP_ENV=production …),
#         created from .env.local via scripts/sync_modal_secret.py.
# outputs: the engine command's exit code; all writes go to the SAME Supabase the backend uses.
# invariants: NEVER fires a live order (these are the same deterministic research/ingest entrypoints the
#             Railway crons run); secrets arrive via Modal Secret env injection, never committed; no LLM in
#             the gate/money path (the engine enforces that — this lane just runs it on more compute).

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import modal

# apps/engine — the pip-installable engine package lives here (same source Railway ships).
ENGINE_DIR = Path(__file__).resolve().parent.parent

app = modal.App("cosmu-engine")

# Build the image from the engine source, exactly like Railway's Dockerfile: copy the tree, then `pip install .`
# so `cosmu` is a real importable package (no PYTHONPATH gymnastics, no dep drift — the image IS the lockfile).
image = (
    modal.Image.debian_slim(python_version="3.12")
    .add_local_dir(
        str(ENGINE_DIR),
        remote_path="/root/engine",
        copy=True,  # materialize into the layer so the next run_commands can see it
        ignore=["**/__pycache__", "**/*.pyc", "tests/**", "remote/**"],
    )
    .run_commands("pip install '/root/engine[lake]'")  # [lake] = DuckDB, so jobs can read/write the R2 Parquet lake
)

# Runtime env: the SAME values the Railway backend reads. APP_ENV=production makes Settings read process env
# only (no committed file). Sync it from .env.local with:  python3 scripts/sync_modal_secret.py
engine_secret = modal.Secret.from_name("cosmu-engine")

# Beefy defaults for a sweep; tune per job. Bursty → scale-to-zero between runs (~$0 idle).
_HEAVY = dict(image=image, secrets=[engine_secret], timeout=60 * 60, cpu=4.0, memory=8192)
# Lake jobs scan/write the 13.5M-row Parquet hoard (LunarCrush ~99%) — 32GB so a partitioned COPY or a deep
# DuckDB scan never spills to swap. Same image/secret; the R2_* creds in the secret make the lake reachable.
_LAKE = dict(image=image, secrets=[engine_secret], timeout=60 * 60, cpu=4.0, memory=32768)


def _run(module_args: list[str], *, extra_env: dict[str, str] | None = None) -> int:
    """Run `python -m <module> [args…]` against the installed engine, streaming output back to the caller.
    `extra_env` overrides process env for THIS run only (e.g. ALT_DATA_BACKEND=parquet for a lake read) —
    never the shared secret, so the ingest/gate crons keep their default (Postgres) backend."""
    env = {**os.environ}
    env.setdefault("APP_ENV", "production")  # process-env secrets only, like the deployed engine
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run([sys.executable, "-m", *module_args], cwd="/root/engine", env=env)
    return proc.returncode


@app.function(**_HEAVY)
def gate_sweep() -> int:
    """Full autonomous cycle on REAL data: ingest → author → ML-ordered screen → deterministic gate/FDR →
    fund SIM survivors → recommendations. Mirrors the Railway 4h cron, with more CPU/RAM for a bigger cohort.
    This is where the tabular SURVIVAL model is exercised/retrained as labeled outcomes accrue."""
    return _run(["cosmu.master.scheduler"])


@app.function(**_HEAVY)
def ingest() -> int:
    """Free-data INGEST ONLY (mirrors the 6h Railway cron). The leaky cross-asset gate is DEFAULT OFF;
    pass --cross-asset-gate to opt in. Honest BH-FDR gate path (promote_cohort) runs via gate_sweep."""
    return _run(["cosmu.research.loop", "--ingest"])


@app.function(**_HEAVY)
def paper_mark() -> int:
    """Re-mark held SIM positions against the latest real close (paper clock, paper-only, no orders)."""
    return _run(["cosmu.orchestrator.loop"])


@app.function(**_HEAVY)
def cost_refresh() -> int:
    """Fetch live vendor spend (OpenRouter, Railway, Modal, xAI ledger), check budget thresholds,
    emit Slack alerts + recommendation rows. Mirrors the 6h Railway cron."""
    return _run(["cosmu.costs.refresh"])


@app.function(**_HEAVY)
def perp_gate_sweep() -> int:
    """Run the funding-dispersion strategy through the cost-scenario grid (OKX/Kraken Futures fees ×
    funding regimes). Reports skew/tail/cost_ratio per scenario — the Phase 0 P0.6 perp cost surface.
    Needs the offline funding cache; run `ingest` first to populate it (or funding will be empty)."""
    return _run(["cosmu.research.perp_gate_sweep"])


@app.function(**_LAKE)
def export_lake() -> int:
    """Refresh the COLD R2 Parquet lake from Postgres, OFF the operator's Mac. DuckDB's postgres-scanner streams
    alt_data → Hive-partitioned Parquet on r2://<bucket> in one COPY; idempotent (OVERWRITE). 32GB + the
    streamed write means the LunarCrush-dominated 13.5M rows never thrash. Needs R2_* + DATABASE_URL in the secret."""
    return _run(["cosmu.data.export_alt_parquet"])


@app.function(**_LAKE)
def lake_run(module: str, args: list[str] | None = None) -> int:
    """Deep-ML hatch: run any engine module with alt-data READS routed to the R2 lake (ALT_DATA_BACKEND=parquet
    for THIS process only — never the shared secret, so ingest/gate keep writing Postgres). DuckDB scans the
    columnar lake with predicate pushdown. NOTE: bar series still load from the local cache (not yet on R2), so
    bar-dependent sweeps (matrix_search) need bars-on-R2 first; alt-data-only research works today.
    e.g. modal run apps/engine/remote/app.py --job lake_run --module cosmu.research.scan_signals"""
    return _run([module, *(args or [])], extra_env={"ALT_DATA_BACKEND": "parquet"})


@app.function(image=image, secrets=[engine_secret], timeout=10 * 60, cpu=2.0, memory=4096)
def lake_smoke() -> int:
    """Prove the R2 cold lake is READABLE from Modal compute: build the cold store from the secret's R2 creds,
    count rows + read one PIT series. No flag flip, no writes. Non-zero exit if the lake is unreachable/empty
    (e.g. R2_* missing from the secret, or export_lake never ran)."""
    from datetime import UTC, datetime

    from cosmu.config.settings import get_settings
    from cosmu.data.providers.parquet_store import ParquetAltDataStore

    cold = ParquetAltDataStore.from_settings(get_settings())
    if not str(cold.root).startswith(("r2://", "s3://")):
        print(f"[lake_smoke] NOT REMOTE root={cold.root} — R2_* missing from the Modal secret (run sync_modal_secret.py)")
        return 1
    con = cold.conn()
    rows = int(con.execute(f"SELECT count(*) FROM read_parquet('{cold.root}/alt_data/**/*.parquet')").fetchone()[0])
    probe = cold.read_asof("defillama", "MARKET", "defi_tvl", datetime.now(UTC))
    print(f"[lake_smoke] root={cold.root} rows={rows:,} defi_tvl_points={len(probe)} last={probe[-1].value if probe else None}")
    return 0 if rows > 0 else 1


@app.function(**_HEAVY)
def run_module(module: str, args: list[str] | None = None) -> int:
    """Escape hatch: run any engine module as `python -m <module> [args…]` on Modal compute.
    e.g. modal run apps/engine/remote/app.py --job run_module --module cosmu.research.gate"""
    return _run([module, *(args or [])])


@app.local_entrypoint()
def main(job: str = "gate_sweep", module: str = "", args: str = "") -> None:
    """`modal run apps/engine/remote/app.py [--job gate_sweep|ingest|perp_gate_sweep|paper_mark|cost_refresh|
    export_lake|lake_smoke|lake_run|run_module]`. For run_module/lake_run pass --module cosmu.x.y and optional
    --args "--flag value" (space-split). export_lake refreshes the R2 lake; lake_smoke verifies R2 read access."""
    jobs = {
        "gate_sweep": gate_sweep,
        "ingest": ingest,
        "paper_mark": paper_mark,
        "forward_mark": paper_mark,  # legacy alias (pre-2026-06-11 vocabulary) — same job
        "cost_refresh": cost_refresh,
        "perp_gate_sweep": perp_gate_sweep,
        "export_lake": export_lake,
        "lake_smoke": lake_smoke,
    }
    if job in ("run_module", "lake_run"):
        fn = run_module if job == "run_module" else lake_run
        code = fn.remote(module, args.split() if args else [])
    elif job in jobs:
        code = jobs[job].remote()
    else:
        raise SystemExit(f"unknown job {job!r}; choose {sorted(jobs) + ['run_module', 'lake_run']}")
    print(f"[modal] job={job} exit={code}")
    if code:
        raise SystemExit(code)
