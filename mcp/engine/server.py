"""cosmu-engine MCP: thin CLI shell-outs to the Cosmu Gate + data pipeline.

Tools shell out to `modal run` / `pnpm` — they do NOT reimplement Gate logic.
The deterministic Gate stays entirely in apps/engine/cosmu/research/gate.py.

Auth: loads creds from .env.local at repo root (process env wins in prod).
Write/money-adjacent: NONE of these tools arm live orders. They drive research
and ingest only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env.local", override=False)
load_dotenv(".env.local", override=False)

# In-process engine read path: import the real Store + read-only handlers (no subprocess, no SQL strings).
# These power the read tools below; the propose-only Gate evaluation calls the deterministic gate directly.
sys.path.insert(0, str(_ROOT / "apps" / "engine"))  # the cosmu.* engine package
sys.path.insert(0, str(Path(__file__).resolve().parent))  # this dir → `import handlers` works run-as-script

from mcp.server.fastmcp import FastMCP  # noqa: E402 — after the sys.path setup above (script-launch import)

import handlers  # noqa: E402 — sibling module; the directory above is on sys.path

mcp = FastMCP(
    "cosmu-engine",
    instructions=(
        "Drive the Cosmu research pipeline by talking. "
        "run_gate / run_ingest / run_job shell out to Modal (cloud compute). "
        "list_verdicts / list_strategies / trial_count read the DB locally. "
        "No live orders are ever placed by any tool in this server."
    ),
)

# Available Modal jobs (mirrors apps/engine/remote/app.py).
GATE_JOBS = ("gate_sweep", "ingest", "forward_mark", "cost_refresh", "perp_gate_sweep")


def _sh(cmd: list[str], *, timeout: int = 3600, env_extra: dict | None = None) -> dict[str, Any]:
    """Run a subprocess from the repo root, capture output, return structured result."""
    env = {**os.environ, **(env_extra or {})}
    env.setdefault("APP_ENV", "dev")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-8000:] if result.stdout else "",
            "stderr": result.stderr[-4000:] if result.stderr else "",
            "ok": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Timed out after {timeout}s", "ok": False}
    except FileNotFoundError as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e), "ok": False}


def _py(snippet: str) -> Any:
    """Run a Python one-liner against the engine package (reads DB, never writes)."""
    result = _sh(
        [sys.executable, "-c", snippet],
        env_extra={"PYTHONPATH": str(_ROOT / "apps" / "engine")},
        timeout=30,
    )
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or result["stdout"])
    return result["stdout"].strip()


def _store():  # noqa: ANN202 - returns a cosmu Store bound to the live DB
    """The engine's own Store, built from settings (process env wins). Read-only callers below only ever issue
    SELECTs through it; the propose-only Gate evaluation runs against a throwaway temp store so a query can
    never touch the live trial ledger."""
    from cosmu.config.settings import get_settings
    from cosmu.knowledge.store import Store

    return Store(get_settings())


# ---------------------------------------------------------------------------
# Gate + pipeline jobs (shell out to Modal)
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Run a Modal compute job against the live Cosmu DB. "
        f"job must be one of: {', '.join(GATE_JOBS)}. "
        "gate_sweep = full autonomous cycle (ingest→author→ML screen→gate→fund SIM). "
        "ingest = one free-data ingest + cross-asset gate pass. "
        "forward_mark = re-mark held SIM positions. "
        "cost_refresh = fetch vendor spend + check budgets. "
        "perp_gate_sweep = funding-dispersion cost-scenario grid. "
        "Returns exit_code, stdout, stderr. Requires Modal to be configured."
    ),
    annotations={"readOnlyHint": False, "idempotentHint": False},
)
def run_gate(job: str = "gate_sweep") -> dict[str, Any]:
    if job not in GATE_JOBS:
        raise ValueError(f"Unknown job {job!r}. Choose from: {GATE_JOBS}")
    return _sh(["modal", "run", "apps/engine/remote/app.py", "--job", job], timeout=3600)


@mcp.tool(
    description=(
        "Convenience alias: run the ingest job on Modal "
        "(mirrors `pnpm modal:ingest`). "
        "Fetches free alt-data + bars and passes the cross-asset gate."
    ),
    annotations={"readOnlyHint": False, "idempotentHint": True},
)
def run_ingest() -> dict[str, Any]:
    return run_gate("ingest")


@mcp.tool(
    description=(
        "Run any engine Python module via Modal's run_module escape hatch. "
        "module: e.g. 'cosmu.research.loop'. args: optional list of CLI args. "
        "Use this for modules not covered by the named jobs."
    ),
    annotations={"readOnlyHint": False},
)
def run_module(module: str, args: list[str] | None = None) -> dict[str, Any]:
    cmd = ["modal", "run", "apps/engine/remote/app.py", "--job", "run_module",
           "--module", module]
    if args:
        cmd += ["--args", " ".join(args)]
    return _sh(cmd, timeout=3600)


@mcp.tool(
    description="List the available Modal job names for run_gate.",
    annotations={"readOnlyHint": True},
)
def list_gate_jobs() -> list[str]:
    return list(GATE_JOBS)


# ---------------------------------------------------------------------------
# DB read tools (local python, no Modal needed)
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Return the N most recent Gate verdicts from the local DB. "
        "Each verdict has: ts, decision (PASS/STOP), data_source, payload."
    ),
    annotations={"readOnlyHint": True},
)
def list_verdicts(limit: int = 10) -> list[dict[str, Any]]:
    snippet = (
        "import json, os; "
        "from cosmu.config.settings import get_settings; "
        "from cosmu.knowledge.store import Store; "
        "from sqlalchemy import text; "
        "s = Store(get_settings()); "
        "rows = s.engine.connect().execute("
        "  text('SELECT ts,decision,data_source,payload FROM gate_verdicts ORDER BY ts DESC LIMIT :n'),"
        f"  dict(n={min(limit, 100)})"
        ").fetchall(); "
        "print(json.dumps([{'ts':r[0],'decision':r[1],'data_source':r[2],'payload':json.loads(r[3])} for r in rows]))"
    )
    raw = _py(snippet)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [{"raw": raw}]


@mcp.tool(
    description=(
        "Return the N most recent strategies with their latest version status. "
        "status filter: 'funded' | 'killed' | 'active' | None (all)."
    ),
    annotations={"readOnlyHint": True},
)
def list_strategies(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    where = f"AND sv.status='{status}' " if status else ""
    snippet = (
        "import json; "
        "from cosmu.config.settings import get_settings; "
        "from cosmu.knowledge.store import Store; "
        "from sqlalchemy import text; "
        "s = Store(get_settings()); "
        "sql = text("
        "  'SELECT s.id, s.name, s.thesis, sv.status, sv.created_at, sv.killed_at "
        "   FROM strategies s "
        "   JOIN strategy_versions sv ON sv.strategy_id=s.id "
        "   WHERE sv.id=(SELECT id FROM strategy_versions WHERE strategy_id=s.id ORDER BY created_at DESC LIMIT 1) "
        f"  {where}"
        "   ORDER BY sv.created_at DESC LIMIT :n'"
        "); "
        f"rows = s.engine.connect().execute(sql, dict(n={min(limit, 200)})).fetchall(); "
        "print(json.dumps([{'id':r[0],'name':r[1],'thesis':r[2],'status':r[3],'created_at':r[4],'killed_at':r[5]} for r in rows]))"
    )
    raw = _py(snippet)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [{"raw": raw}]


@mcp.tool(
    description="Return total trial count and last-trial timestamp (deflated Sharpe ledger).",
    annotations={"readOnlyHint": True},
)
def trial_count() -> dict[str, Any]:
    snippet = (
        "import json; "
        "from cosmu.config.settings import get_settings; "
        "from cosmu.knowledge.store import Store; "
        "from sqlalchemy import text; "
        "s = Store(get_settings()); "
        "row = s.engine.connect().execute("
        "  text('SELECT COUNT(*), MAX(ts) FROM trials')"
        ").fetchone(); "
        "print(json.dumps({'total_trials': row[0], 'last_ts': row[1]}))"
    )
    raw = _py(snippet)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


# ---------------------------------------------------------------------------
# In-process READ-ONLY tools (mcp/engine/handlers.py). No subprocess, no SQL
# string-building, no money path. Each reuses an engine function and only ever
# issues SELECTs (or, for the Gate, EMITS a propose-only verdict). NONE of these
# arm an order, fund a track, toggle live, or loosen the Gate.
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "READ-ONLY. The N most recent strategies, each with its latest version's status. "
        "status filter: 'funded' | 'killed' | 'active' | None (all). Reads only — never authors or funds."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def strategies(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return handlers.list_strategies(_store(), status=status, limit=limit)


@mcp.tool(
    description=(
        "READ-ONLY. The N most recently-updated forward-test tracks (one standalone track per funded survivor; "
        "there is no pooled wallet). Returns marked equity/return_pct. Reads only — never marks or moves money."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def tracks(limit: int = 20) -> list[dict[str, Any]]:
    return handlers.list_tracks(_store(), limit=limit)


@mcp.tool(
    description=(
        "READ-ONLY. The N most recent Gate verdicts (PASS/STOP) from the verdict ledger, newest first. "
        "Each has ts, decision, data_source, payload. A pure SELECT over gate_verdicts."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def gate_verdicts(limit: int = 10) -> list[dict[str, Any]]:
    return handlers.read_gate_verdicts(_store(), limit=limit)


@mcp.tool(
    description=(
        "READ-ONLY. The gate-ranked strategy leaderboard (highest deflated Sharpe first), joined to each "
        "version's backtest. A pure read-out — no running web server needed, no money path."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def leaderboard(limit: int = 20) -> list[dict[str, Any]]:
    return handlers.read_leaderboard(_store(), limit=limit)


@mcp.tool(
    description=(
        "READ-ONLY. The aggregate forward-test overview: Σ-equity curve across all standalone tracks, net PnL, "
        "spend-by-category, and whether live is enabled. A pure read-out (no pooled wallet)."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def overview() -> dict[str, Any]:
    return handlers.read_overview(_store())


@mcp.tool(
    description=(
        "READ-ONLY / PROPOSE-ONLY. Run the deterministic single-signal edge Gate on synthetic point-in-time "
        "fixtures and return its PASS/STOP verdict. Calls the real cosmu.research.gate.evaluate_gate (never a "
        "reimplementation, never a relaxed bar). edge=True = edge-bearing fixtures; edge=False = the honest null "
        "where the Gate MUST STOP. Runs against a throwaway temp store, so it cannot touch the live trial "
        "ledger and CANNOT fund a track, arm an order, or move any money."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
def evaluate_signal_gate(edge: bool = True, seed: int = 7) -> dict[str, Any]:
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    tmp = tempfile.mkdtemp(prefix="cosmu-mcp-gate-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/gate.sqlite3", openrouter_api_key=None))
    return handlers.evaluate_signal_gate(store, edge=edge, seed=seed)


if __name__ == "__main__":
    mcp.run()
