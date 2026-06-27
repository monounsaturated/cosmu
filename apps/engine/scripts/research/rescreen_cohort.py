# intent: the LOT-C RE-SCREEN HARNESS — re-run a cohort of KILLED specs at the DEEP window (+ optional multi-timeframe)
# in MEASURE-ONLY mode, to quantify how many killed specs WOULD survive at full depth / multi-tf BEFORE touching any
# production default. It answers ONE question — "is the kill verdict an artifact of the shallow 1000/1500-bar screen
# window (or the single-timeframe screen), or a real no-edge?" — and answers it WITHOUT moving money: it never writes
# backtest_symbols / tracks / strategy_versions, never opens a paper track, never touches a Gate constant.
#
# HOW IT STAYS MEASURE-ONLY (the safety contract):
#   • StrategyFinder.find(spec, persist=False) is called with persist=False, so _persist (the ONLY writer of
#     backtest_symbols / tracks / survivor events) is never invoked. The harness reads the in-memory FinderReport and
#     prints/serializes it — it opens no Writer and commits no transaction.
#   • The DEEP window is requested via the EXPLICIT env knob COSMU_SCREEN_DEEP (set for THIS process only), the same
#     opt-in finder._market / loop._bar_limit honour. With --shallow the env is left unset → today's 1500/1000 window
#     (so the harness can A/B the two windows on the SAME specs).
#   • Multi-timeframe is requested via --timeframes (e.g. 1h,4h,1d): each killed spec is model_copy'd with
#     horizon.bar_sizes = the requested list, so find() screens it once per tf (each its own brut cell). Default: the
#     spec's own single bar_size (byte-identical to its original kill screen except for the window).
#   • The report is DISPOSABLE: a local JSON + (when R2 is configured) an R2 object under research/rescreen_cohort/.
#     Re-funding a flipped cohort would be a SEPARATE, explicitly-flagged step — OUT OF SCOPE here.
#
# VERDICT-DRIFT is the headline finding AND the headline risk: a deeper window changes a cell's bar_returns/
# fold_returns and therefore its DSR/PBO verdict. A killed spec may flip to "would-pass". That is exactly what we are
# MEASURING — it is observed, never shipped. We surface per-spec the realized bar count, the effective-N, and the
# validation window so a deep "would-survive" on a thin 150-day cache is not read as fact (the forward/paper gate is
# still the brut fluke safeguard; a deep screen on a thin cache silently behaves shallow — see the depth helper).
#
# Run (heavy compute → Modal per memory spend_and_compute_discipline; needs the operator's local deep bar cache):
#   python3 apps/engine/scripts/research/rescreen_cohort.py [--limit N] [--timeframes 1h,4h,1d] [--shallow]
#                                                            [--strategy NAME] [--max-variants N] [--out PATH]

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Make the engine package importable when run as a bare script.
_ENGINE_ROOT = Path(__file__).resolve().parents[2]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from cosmu.config.settings import Settings  # noqa: E402
from cosmu.knowledge.store import Store  # noqa: E402
from cosmu.lab.depth import DEEP_BAR_LIMIT  # noqa: E402
from cosmu.strategy.spec import StrategySpec  # noqa: E402

_DEEP_ENV = "COSMU_SCREEN_DEEP"
_R2_PREFIX = "research/rescreen_cohort"


@dataclass
class SpecVerdict:
    """One killed spec's re-screen result. `would_pass` is True iff the deep/multi-tf re-screen produced ANY surviving
    cell (gate + own-holdout) — a MEASURE-ONLY flag, never a promotion. Per-cell rows carry the realized window so a
    thin-cache 'survivor' is not read as fact."""

    strategy_name: str
    version_id: str
    original_status: str
    kill_reason: str | None
    screened_cells: int
    gate_passed_cells: int
    would_pass: bool
    timeframes: list[str]
    cells: list[dict] = field(default_factory=list)
    error: str | None = None


def _load_killed_specs(
    store: Store, *, limit: int, strategy: str | None, version_ids: list[str] | None = None
) -> list[tuple[str, str, str | None, StrategySpec]]:
    """Load up to `limit` KILLED versions' specs from the store, newest-first. Returns
    [(version_id, strategy_name, kill_reason, StrategySpec)]. A spec that fails to validate is skipped (never crashes the
    harness). Optionally narrows to one strategy NAME.

    When `version_ids` is given (an OPT-IN explicit cohort — e.g. the luck-farm thin-crypto-price selection), ONLY those
    KILLED versions are loaded, in the GIVEN order (so a caller can pre-rank highest-EV first), and `limit`/`strategy`
    are ignored. The status='killed' guard is kept so the harness never re-screens a live/paper version by id. Default
    (version_ids None) is byte-identical to before — newest-first up to `limit`."""
    conds = ["sv.status = ?"]
    params: list[object] = ["killed"]
    if version_ids:
        placeholders = ",".join(["?"] * len(version_ids))
        conds.append(f"sv.id IN ({placeholders})")
        params.extend(version_ids)
        where = " AND ".join(conds)
        rows = store.rows(
            "SELECT sv.id AS version_id, s.name AS strategy_name, sv.kill_reason, sv.spec "
            "FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id "
            f"WHERE {where}",
            tuple(params),
        )
        # Preserve the caller's requested order (highest-EV first) — the SQL IN-list does not guarantee it.
        order = {vid: i for i, vid in enumerate(version_ids)}
        rows = sorted(rows, key=lambda r: order.get(r["version_id"], len(order)))
    else:
        if strategy:
            conds.append("s.name = ?")
            params.append(strategy)
        where = " AND ".join(conds)
        rows = store.rows(
            "SELECT sv.id AS version_id, s.name AS strategy_name, sv.kill_reason, sv.spec "
            "FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id "
            f"WHERE {where} ORDER BY sv.created_at DESC LIMIT ?",
            (*params, int(limit)),
        )
    out: list[tuple[str, str, str | None, StrategySpec]] = []
    for r in rows:
        raw = r["spec"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                continue
        if not raw:
            continue
        try:
            spec = StrategySpec.model_validate(raw)
        except Exception:  # noqa: BLE001 — a legacy/invalid spec is skipped, never aborts the cohort
            continue
        out.append((r["version_id"], r["strategy_name"], r.get("kill_reason"), spec))
    return out


def _with_timeframes(spec: StrategySpec, timeframes: list[str] | None) -> StrategySpec:
    """Return `spec` unchanged when no timeframe override is requested (single-tf re-screen on the spec's own
    bar_size), else a model_copy whose horizon.bar_sizes is the requested list (find() then screens once per tf)."""
    if not timeframes:
        return spec
    return spec.model_copy(update={"horizon": spec.horizon.model_copy(update={"bar_sizes": list(timeframes)})})


def _rescreen_one(
    finder, version_id: str, strategy_name: str, kill_reason: str | None,  # noqa: ANN001 — StrategyFinder
    spec: StrategySpec, timeframes: list[str] | None, *, max_variants: int,
) -> SpecVerdict:
    """Re-screen ONE killed spec measure-only (persist=False) and summarize its per-cell verdicts. Never writes."""
    rescreen_spec = _with_timeframes(spec, timeframes)
    tfs = rescreen_spec.horizon.timeframes()
    try:
        report = finder.find(rescreen_spec, persist=False, max_variants=max_variants)
    except Exception as exc:  # noqa: BLE001 — one unscreenable spec never aborts the cohort
        return SpecVerdict(
            strategy_name=strategy_name, version_id=version_id, original_status="killed",
            kill_reason=kill_reason, screened_cells=0, gate_passed_cells=0, would_pass=False,
            timeframes=tfs, error=f"{type(exc).__name__}: {exc}",
        )
    # Flatten the report's per-variant cells into measure-only rows. A cell "would_pass" iff it cleared the gate AND its
    # own holdout — the SAME brut survivor definition find() uses, just never persisted.
    cells: list[dict] = []
    gate_cells = 0
    for r in report.leaderboard + report.survivors:
        for _sym, cell in r.cells.items():
            if cell.passed:
                gate_cells += 1
            cells.append({
                "config_tag": r.config_tag,
                "timeframe": r.timeframe,
                "symbol": cell.symbol,
                "venue_id": cell.venue_id,
                "trades": cell.trades,
                "deflated_sharpe": round(float(cell.deflated_sharpe), 6),
                "gate_passed": bool(cell.passed),
                "holdout_passed": bool(cell.holdout_passed),
                "oos_window_days": cell.oos_window_days,
                "would_survive": bool(cell.passed and cell.holdout_passed),
            })
    return SpecVerdict(
        strategy_name=strategy_name, version_id=version_id, original_status="killed",
        kill_reason=kill_reason, screened_cells=len(cells), gate_passed_cells=gate_cells,
        would_pass=len(report.survivors) > 0, timeframes=tfs, cells=cells,
    )


def _persist_report(settings: Settings, payload: dict, out_path: Path) -> str:
    """Write the disposable report to LOCAL (always) + R2 (when configured). Returns a human note of where it landed.
    NEVER writes a prod table — this is a research artifact only."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    where = [str(out_path)]
    if all((settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket)):
        try:
            import boto3

            s3 = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )
            key = f"{_R2_PREFIX}/{payload['run_id']}.json"
            s3.put_object(
                Bucket=settings.r2_bucket, Key=key,
                Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                ContentType="application/json",
            )
            where.append(f"r2://{settings.r2_bucket}/{key}")
        except Exception as exc:  # noqa: BLE001 — R2 is best-effort; the local artifact is the source of truth
            where.append(f"(R2 upload skipped: {type(exc).__name__})")
    return " + ".join(where)


def main() -> int:
    ap = argparse.ArgumentParser(description="LOT-C measure-only re-screen of killed specs at deep window / multi-tf.")
    ap.add_argument("--limit", type=int, default=50, help="max killed specs to re-screen (newest-first)")
    ap.add_argument("--timeframes", type=str, default=None, help="comma-separated tf list (e.g. 1h,4h,1d); default = each spec's own bar_size")
    ap.add_argument("--shallow", action="store_true", help="screen at TODAY's 1500/1000 window instead of deep (A/B baseline)")
    ap.add_argument("--strategy", type=str, default=None, help="narrow to one strategy NAME")
    ap.add_argument("--version-ids-file", type=str, default=None,
                    help="OPT-IN: path to a file of killed version_ids (one per line, order = priority) — re-screen "
                         "EXACTLY this cohort (e.g. the luck-farm thin-crypto-price set). Ignores --limit/--strategy.")
    ap.add_argument("--max-variants", type=int, default=24, help="grid cap per spec (keep small; this is a probe)")
    ap.add_argument("--out", type=str, default=None, help="local report path (default: .cosmu/research/rescreen_cohort_<ts>.json)")
    args = ap.parse_args()

    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()] if args.timeframes else None

    # DEEP is the DEFAULT for this harness (the whole point), unless --shallow. Set the env knob for THIS process only —
    # finder._market / loop._bar_limit route through screen_depth() which reads it. Restored on exit so the env knob
    # never leaks to a co-running process.
    prev_deep = os.environ.get(_DEEP_ENV)
    if args.shallow:
        os.environ.pop(_DEEP_ENV, None)
    else:
        os.environ[_DEEP_ENV] = "1"

    try:
        settings = Settings()
        store = Store(settings)
        # Lazy import so setting the env knob above is in effect before the finder module resolves the depth helper.
        from cosmu.lab.finder import StrategyFinder

        finder = StrategyFinder(settings=settings, store=store)
        version_ids = None
        if args.version_ids_file:
            version_ids = [ln.strip() for ln in Path(args.version_ids_file).read_text().splitlines() if ln.strip()]
        specs = _load_killed_specs(store, limit=args.limit, strategy=args.strategy, version_ids=version_ids)
        print(f"re-screening {len(specs)} killed specs "
              f"({'SHALLOW 1500/1000' if args.shallow else f'DEEP {DEEP_BAR_LIMIT}'} window, "
              f"timeframes={timeframes or 'spec-own'}) — MEASURE ONLY, no prod write")

        verdicts: list[SpecVerdict] = []
        for i, (vid, name, kill_reason, spec) in enumerate(specs, 1):
            v = _rescreen_one(finder, vid, name, kill_reason, spec, timeframes, max_variants=args.max_variants)
            verdicts.append(v)
            flag = "WOULD-PASS" if v.would_pass else ("ERROR" if v.error else "still-killed")
            print(f"  [{i}/{len(specs)}] {name} ({vid[:8]}) → {flag} "
                  f"(cells={v.screened_cells}, gate={v.gate_passed_cells}{', ' + v.error if v.error else ''})")
    finally:
        # Restore the env knob exactly as it was (never leak the deep flag to the rest of the process tree).
        if prev_deep is None:
            os.environ.pop(_DEEP_ENV, None)
        else:
            os.environ[_DEEP_ENV] = prev_deep

    would_pass = sum(1 for v in verdicts if v.would_pass)
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    payload = {
        "run_id": run_id,
        "measure_only": True,
        "deep_window": not args.shallow,
        "bar_limit_sentinel": DEEP_BAR_LIMIT if not args.shallow else None,
        "timeframes_requested": timeframes,
        "strategy_filter": args.strategy,
        "killed_specs_rescreened": len(verdicts),
        "would_pass_count": would_pass,
        "would_pass_rate": round(would_pass / len(verdicts), 4) if verdicts else 0.0,
        "verdicts": [
            {
                "strategy_name": v.strategy_name, "version_id": v.version_id,
                "kill_reason": v.kill_reason, "screened_cells": v.screened_cells,
                "gate_passed_cells": v.gate_passed_cells, "would_pass": v.would_pass,
                "timeframes": v.timeframes, "error": v.error, "cells": v.cells,
            }
            for v in verdicts
        ],
    }
    out_path = Path(args.out) if args.out else (_ENGINE_ROOT / ".cosmu" / "research" / f"rescreen_cohort_{run_id}.json")
    where = _persist_report(settings, payload, out_path)
    print(f"\nMEASURE-ONLY re-screen complete: {would_pass}/{len(verdicts)} killed specs WOULD survive "
          f"({payload['would_pass_rate'] * 100:.1f}%) at "
          f"{'shallow' if args.shallow else 'deep'} window. Report → {where}")
    print("NOTE: would-pass is OBSERVED drift, never shipped — no prod table written, no track opened, no money moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
