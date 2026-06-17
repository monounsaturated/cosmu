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
    .apt_install("curl", "ca-certificates")
    # pg_dump 17 for the daily_backup job. Supabase runs Postgres 17.x and pg_dump REFUSES to dump a server newer
    # than itself; Debian's default postgresql-client is v15 (→ "server version mismatch"). Pull the official PGDG
    # apt repo and install the v17 client (codename auto-detected so it survives a base-image bump).
    .run_commands(
        "install -d /usr/share/postgresql-common/pgdg",
        "curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc",
        'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" > /etc/apt/sources.list.d/pgdg.list',
        "apt-get update",
        "apt-get install -y --no-install-recommends postgresql-client-17",
    )
    .add_local_dir(
        str(ENGINE_DIR),
        remote_path="/root/engine",
        copy=True,  # materialize into the layer so the next run_commands can see it
        ignore=["**/__pycache__", "**/*.pyc", "tests/**", "remote/**"],
    )
    .run_commands("pip install '/root/engine[lake,ops]'")  # [lake]=duckdb (DuckLake + R2 Parquet lake_* jobs), [ops]=boto3 (R2 backup upload)
)

# Crypto bar cache for the gate sweep. Binance's REST API geo-blocks cloud IPs (Modal is US) → a live fetch
# returns nothing, so the gate sees "no-data" and refuses every spec. We bundle the LOCAL daily bar cache into
# the image (deterministic, point-in-time, ~a few MB for 1d) and point COSMU_BINANCE_CACHE at it. Opt-in via
# COSMU_BARS_SRC (set on the operator Mac, e.g. /Users/.../.cosmu/market_data) so the committed image stays
# Mac-path-free; only the daily files ship (1h/4h ignored to keep the layer lean). The bars never leave the
# image; all WRITES still go to the same Supabase.
_BARS_SRC = os.environ.get("COSMU_BARS_SRC")
_BARS_REMOTE = "/root/market_data"
if _BARS_SRC and Path(_BARS_SRC).exists():
    # Bake COSMU_BINANCE_CACHE into the image env so the CONTAINER (where COSMU_BARS_SRC is unset) points the
    # bar loader at the bundled daily cache — without this the runtime never knows the bars were shipped.
    image = image.add_local_dir(
        _BARS_SRC, remote_path=_BARS_REMOTE, copy=True, ignore=["**/*_1h.json", "**/*_4h.json"]
    ).env({"COSMU_BINANCE_CACHE": _BARS_REMOTE})

# A SEPARATE image for the TEST SUITE: runs the full engine suite hermetically off the M2 (the heavy-compute
# lane; the M2 OOM'd running it serially). It copies the WHOLE repo (not just apps/engine) — a few cross-cutting
# tests scan repo-root context (.claude/skills, apps/web routes), so an engine-only image false-fails them — and
# installs the dev+live+lake extras (pytest/xdist, py-clob-client, duckdb) so every test is collectable. Heavy
# dirs (node_modules/.git/.venv/.next/.cosmu) are excluded. Tests build temp sqlite + offline fixtures → no
# secret/DB needed.
REPO_ROOT = ENGINE_DIR.parent.parent  # apps/engine -> apps -> repo root
test_image = (
    modal.Image.debian_slim(python_version="3.12")
    .add_local_dir(
        str(REPO_ROOT),
        remote_path="/root/repo",
        copy=True,
        ignore=[
            "**/node_modules", "**/.git", "**/.venv", "**/.next", "**/.cosmu", "**/.turbo",
            "**/dist", "**/.pytest_cache", "**/__pycache__", "**/*.pyc", "**/*.sqlite3", ".claude/worktrees",
            # NEVER bundle local dotenv secrets into the test image. The `tests` job runs with APP_ENV=test,
            # which now maps to .env.local (config/settings.py) — so a bundled .env.local would make the Modal
            # suite read the PROD DATABASE_URL + real keys. The job has NO Modal secret attached, so excluding
            # these files is what keeps it hermetic (temp sqlite + offline fixtures, as the header promises).
            "**/.env.local", "**/.env*.local",
        ],
    )
    .run_commands("pip install '/root/repo/apps/engine[dev,live,lake]'")
)

# Runtime env: the SAME values the Railway backend reads. APP_ENV=production makes Settings read process env
# only (no committed file). Sync it from .env.local with:  python3 scripts/sync_modal_secret.py
engine_secret = modal.Secret.from_name("cosmu-engine")

# Beefy defaults for a sweep; tune per job. Bursty → scale-to-zero between runs (~$0 idle).
_HEAVY = dict(image=image, secrets=[engine_secret], timeout=60 * 60, cpu=4.0, memory=8192)
# Lake jobs scan/write the 13.5M-row Parquet hoard (LunarCrush ~99%) — 32GB so a partitioned COPY or a deep
# DuckDB scan never spills to swap. Same image/secret; the R2_* creds in the secret make the lake reachable.
_LAKE = dict(image=image, secrets=[engine_secret], timeout=60 * 60, cpu=4.0, memory=32768)
# Light profile for the I/O-bound / cheap-probe schedules (ingest, mark, cost, heartbeat) — keeps the fleet's
# Modal spend small (these aren't compute, they're network + a few queries). gate_sweep stays _HEAVY.
_LIGHT = dict(image=image, secrets=[engine_secret], timeout=20 * 60, cpu=1.0, memory=2048)


def _run(module_args: list[str], *, extra_env: dict[str, str] | None = None) -> int:
    """Run `python -m <module> [args…]` against the installed engine, streaming output back to the caller.
    `extra_env` overrides process env for THIS run only (e.g. ALT_DATA_BACKEND=parquet for a lake read) —
    never the shared secret, so the ingest/gate crons keep their default (Postgres) backend."""
    env = {**os.environ}
    env.setdefault("APP_ENV", "production")  # process-env secrets only, like the deployed engine
    # COSMU_BINANCE_CACHE is baked into the image env when bars are bundled (see above) → inherited here.
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


@app.function(schedule=modal.Cron("0 * * * *"), **_LIGHT)
def ingest() -> int:
    """Free-data INGEST ONLY (hourly — replaces the dead Railway */15 cron; the canary the heartbeat watches).
    The leaky cross-asset gate is DEFAULT OFF;
    pass --cross-asset-gate to opt in. Honest BH-FDR gate path (promote_cohort) runs via gate_sweep."""
    return _run(["cosmu.research.loop", "--ingest"])


@app.function(**_LIGHT)
def paper_mark() -> int:
    """Re-mark held SIM positions against the latest real close (paper clock, paper-only, no orders).
    Scheduled via the combined `tick` (Modal Free = 5 schedules max); also runnable on-demand."""
    return _run(["cosmu.orchestrator.loop"])


@app.function(**_HEAVY)
def arm_fleet() -> int:
    """Re-arm + advance the documented equity cohort (Faber/ADM/VAA/PAA/DAA/…) so the forward paper clock
    ticks for the arm-based tracks too (paper_mark only re-marks position-backed tracks). Scheduled via the
    combined `tick`. SIM only — never an order."""
    return _run(["cosmu.research.arm_fleet"])


@app.function(**_LIGHT)
def cost_refresh() -> int:
    """Fetch live vendor spend (OpenRouter, Railway, Modal, xAI ledger), check budget thresholds,
    emit Slack alerts + recommendation rows. Mirrors the 6h Railway cron."""
    return _run(["cosmu.costs.refresh"])


@app.function(schedule=modal.Cron("30 * * * *"), **_LIGHT)
def heartbeat() -> int:
    """HOURLY dead-man's-switch (:30, after the :00 ingest): Slack-alert if the fleet's ingest/tick/mark signals
    go stale — the alarm that was MISSING when the Railway crons died silently for ~10 days. Read-only; exits
    non-zero on a stale fleet so the Modal run also flags red. Logic in cosmu/ops/heartbeat.py."""
    return _run(["cosmu.ops.heartbeat"])


@app.function(schedule=modal.Cron("0 */4 * * *"), **_HEAVY)
def tick() -> int:
    """EVERY 4h — the full forward cycle in ONE scheduled slot (Modal Free caps schedules at 5, so discovery +
    paper clock + cohort re-arm share this slot). Discovery (author → deterministic gate/FDR → fund SIM
    survivors) + advance the paper clock (mark held positions + re-arm the documented equity cohort), and refresh
    vendor-cost budgets once/day. SIM only by invariant — NEVER an order. The standalone gate_sweep / paper_mark /
    arm_fleet / cost_refresh functions stay for on-demand `modal run`."""
    from datetime import UTC, datetime

    rc = _run(["cosmu.master.scheduler"])   # discovery: author → gate/FDR → fund SIM survivors
    _run(["cosmu.orchestrator.loop"])        # paper clock: mark held positions to the latest real close
    _run(["cosmu.research.arm_fleet"])       # advance the documented equity cohort's forward clock
    _run(["cosmu.strategy.agent_run"])       # observe-only LLM strategies: reason (Mind panel) + record traces ($0)
    if datetime.now(UTC).hour < 4:           # ~once/day (the 00:00 UTC tick): vendor-cost budget alerts
        _run(["cosmu.costs.refresh"])
    return rc


@app.function(**_HEAVY)
def perp_gate_sweep() -> int:
    """Run the funding-dispersion strategy through the cost-scenario grid (OKX/Kraken Futures fees ×
    funding regimes). Reports skew/tail/cost_ratio per scenario — the Phase 0 P0.6 perp cost surface.
    Needs the offline funding cache; run `ingest` first to populate it (or funding will be empty)."""
    return _run(["cosmu.research.perp_gate_sweep"])


# ---------------------------------------------------------------------------
# Matrix sweep — parallel fan-out of the strategy × asset × timeframe hunt.
# CAVEAT: only daily (1d) bars are baked into the Modal image (COSMU_BARS_SRC bundles the bar
# cache; intraday frames are excluded from the image to keep the layer small). A pure 1d sweep
# works out-of-the-box. For intraday frames (4h, 1h) the bars must be available via the R2 cold
# store (COSMU_BARS_SRC pointing to an R2 path) — set COSMU_BARS_SRC to an r2:// prefix and the
# loader will pull from R2. Until then, intraday cells honestly return no-data rather than crashing.
# ---------------------------------------------------------------------------

@app.function(**_HEAVY)
def matrix_cell(asset: str, timeframe: str) -> dict:
    """Single (asset, timeframe) cell of the strategy × universe sweep — the self-contained unit
    Modal.map fans out in parallel. Runs every inbox StrategySpec through the full honest Gate
    (deflated Sharpe + CSCV-PBO + holdout + BH-FDR, net of real fees) on the given slice and
    returns the MatrixResult as a plain dict (dataclasses.asdict) so the caller can aggregate.
    Each cell writes its gate_verdicts row when persist=True (the default in run_matrix_cell).
    NEVER fires a live order — deterministic research only."""
    import dataclasses

    from cosmu.research.matrix_search import run_matrix_cell
    return dataclasses.asdict(run_matrix_cell(asset, timeframe))


@app.local_entrypoint()
def sweep(assets: str = "", timeframes: str = "1d") -> None:
    """Fan out the matrix sweep across (asset × timeframe) cells in parallel using Modal.starmap.
    Default asset universe: the full 30-asset PERP_UNIVERSE (the unsearched broad set) + equity
    ETFs (SPY, QQQ, IWM, GLD, TLT) which carry the alt-joined feature space (~75 features not yet
    exhausted by the prior bar-TA grid). Override via --assets BTC,ETH,SOL --timeframes 1d,4h.
    Example: modal run apps/engine/remote/app.py::sweep --assets BTCUSDT,ETHUSDT --timeframes 1d
    Note: the pnpm modal:sweep shortcut runs the full broad universe with 1d bars."""
    # Broad default: full perp universe + equity ETFs (the unsearched territory).
    # These are NOT the exhausted bar-TA grid (BTC/ETH/SOL/BNB/XRP/ADA/AVAX/LINK + SPY/QQQ).
    _BROAD_ASSETS = [
        # --- crypto perps (30 assets — volume-ordered; bar cache bundled for 1d via COSMU_BARS_SRC) ---
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
        "TRXUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "UNIUSDT",
        "ATOMUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT",
        "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "AAVEUSDT",
        "ETCUSDT", "XLMUSDT", "ICPUSDT", "RUNEUSDT", "GALAUSDT",
        # --- equity ETFs (alt-joined: macro + sector features; bar cache via load_tr_bars) ---
        "SPY", "QQQ", "IWM", "GLD", "TLT", "EEM", "XLF", "XLK",
    ]
    asset_list = [a.strip() for a in assets.split(",") if a.strip()] if assets else _BROAD_ASSETS
    tf_list = [t.strip() for t in timeframes.split(",") if t.strip()]
    cells = [(a, tf) for a in asset_list for tf in tf_list]
    print(f"[sweep] fanning out {len(cells)} cells ({len(asset_list)} assets × {len(tf_list)} timeframes) via Modal.starmap")
    for r in matrix_cell.starmap(cells):
        survivors = r.get("survivors") or []
        verdict = "SURVIVOR" if survivors else ("no-survivor" if r.get("n_traded") else "no-data")
        print(f"  {r.get('asset', '?')}@{r.get('timeframe', '?'):4s}  {verdict:12s}  "
              f"traded={r.get('n_traded', 0):3d}  promoted={r.get('n_promoted', 0):2d}  "
              f"best_dsr={r.get('best_dsr', 0.0):.4f}  survivors={survivors}")


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
def sync_lake() -> int:
    """Mirror alt_data → the DuckLake cold lake on R2, incrementally (backfill on first run, then aged-out
    deltas). READ-ONLY on alt_data. Needs the R2 keys in the cosmu-engine secret + duckdb in the image."""
    return _run(["cosmu.data.age_out"])


@app.function(**_HEAVY)
def prune_alt_data(apply: bool = False, hot_window_days: int = 90) -> int:
    """GATED Postgres retention: DELETE alt_data older than hot_window_days (funding_rate exempt) ONLY after the
    DuckLake lake is confirmed to hold the delete window, then VACUUM. DRY-RUN unless apply=True. Run sync_lake
    first so the lake is current. This is the step that shrinks the hot DB."""
    args = ["--hot-window-days", str(hot_window_days)]
    if apply:
        args.append("--apply")
    return _run(["cosmu.data.retention", *args])


@app.function(schedule=modal.Cron("0 6 * * 1"), **_HEAVY)
def cold_tier_maintenance() -> int:
    """WEEKLY (Mon 06:00 UTC), off the Railway box / M2: mirror new alt_data → the DuckLake lake, THEN gated-prune
    the aged-out (>90d) Postgres rows + VACUUM. The prune deletes ONLY rows the lake is confirmed to hold
    (funding_rate exempt), so no row is ever lost; if the mirror fails, the prune is skipped. Keeps Postgres at
    the ~90d hot window and the lake complete. Disable with `modal app stop cosmu-engine` or by removing this
    schedule + redeploying."""
    rc = _run(["cosmu.data.age_out"])  # mirror first
    if rc != 0:
        return rc  # never prune if the mirror failed — the prune's gate would refuse anyway, but bail early
    return _run(["cosmu.data.retention", "--apply"])  # gated: lake-completeness checked inside before any DELETE


@app.function(schedule=modal.Cron("0 5 * * *"), **_HEAVY)
def daily_backup() -> int:
    """DAILY (05:00 UTC) self-managed money-truth backup — replaces Supabase's managed daily backups, which are
    GONE on the Free plan. `pg_dump -Fc` of the control plane + DuckLake catalog (EXCLUDES the alt_data rows —
    they live in the R2 lake, parity-proven), uploaded to r2://<bucket>/backups/pg/ + last-14 retention. Needs
    postgresql-client (in the image), DATABASE_URL + R2 keys (in the cosmu-engine secret). Restore:
    pg_restore --no-owner --clean --if-exists -d '<session DSN :5432>' <file>."""
    return _run(["cosmu.data.pg_backup"])


@app.function(**_HEAVY)
def run_module(module: str, args: list[str] | None = None) -> int:
    """Escape hatch: run any engine module as `python -m <module> [args…]` on Modal compute.
    e.g. modal run apps/engine/remote/app.py --job run_module --module cosmu.research.gate"""
    return _run([module, *(args or [])])


@app.function(image=test_image, timeout=60 * 30, cpu=8.0, memory=16384)
def tests(paths: str = "tests", expr: str = "") -> int:
    """Run the engine pytest suite on Modal compute (off the M2) — parallel (-n auto, loadfile distribution,
    xdist-safe). Hermetic: temp sqlite + offline fixtures, no secret/DB needed. `paths` scopes files (space-
    split), `expr` is a -k filter. e.g. modal run apps/engine/remote/app.py --job tests"""
    env = {**os.environ, "APP_ENV": "test"}
    cmd = [sys.executable, "-m", "pytest", *paths.split(), "-n", "auto", "--dist=loadfile", "-q",
           "-p", "no:cacheprovider", "-rfE", "--tb=line"]  # -rfE: name every failed/errored test in the summary
    if expr:
        cmd += ["-k", expr]
    return subprocess.run(cmd, cwd="/root/repo/apps/engine", env=env).returncode


@app.local_entrypoint()
def main(job: str = "gate_sweep", module: str = "", args: str = "", apply: bool = False, hot_window_days: int = 90) -> None:
    """`modal run apps/engine/remote/app.py [--job gate_sweep|ingest|perp_gate_sweep|paper_mark|cost_refresh|
    sync_lake|daily_backup|prune|export_lake|lake_smoke|lake_run|tests|run_module]`.
    For run_module/lake_run pass --module cosmu.x.y and optional --args "--flag value" (space-split).
    For prune pass --apply to actually delete (default dry-run) and optional --hot-window-days N.
    export_lake refreshes the R2 Parquet lake; lake_smoke verifies R2 read access."""
    jobs = {
        "tick": tick,
        "gate_sweep": gate_sweep,
        "ingest": ingest,
        "paper_mark": paper_mark,
        "forward_mark": paper_mark,  # legacy alias (pre-2026-06-11 vocabulary) — same job
        "arm_fleet": arm_fleet,
        "cost_refresh": cost_refresh,
        "heartbeat": heartbeat,
        "perp_gate_sweep": perp_gate_sweep,
        "sync_lake": sync_lake,
        "daily_backup": daily_backup,
        "export_lake": export_lake,
        "lake_smoke": lake_smoke,
        "tests": tests,
    }
    if job in ("run_module", "lake_run"):
        fn = run_module if job == "run_module" else lake_run
        code = fn.remote(module, args.split() if args else [])
    elif job == "prune":
        code = prune_alt_data.remote(apply=apply, hot_window_days=hot_window_days)
    elif job in jobs:
        code = jobs[job].remote()
    else:
        raise SystemExit(f"unknown job {job!r}; choose {sorted(jobs) + ['prune', 'run_module', 'lake_run']}")
    print(f"[modal] job={job} exit={code}")
    if code:
        raise SystemExit(code)
