# intent: the Modal HEAVY-COMPUTE lane — run beefy engine jobs (cohort gate sweeps, the ML-ordered
# autonomous cycle, ingest, forward-mark) off the M2 and off the small Railway box. Same code, same DB,
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
    .run_commands("pip install /root/engine")
)

# Runtime env: the SAME values the Railway backend reads. APP_ENV=production makes Settings read process env
# only (no committed file). Sync it from .env.local with:  python3 scripts/sync_modal_secret.py
engine_secret = modal.Secret.from_name("cosmu-engine")

# Beefy defaults for a sweep; tune per job. Bursty → scale-to-zero between runs (~$0 idle).
_HEAVY = dict(image=image, secrets=[engine_secret], timeout=60 * 60, cpu=4.0, memory=8192)


def _run(module_args: list[str]) -> int:
    """Run `python -m <module> [args…]` against the installed engine, streaming output back to the caller."""
    env = {**os.environ}
    env.setdefault("APP_ENV", "production")  # process-env secrets only, like the deployed engine
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
def forward_mark() -> int:
    """Re-mark held SIM positions against the latest real close (forward-test clock, paper-only, no orders)."""
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


@app.function(**_HEAVY)
def run_module(module: str, args: list[str] | None = None) -> int:
    """Escape hatch: run any engine module as `python -m <module> [args…]` on Modal compute.
    e.g. modal run apps/engine/remote/app.py --job run_module --module cosmu.research.gate"""
    return _run([module, *(args or [])])


@app.local_entrypoint()
def main(job: str = "gate_sweep", module: str = "", args: str = "") -> None:
    """`modal run apps/engine/remote/app.py [--job gate_sweep|ingest|perp_gate_sweep|forward_mark|cost_refresh|run_module]`.
    For run_module pass --module cosmu.x.y and optional --args "--flag value" (space-split)."""
    jobs = {
        "gate_sweep": gate_sweep,
        "ingest": ingest,
        "forward_mark": forward_mark,
        "cost_refresh": cost_refresh,
        "perp_gate_sweep": perp_gate_sweep,
    }
    if job == "run_module":
        code = run_module.remote(module, args.split() if args else [])
    elif job in jobs:
        code = jobs[job].remote()
    else:
        raise SystemExit(f"unknown job {job!r}; choose {sorted(jobs) + ['run_module']}")
    print(f"[modal] job={job} exit={code}")
    if code:
        raise SystemExit(code)
