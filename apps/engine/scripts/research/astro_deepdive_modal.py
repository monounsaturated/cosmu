#!/usr/bin/env python3
# intent: the APPROVED astro FULL deep-dive HARNESS — the single most exhaustive, definitive astro pass
# (full Binance-pair universe × full daily astro parameter space), built to make the (near-certain null)
# conclusion unimpeachable while standing up the minute-bar + full-universe + R2 data infra the real
# strategies want. Pre-registered design lives in docs/research/astro_final_deepdive_PLAN.md.
#
# FIVE PHASES (PHASE0 runs locally; PHASE1–4 fan out on Modal, scale-to-zero):
#   PHASE0  local: validate inputs, ANNOUNCE scope + cost estimate + R2 layout. `--mode prepare` STOPS here ($0).
#   PHASE1  Modal fan-out: download_binance_vision_slab(pair, timeframe, market, start, end) → Parquet on R2
#           under the 'astro_deepdive' prefix (checksummed bulk ZIPs from data.binance.vision, free, no rate
#           limit). One container per (pair × timeframe) SLAB with retries + resume-from-R2 so a lost gRPC stream
#           is re-run on a fresh container and an already-written slab is skipped — not the whole map killed.
#   PHASE2  Modal: compute the DAILY astro feature tensor ONCE (reuse AF.deep_astro_features) → R2 (astro barely
#           moves intraday — daily is correct and ~25 MB).
#   PHASE3  Modal fan-out: the backtest + permutation-null sweep — REUSE run_lab.enumerate_configs /
#           backtest_config / position_series for the vectorized signals, and modal_sweep._perm_cv_core /
#           run_sweep_modal for the B=n_perm phase-/label-permutation null. Results → R2.
#   PHASE4  aggregate every (config × asset × encoding) trial + Deflated-Sharpe at the TRUE trial count → R2.
#
# A CostTracker watches accumulated container-hours and STOPS the remaining phases the moment estimated spend
# crosses 0.8×budget (Slack alert when SLACK_WEBHOOK_URL is set, else print).
#
# RESEARCH-ONLY + ISOLATED: every write lands under the R2 'astro_deepdive' prefix via LabStore. This harness
# NEVER imports or touches gate.py / the scheduler / the trial-ledger / the money path. `--mode prepare` spends
# $0 (no Modal call); `--mode run` is the operator-controlled $35–110 spend.
#
# NO FABRICATION: real prices (data.binance.vision), deterministic astro geometry, PIT throughout. The expected
# outcome — pre-registered — is a documented NULL (0 survive deflation), which closes astro permanently.

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# apps/engine — so `cosmu.*` and the reused research helpers import the same way run_lab does.
ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(ENGINE_ROOT / "scripts/research/astro_deep"))
sys.path.insert(0, str(ENGINE_ROOT / "scripts/research/astro_strategy_lab"))

# The R2 prefix that ISOLATES this entire run from prod alt_data + the Gate ledger + the astro_lab namespace.
R2_PREFIX = "astro_deepdive"

# data.binance.vision bulk-download layout (free, checksummed, no rate limit). The PLAN's data source.
BINANCE_VISION_BASE = "https://data.binance.vision/data"


# ── config ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class DownloadSpec:
    """What price data to pull from data.binance.vision (PHASE1). Pairs default to a representative slice;
    the PLAN targets ~400 USDT pairs — pass the full list to widen. `timeframes`: '1m' is the headline new
    data; '1h'/'1d' are cheap derivations the harness can also fetch directly."""

    pairs: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"])
    market: str = "spot"  # data.binance.vision market segment: spot | um (USD-M futures) | cm (COIN-M)
    timeframes: list[str] = field(default_factory=lambda: ["1d", "1h", "1m"])
    start: str = "2017-08-01"  # Binance spot inception-ish; per-pair availability clips this
    end: str = "2026-06-01"

    def r2_glob(self) -> str:
        return f"{R2_PREFIX}/bars/<pair>/<timeframe>/*.parquet"


@dataclass
class DeepDiveConfig:
    """The deep-dive run knobs. Defaults match the PLAN's pre-registered envelope."""

    download_spec: DownloadSpec = field(default_factory=DownloadSpec)
    n_configs: int = 4000      # distinct labeled astro strategy configs (cap fed to run_lab.enumerate_configs)
    n_perm: int = 1000         # permutation-null draws per candidate (the B in the PLAN; the swing cost)
    fee_bps: float = 10.0      # per position-change fee, matched to run_lab.backtest_config
    modal_budget_usd: float = 110.0  # hard ceiling; CostTracker STOPS at 0.8× this
    seed: int = 7

    # Modal resourcing assumptions used ONLY for the prepare-time cost estimate (no spend).
    container_hr_usd: float = 0.40
    download_wall_hours: float = 0.10   # ~6 min per download container (bulk ZIP fetch + parquet write)
    sweep_wall_hours: float = 0.05      # ~3 min per perm-null container (vectorized + B perms)

    def n_download_containers(self) -> int:
        """One container per (pair × timeframe) — embarrassingly parallel by the PLAN."""
        return len(self.download_spec.pairs) * len(self.download_spec.timeframes)

    def n_sweep_containers(self) -> int:
        """The candidate perm-null fan-out. The full config sweep is vectorized + cheap and runs in a single
        feature pass; the EXPENSIVE part is the B=n_perm null on the surviving candidates, so we size the
        fan-out to the candidate set (≈1 container per ~50 configs that clear the raw pre-screen)."""
        return max(1, self.n_configs // 50)

    def estimated_modal_usd(self) -> float:
        dl = self.n_download_containers() * self.download_wall_hours
        # PHASE2 feature tensor: one short container. PHASE3 sweep: candidate fan-out × B-scaled wall.
        tensor = 1 * 0.25
        sweep = self.n_sweep_containers() * self.sweep_wall_hours * max(1.0, self.n_perm / 1000.0)
        return (dl + tensor + sweep) * self.container_hr_usd

    def scope_summary(self) -> dict:
        ds = self.download_spec
        return dict(
            r2_prefix=R2_PREFIX,
            pairs=len(ds.pairs),
            market=ds.market,
            timeframes=ds.timeframes,
            date_range=f"{ds.start}..{ds.end}",
            n_configs=self.n_configs,
            n_perm=self.n_perm,
            fee_bps=self.fee_bps,
            n_download_containers=self.n_download_containers(),
            n_sweep_containers=self.n_sweep_containers(),
            est_modal_usd=round(self.estimated_modal_usd(), 2),
            budget_usd=self.modal_budget_usd,
            stop_at_usd=round(0.8 * self.modal_budget_usd, 2),
        )


# ── Modal app + images (defined at import so `modal run` discovers them; importing modal is cheap) ───
# Reuse remote/app.py's _HEAVY engine image for the phases that need the full `cosmu`/ephem stack
# (download + feature tensor); reuse modal_sweep.py's LIGHT numpy/scipy/sklearn image for the perm-null
# kernel. Both are ephemeral + scale-to-zero — nothing is left running, ~$0 idle.

try:  # importing modal must not break `--mode prepare` on a box without modal installed
    import modal

    _MODAL_OK = True
except Exception:  # noqa: BLE001
    modal = None  # type: ignore
    _MODAL_OK = False


def _ensure_research_path() -> None:
    """Put the research helper dirs on sys.path INSIDE the Modal container. `cosmu` is pip-installed, but the
    reused research modules (lab_store / astro_deep_study / astro_features_deep / run_lab / modal_sweep) live in
    the copied tree, NOT in site-packages — without this the in-container workers raise ModuleNotFoundError. The
    image copies the tree to /root/engine (remote/app.py's layout); the local driver resolves ENGINE_ROOT to the
    real apps/engine. Try both roots so the SAME core functions import identically on the M2 and on Modal."""
    roots = [Path("/root/engine"), ENGINE_ROOT]
    subdirs = ("", "scripts/research", "scripts/research/astro_deep", "scripts/research/astro_strategy_lab")
    for root in roots:
        if not root.exists():
            continue
        for sub in subdirs:
            p = str(root / sub) if sub else str(root)
            if p not in sys.path:
                sys.path.insert(0, p)


def _engine_image():
    """The same engine image remote/app.py builds (copy the tree, `pip install .[lake]`), so `cosmu`, the
    ephemeris stack, the research helpers, AND duckdb (the LabStore R2 writer) are all importable inside the
    container — no PYTHONPATH drift and no missing-duckdb surprise when a worker writes Parquet to R2."""
    return (
        modal.Image.debian_slim(python_version="3.12")
        .add_local_dir(
            str(ENGINE_ROOT),
            remote_path="/root/engine",
            copy=True,
            ignore=["**/__pycache__", "**/*.pyc", "tests/**", "remote/**"],
        )
        .run_commands("pip install '/root/engine[lake]'")  # [lake]=duckdb → LabStore R2 COPY works in-container
    )


if _MODAL_OK:
    app = modal.App("cosmu-astro-deepdive")
    _engine_secret = modal.Secret.from_name("cosmu-engine")  # DATABASE_URL, R2_*, SLACK_WEBHOOK_URL, …
    # PHASE1/2 need the full engine + ephemeris + R2 creds; PHASE3 perm-null is light numpy/sklearn.
    # retries=2 + max_containers cap make the bulk-download fan-out resilient to the grpclib StreamTerminated /
    # Deadline-exceeded the first smoke hit: a slab that loses its stream is RE-RUN on a fresh container instead
    # of killing the map, and the container count is bounded so we never melt the gRPC control plane.
    _ENGINE = dict(
        image=_engine_image(), secrets=[_engine_secret],
        timeout=60 * 30, cpu=4.0, memory=8192, retries=2, max_containers=24,
    )

    @app.function(**_ENGINE)
    def download_binance_vision_slab(pair: str, timeframe: str, market: str, start: str, end: str) -> dict:
        """PHASE1 worker (SLAB granularity): pull REAL OHLCV for ONE (pair × timeframe) and write Parquet to R2
        under the 'astro_deepdive' prefix. The fan-out is over the (pair × timeframe) cartesian product so each
        container does a SMALL, bounded download (a single timeframe's monthly ZIPs) — the fix for the 1m bulk
        download timing the container's gRPC stream out. Read-only on Binance, write-only to the isolated R2
        prefix — no DB, no order. Returns one manifest dict {pair, timeframe, rows, r2, skipped}."""
        return _download_one_slab(pair, timeframe, market, start, end)

    @app.function(**_ENGINE)
    def compute_astro_tensor(start: str, end: str) -> dict:
        """PHASE2 worker: compute the DAILY astro feature tensor ONCE over the run's date span (reuse
        AF.deep_astro_features + the calendar/space-weather joins run_lab uses) and write it to R2. Deterministic
        geometry, no look-ahead, ~25 MB. Returns {rows, cols, r2}."""
        return _compute_astro_tensor_core(start, end)


# ── PHASE1 core: data.binance.vision → Parquet on R2 (pure; runs in-container) ──────────────────────


def _slab_batch_id(pair: str, tf: str) -> str:
    """The deterministic LabStore batch-id (and hence R2 key) for one (pair × timeframe) slab."""
    return f"{pair}/{tf}/{pair}-{tf}"


def _slab_done(store, pair: str, tf: str) -> bool:
    """RESUME guard: True when this slab's Parquet already exists (R2 when ready, else the local mirror), so a
    re-run SKIPS pairs already written instead of re-downloading. Best-effort — any read hiccup means 'not done'
    and we simply re-fetch (never a false 'done', so we never silently drop a slab)."""
    batch_id = _slab_batch_id(pair, tf)
    local_path = store.local / f"{batch_id}.parquet"
    if local_path.exists() and local_path.stat().st_size > 0:
        return True
    if not store.r2_ready:
        return False
    try:  # cheap existence probe against the exact R2 key
        con = store._conn()
        try:
            n = con.execute(
                f"SELECT count(*) FROM read_parquet('{store.r2_uri(batch_id)}')"
            ).fetchone()[0]
            return int(n) > 0
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — key absent / transient list error → treat as not-done, re-fetch
        return False


def _fetch_month_zip(url: str, cols, *, attempts: int = 4, timeout: int = 45):
    """Fetch ONE monthly bulk ZIP with bounded retries + exponential backoff. Returns the parsed DataFrame, or
    None when the month genuinely isn't listed (HTTP 404 — pair not live yet) or every attempt fails. Retrying
    here (not at the container level) keeps a single flaky month from forcing a whole-slab container retry."""
    import io
    import time
    import urllib.error
    import urllib.request
    import zipfile

    import pandas as pd

    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read()
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                name = zf.namelist()[0]
                return pd.read_csv(zf.open(name), header=None, names=cols)
        except urllib.error.HTTPError as e:  # 404 = month not published (honest absence) → stop retrying
            if e.code == 404:
                return None
            time.sleep(0.5 * (2**i))
        except Exception:  # noqa: BLE001 — transient network/stream error → backoff + retry
            time.sleep(0.5 * (2**i))
    return None


def _download_one_slab(pair: str, timeframe: str, market: str, start: str, end: str) -> dict:
    """Download the monthly bulk ZIPs from data.binance.vision for ONE (pair × timeframe), concat to a tidy
    OHLCV frame, and persist a single immutable Parquet to the isolated R2 prefix via LabStore. SMALL + bounded
    (one timeframe's months) so the container's gRPC stream never times out the way the all-timeframes-in-one
    worker did. Pure + read-only on the network; the only write is immutable Parquet under 'astro_deepdive/bars/'.

    RESUME: if the slab's Parquet already exists, returns {skipped: True} WITHOUT re-downloading. A slab whose
    months are all unlisted yields an honest {rows: 0} manifest, never fabricated bars.
    """
    _ensure_research_path()  # container: put the research helper dirs on sys.path before importing them
    import pandas as pd

    from lab_store import LabStore  # reused durable store, pointed at the deepdive prefix

    store = LabStore(prefix=f"{R2_PREFIX}/bars", local_dir=f".cosmu/{R2_PREFIX}/bars")
    if _slab_done(store, pair, timeframe):
        return dict(pair=pair, timeframe=timeframe, rows=0, r2=store.r2_uri(_slab_batch_id(pair, timeframe)),
                    skipped=True)

    seg = {"spot": "spot", "um": "futures/um", "cm": "futures/cm"}.get(market, "spot")
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbav", "tbqv", "ignore"]

    a, b = pd.Timestamp(start), pd.Timestamp(end)
    months = [d.strftime("%Y-%m") for d in pd.date_range(a, b, freq="MS")]

    frames: list[pd.DataFrame] = []
    for ym in months:
        url = f"{BINANCE_VISION_BASE}/{seg}/monthly/klines/{pair}/{timeframe}/{pair}-{timeframe}-{ym}.zip"
        df = _fetch_month_zip(url, cols)
        if df is not None:
            frames.append(df)
    if not frames:
        return dict(pair=pair, timeframe=timeframe, rows=0, r2=None, skipped=False)

    bars = pd.concat(frames, ignore_index=True)
    bars["ts"] = pd.to_datetime(bars["open_time"], unit="ms", utc=True).dt.tz_localize(None)
    bars = bars[["ts", "open", "high", "low", "close", "volume"]].drop_duplicates("ts").sort_values("ts")
    paths = store.save_batch(bars, _slab_batch_id(pair, timeframe))
    return dict(pair=pair, timeframe=timeframe, rows=int(len(bars)), r2=paths.get("r2"), skipped=False)


# ── PHASE2 core: the DAILY astro feature tensor (reuse AF.deep_astro_features) ───────────────────────


def _compute_astro_tensor_core(start: str, end: str) -> dict:
    """Compute the deterministic DAILY astro panel over [start, end] ONCE and write it to R2. Reuses exactly
    what run_lab builds: AF.deep_astro_features ⋈ calendar ⋈ extra ⋈ space-weather. ~25 MB, knowable at each
    day's start (no look-ahead). Returns {rows, cols, r2}."""
    _ensure_research_path()  # container: put the research helper dirs on sys.path before importing them
    import pandas as pd

    import astro_deep_study as S
    import astro_features_deep as AF
    from lab_store import LabStore

    dates = pd.DatetimeIndex(pd.date_range(start, end, freq="D"))
    panel = AF.deep_astro_features(dates).join(S.calendar_features(dates))
    ex = S._extra_feats(dates)
    panel = panel.join(ex[[c for c in ex.columns if c not in panel.columns]])
    sw = S.load_spaceweather(dates)
    panel = panel.join(sw[[c for c in sw.columns if c not in panel.columns]])

    store = LabStore(prefix=f"{R2_PREFIX}/tensor", local_dir=f".cosmu/{R2_PREFIX}/tensor")
    out = panel.reset_index(names="date")
    paths = store.save_batch(out, "astro_daily_tensor")
    return dict(rows=int(len(panel)), cols=int(panel.shape[1]), r2=paths.get("r2"))


# ── PHASE3/4: backtest + permutation-null sweep, then aggregate + deflate ────────────────────────────


def _build_sweep_jobs(config: DeepDiveConfig, panel, ret_panel) -> tuple[list[dict], list[dict]]:
    """Enumerate the labeled astro configs (REUSE run_lab.enumerate_configs) and run the vectorized backtest
    (REUSE run_lab.backtest_config) to produce the trial rows; build the modal_sweep perm-null payloads for the
    candidates (REUSE modal_sweep.make_job / _perm_cv_core). Returns (trial_rows, perm_jobs).

    The vectorized backtest is the cheap full pass; the perm-null is fanned out (PHASE3 on Modal). Encoding the
    candidate selection as a raw |Sharpe| pre-screen keeps the EXPENSIVE B=n_perm null off the long tail of
    obvious-noise configs while still counting EVERY config in the deflation denominator (PHASE4)."""
    import numpy as np

    import run_lab as RL
    import modal_sweep as MS

    configs = RL.enumerate_configs(panel, cap=config.n_configs)
    trial_rows: list[dict] = []
    for cfg in configs:
        trial_rows.extend(RL.backtest_config(cfg, panel, ret_panel, fee_bps=config.fee_bps))

    # Candidate pre-screen for the perm-null fan-out (does NOT shrink the deflation N — that stays = all trials).
    perm_jobs: list[dict] = []
    if trial_rows:
        import pandas as pd

        tr = pd.DataFrame(trial_rows)
        cand = tr.reindex(tr["sharpe"].abs().sort_values(ascending=False).index).head(
            config.n_sweep_containers() * 50
        )
        # One perm-null job per candidate (asset × config): label-permutation AUC null on the position series.
        # We feed the candidate's market-wide signal + the asset's up/down label as a minimal X/y/dates triple.
        for _, row in cand.iterrows():
            cfg = next((c for c in configs if c["config_id"] == row["config_id"]), None)
            if cfg is None:
                continue
            asset = row["asset"]
            if asset not in ret_panel.columns:
                continue
            pos = RL.position_series(cfg, panel)
            r = ret_panel[asset]
            idx = r.dropna().index
            X = np.nan_to_num(pd.Series(pos, index=panel.index).reindex(idx).to_numpy(float)).reshape(-1, 1)
            y = (r.reindex(idx).to_numpy(float) > 0).astype(int)
            dates = idx.values
            perm_jobs.append(
                MS.make_job(
                    asset=f"{asset}:{cfg['config_id']}", group=cfg["school"], model="hgb",
                    X=X, y=y, dates=dates, n_perm=config.n_perm, seed=config.seed,
                )
            )
    return trial_rows, perm_jobs


def _aggregate_and_deflate(config: DeepDiveConfig, trial_rows: list[dict], perm_rows: list[dict]) -> dict:
    """PHASE4: charge Deflated Sharpe at the TRUE trial count (EVERY config × asset trial) and merge the
    permutation p-values for the candidates. Writes the aggregate to R2 and returns the verdict dict. Reuses
    ml_harness.deflated_sharpe — the same DSR the rest of the lab uses."""
    import numpy as np
    import pandas as pd

    import ml_harness as ML
    from lab_store import LabStore

    if not trial_rows:
        return dict(n_trials=0, survivors=0, note="no trials produced")

    df = pd.DataFrame(trial_rows)
    N = int(len(df))  # the honest denominator: every (config × asset × encoding) trial counted
    df["dsr"] = [
        ML.deflated_sharpe(s / np.sqrt(252 if not a.endswith("USDT") else 365), N, int(n), 0.0, 3.0)
        for s, n, a in zip(df["sharpe"], df["n"], df["asset"])
    ]
    if perm_rows:
        perm = pd.DataFrame(perm_rows)
        df = df.merge(
            perm.assign(
                asset=perm["asset"].str.split(":").str[0],
                config_id=perm["asset"].str.split(":").str[1],
            )[["asset", "config_id", "p"]],
            on=["asset", "config_id"], how="left",
        )
    survivors = df[df["dsr"] > 0.95]
    store = LabStore(prefix=f"{R2_PREFIX}/results", local_dir=f".cosmu/{R2_PREFIX}/results")
    store.save_batch(df, "deepdive_trials")
    verdict = dict(
        n_trials=N,
        survivors=int(len(survivors)),
        raw_best_sharpe=float(df["sharpe"].max()),
        perm_tested=int(len(perm_rows)),
        note=("INVESTIGATE — forward-test required" if len(survivors)
              else "NULL — 0 survive deflation at the true trial count (astro closed)"),
    )
    return verdict


# ── orchestrator ─────────────────────────────────────────────────────────────────────────────────────


def run_astro_deepdive_modal(config: DeepDiveConfig, *, prepare_only: bool = False) -> dict:
    """The 5-phase deep-dive orchestrator. PHASE0 ALWAYS runs locally (validate + announce scope/cost). When
    `prepare_only` (the CLI `--mode prepare`), it STOPS after PHASE0 having spent $0 — no Modal call. Otherwise
    it runs PHASE1–4 on Modal, accruing container-hours into a CostTracker that ABORTS the remaining phases the
    moment estimated spend crosses 0.8×budget."""
    from astro_deepdive_modal.cost_tracker import CostTracker

    # ── PHASE0: local validate + announce (no spend) ──────────────────────────────────────────────
    scope = config.scope_summary()
    print("─" * 78)
    print("ASTRO FULL DEEP-DIVE — PHASE0 (local validate + scope announce)")
    print("─" * 78)
    print(json.dumps(scope, indent=2))
    print(f"\nR2 layout (isolated prefix '{R2_PREFIX}/'):")
    print(f"  bars   : r2://<bucket>/{R2_PREFIX}/bars/<pair>/<timeframe>/*.parquet")
    print(f"  tensor : r2://<bucket>/{R2_PREFIX}/tensor/astro_daily_tensor.parquet")
    print(f"  results: r2://<bucket>/{R2_PREFIX}/results/deepdive_trials.parquet")
    print(
        f"\nEstimated Modal spend ≈ ${scope['est_modal_usd']} "
        f"(budget ${scope['budget_usd']}, hard STOP at ${scope['stop_at_usd']}).\n"
        "Expected outcome (pre-registered): a documented NULL. See docs/research/astro_final_deepdive_PLAN.md.\n"
    )
    if not config.download_spec.pairs:
        raise SystemExit("[abort] download_spec.pairs is empty — nothing to download.")

    if prepare_only:
        print("[prepare] PHASE0 only — no Modal launched, $0 spent. Re-run with --mode run to execute.")
        return dict(phase="prepare", scope=scope, spent_usd=0.0)

    if not _MODAL_OK:
        raise SystemExit("[abort] modal is not importable — install modal to run the deep-dive (--mode run).")

    ct = CostTracker(budget_usd=config.modal_budget_usd, container_hr_usd=config.container_hr_usd)
    ds = config.download_spec
    results: dict = {"scope": scope}

    with app.run():
        # ── PHASE1: data.binance.vision → R2 (fan-out one container per pair×timeframe SLAB) ───────
        # Smaller slabs + retries=2 + return_exceptions=True: a slab that loses its gRPC stream is retried on a
        # fresh container and, if it still fails, surfaces as an honest error row WITHOUT killing the whole map.
        # resume-from-R2 lives in the worker (_slab_done), so a re-run skips slabs already written.
        print(f"\n[PHASE1] download {len(ds.pairs)} pairs × {ds.timeframes} → r2://…/{R2_PREFIX}/bars/ "
              f"({config.n_download_containers()} slabs)")
        dl_jobs = [(p, tf, ds.market, ds.start, ds.end) for p in ds.pairs for tf in ds.timeframes]
        manifests: list[dict] = []
        errs: list[str] = []
        for m in download_binance_vision_slab.starmap(dl_jobs, order_outputs=False, return_exceptions=True):
            if isinstance(m, Exception):
                errs.append(str(m)[:300])
                manifests.append(dict(pair="?", timeframe="?", rows=0, r2=None, error=str(m)[:300]))
            else:
                manifests.append(m)
        n_ok = sum(1 for m in manifests if m.get("rows", 0) > 0 or m.get("skipped"))
        n_skip = sum(1 for m in manifests if m.get("skipped"))
        print(f"   PHASE1 slabs: {n_ok} ok ({n_skip} resumed) · {len(errs)} errored (of {len(dl_jobs)})")
        if errs:  # surface the FIRST exception so a systematic failure (bad import/creds) is diagnosable
            print(f"   PHASE1 first error: {errs[0]}")
        results["download"] = manifests
        ct.add_container_hours(
            ct.estimate_phase_hours(config.n_download_containers(), config.download_wall_hours),
            label="phase1_download",
        )
        if ct.checkpoint("PHASE1 download done").should_stop:
            results["aborted_after"] = "phase1"
            return {**results, "cost": ct.summary()}

        # ── PHASE2: DAILY astro feature tensor (computed once) → R2 ────────────────────────────────
        print(f"\n[PHASE2] daily astro feature tensor → r2://…/{R2_PREFIX}/tensor/")
        results["tensor"] = compute_astro_tensor.remote(ds.start, ds.end)
        ct.add_container_hours(0.25, label="phase2_tensor")
        if ct.checkpoint("PHASE2 tensor done").should_stop:
            results["aborted_after"] = "phase2"
            return {**results, "cost": ct.summary()}

        # ── PHASE3: backtest + permutation-null sweep (fan-out) → R2 ───────────────────────────────
        # The vectorized full backtest + job-building runs on the driver (cheap); the B=n_perm permutation
        # null is fanned out to Modal containers (the expensive part) via the reused run_sweep_modal.
        print(f"\n[PHASE3] backtest + B={config.n_perm} permutation-null sweep → Modal fan-out")
        import modal_sweep as MS

        panel, ret_panel = _load_panel_for_sweep(config)
        trial_rows, perm_jobs = _build_sweep_jobs(config, panel, ret_panel)
        print(f"   {len(trial_rows)} trial rows · {len(perm_jobs)} candidate perm-null jobs")
        perm_rows = MS.run_sweep_modal(perm_jobs, return_exceptions=True) if perm_jobs else []
        ct.add_container_hours(
            ct.estimate_phase_hours(config.n_sweep_containers(), config.sweep_wall_hours)
            * max(1.0, config.n_perm / 1000.0),
            label="phase3_sweep",
        )
        if ct.checkpoint("PHASE3 sweep done").should_stop:
            results["aborted_after"] = "phase3"
            return {**results, "cost": ct.summary()}

    # ── PHASE4: aggregate + Deflated-Sharpe at the TRUE trial count → R2 (local, cheap) ───────────
    print(f"\n[PHASE4] aggregate + Deflated-Sharpe at the true trial count → r2://…/{R2_PREFIX}/results/")
    results["verdict"] = _aggregate_and_deflate(config, trial_rows, perm_rows)
    ct.checkpoint("PHASE4 aggregate done")
    results["cost"] = ct.summary()
    print("\n" + json.dumps(results["verdict"], indent=2))
    return results


def _load_panel_for_sweep(config: DeepDiveConfig):
    """Build the (astro panel, return panel) the sweep needs. On Modal we'd read the PHASE1/PHASE2 Parquet back
    from R2; here we reconstruct deterministically the same way run_lab does so the driver stays self-contained.
    Kept tiny + lazy so `--mode prepare` never imports the heavy stack."""
    import numpy as np
    import pandas as pd

    import astro_deep_study as S
    import astro_features_deep as AF
    import real_panel as RP

    ds = config.download_spec
    crypto = [p for p in ds.pairs if p.endswith("USDT")]
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars = {s: b for s, b in bars.items() if len(b) >= 500}
    dates = pd.DatetimeIndex(sorted({d for b in bars.values() for d in b.index}))
    panel = AF.deep_astro_features(dates).join(S.calendar_features(dates))
    ex = S._extra_feats(dates)
    panel = panel.join(ex[[c for c in ex.columns if c not in panel.columns]])
    sw = S.load_spaceweather(dates)
    panel = panel.join(sw[[c for c in sw.columns if c not in panel.columns]])
    ret_panel = pd.DataFrame({s: np.log(b["close"]).diff() for s, b in bars.items()}).reindex(dates)
    return panel, ret_panel


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────


def _config_from_args(args: argparse.Namespace) -> DeepDiveConfig:
    spec = DownloadSpec()
    if args.pairs:
        spec.pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    if args.timeframes:
        spec.timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    if args.start:
        spec.start = args.start
    if args.end:
        spec.end = args.end
    return DeepDiveConfig(
        download_spec=spec,
        n_configs=args.n_configs,
        n_perm=args.n_perm,
        fee_bps=args.fee_bps,
        modal_budget_usd=args.budget,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Astro FULL deep-dive Modal harness (research-only, isolated 'astro_deepdive' R2 prefix)."
    )
    ap.add_argument("--mode", choices=("prepare", "run"), default="prepare",
                    help="prepare = print scope + cost + R2 layout and EXIT ($0 spend); run = execute PHASE1–4 on Modal.")
    ap.add_argument("--pairs", default="", help="comma list of Binance pairs (default: 5-pair representative slice)")
    ap.add_argument("--timeframes", default="", help="comma list, e.g. 1d,1h,1m (default 1d,1h,1m)")
    ap.add_argument("--start", default="", help="ISO date, e.g. 2017-08-01")
    ap.add_argument("--end", default="", help="ISO date, e.g. 2026-06-01")
    ap.add_argument("--n-configs", dest="n_configs", type=int, default=4000)
    ap.add_argument("--n-perm", dest="n_perm", type=int, default=1000)
    ap.add_argument("--fee-bps", dest="fee_bps", type=float, default=10.0)
    ap.add_argument("--budget", type=float, default=110.0, help="Modal budget USD (hard STOP at 0.8×)")
    args = ap.parse_args()

    config = _config_from_args(args)
    if args.mode == "prepare":
        run_astro_deepdive_modal(config, prepare_only=True)
    else:
        out = run_astro_deepdive_modal(config, prepare_only=False)
        print("\n[done]", json.dumps(out.get("verdict", out.get("aborted_after", "ok")), default=str))


if __name__ == "__main__":
    main()
