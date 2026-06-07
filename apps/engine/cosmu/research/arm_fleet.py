"""arm_fleet.py — one-command entrypoint to arm the full equity forward-test fleet.

Calls each equity *_arm.py module's arm() function in declaration order, honours
idempotency (each arm() skips already-armed tracks), is offline-safe (arm() defers
the price fill when Yahoo is unreachable, the track still registers), and is SIM-only
(live stays OFF in every child module — no real orders, no money moved).

Usage
-----
# Arm the whole fleet (idempotent):
    python3 -m cosmu.research.arm_fleet

# Dry-run — verify all modules import cleanly and list what WOULD be armed:
    python3 -m cosmu.research.arm_fleet --dry-run

# Arm a single strategy (useful on first-time setup or re-runs):
    python3 -m cosmu.research.arm_fleet --only faber_gtaa

Deploy / cloud
--------------
Railway / Modal (no node_modules needed, pure Python):
    PYTHONPATH=apps/engine python3 -m cosmu.research.arm_fleet

Modal one-shot stub (example):
    modal run apps/engine/cosmu/research/arm_fleet.py::arm_all   # if wired as a Modal fn

Invariants
----------
- NEVER touches live-mode flags; every child arm() is explicitly SIM-only.
- Never loosens any Gate threshold — arm() calls validate() inside each module; if
  the strategy fails its deployment bar the arm() returns {"armed": False} and this
  script marks it FAILED (not SKIPPED) and prints the reason.
- Deterministic for a fixed store + market data.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------
# Fleet registry — canonical order, short aliases for --only
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    alias: str                              # short name for --only / display
    module: str                             # dotted Python module path
    label: str                              # human label printed in the summary
    arm_fn: Callable | None = field(default=None, repr=False)  # populated at import


_FLEET: list[_Entry] = [
    _Entry("faber_gtaa",         "cosmu.research.equity_faber_gtaa_arm",         "Faber GTAA (5-asset 10mo SMA)"),
    _Entry("accel_dual_momentum","cosmu.research.equity_accel_dual_momentum_arm", "Accelerating Dual Momentum (ADM)"),
    _Entry("risk_parity",        "cosmu.research.equity_risk_parity_arm",         "Risk Parity (Inverse-Vol SPY/AGG/GLD)"),
    _Entry("vaa",                "cosmu.research.equity_vaa_arm",                 "Vigilant Asset Allocation (VAA-G4)"),
    _Entry("tsmom_trend",        "cosmu.research.equity_tsmom_trend_arm",         "Time-Series Momentum (TSMOM 5-ETF)"),
    _Entry("dual_momentum_qqq",  "cosmu.research.equity_dual_momentum_qqq_arm",   "Dual Momentum QQQ (tech-tilt)"),
    _Entry("sector_rotation",    "cosmu.research.equity_sector_rotation_arm",     "Sector-Momentum Rotation (TAA Top-3)"),
    _Entry("dual_momentum",      "cosmu.research.equity_dual_momentum_arm",       "Global Equities Momentum (GEM)"),
]

# Status codes used in the per-strategy result
_ARMED   = "armed"    # newly armed this run
_SKIPPED = "skipped"  # already armed (idempotent path — arm() returned armed=True + reused)
_FAILED  = "failed"   # arm() returned armed=False OR raised an exception


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _load_fleet(aliases: list[str] | None = None) -> list[_Entry]:
    """Import each fleet module and attach its arm() function (idempotent — skips
    entries whose arm_fn is already set so tests can inject mocks before calling
    arm_all).  Raises ImportError on a missing module so the caller knows the
    codebase is broken — do not swallow."""
    subset = _FLEET if not aliases else [e for e in _FLEET if e.alias in aliases]
    for entry in subset:
        if entry.arm_fn is None:  # do NOT overwrite a mock injected by a test
            mod = importlib.import_module(entry.module)
            entry.arm_fn = mod.arm  # every *_arm.py exports arm(store=None) -> dict
    return subset


def arm_all(
    *,
    dry_run: bool = False,
    only: list[str] | None = None,
    store=None,             # cosmu.knowledge.store.Store | None — injected in tests
) -> dict:
    """Arm (or dry-run) the full fleet.  Returns a summary dict with per-strategy
    outcomes plus aggregate counts.  Always prints a human-readable table.

    Parameters
    ----------
    dry_run : bool
        When True, import all modules and print what WOULD be armed, then exit without
        writing to the store.  Useful for CI smoke-checks.
    only : list[str] | None
        Restrict to these aliases (e.g. ["faber_gtaa", "vaa"]).  None = whole fleet.
    store : Store | None
        Optional pre-built Store to inject (avoids repeated DB connections in tests).
    """
    entries = _load_fleet(only)

    results: dict[str, dict] = {}

    if dry_run:
        print("\n[arm_fleet] DRY-RUN — no DB writes\n")
        print(f"{'ALIAS':<25} {'MODULE':<50} STATUS")
        print("-" * 90)
        for e in entries:
            print(f"  {e.alias:<23} {e.module:<50} would-arm")
        print(f"\n{len(entries)} strategy/ies would be armed.  Pass no --dry-run to execute.\n")
        return {"dry_run": True, "would_arm": [e.alias for e in entries]}

    print(f"\n[arm_fleet] Arming {len(entries)} strategy/ies  (SIM-only, idempotent)\n")

    n_armed = n_skipped = n_failed = 0

    for entry in entries:
        print(f"--- {entry.label} ---")
        try:
            result: dict = entry.arm_fn(store)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001
            # arm() raised — treat as FAILED, print the traceback for diagnostics, continue
            tb = traceback.format_exc()
            print(f"  EXCEPTION in {entry.module}.arm():\n{tb}")
            results[entry.alias] = {"status": _FAILED, "error": str(exc)}
            n_failed += 1
            continue

        if not result.get("armed", False):
            reason = result.get("reason", "unknown")
            print(f"  NOT armed — reason: {reason}")
            results[entry.alias] = {"status": _FAILED, "reason": reason, "detail": result}
            n_failed += 1
        elif result.get("reused") or result.get("position_deferred") is False:
            # reused = position was already held (arm() confirmed idempotency)
            results[entry.alias] = {"status": _SKIPPED, "detail": result}
            n_skipped += 1
        else:
            results[entry.alias] = {"status": _ARMED, "detail": result}
            n_armed += 1

    # ---------------------------------------------------------------------------
    # Summary table
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"  arm_fleet SUMMARY   ({len(entries)} strategies)")
    print("=" * 60)
    col_w = max(len(e.alias) for e in entries) + 2
    for alias, res in results.items():
        status = res["status"].upper()
        detail = ""
        if res["status"] == _FAILED:
            detail = res.get("reason") or res.get("error") or ""
        print(f"  {alias:<{col_w}} {status}  {detail}")
    print("=" * 60)
    print(f"  armed={n_armed}  skipped={n_skipped}  failed={n_failed}")
    print("=" * 60 + "\n")

    return {
        "armed": n_armed,
        "skipped": n_skipped,
        "failed": n_failed,
        "strategies": results,
    }


# ---------------------------------------------------------------------------
# __main__ entry-point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in argv
    only: list[str] | None = None

    # --only faber_gtaa,vaa  OR  --only faber_gtaa --only vaa
    if "--only" in argv:
        idx = argv.index("--only")
        if idx + 1 < len(argv):
            # accept comma-separated or repeated --only flags
            raw = argv[idx + 1]
            only = [a.strip() for a in raw.split(",") if a.strip()]

    valid_aliases = {e.alias for e in _FLEET}
    if only:
        bad = [a for a in only if a not in valid_aliases]
        if bad:
            print(f"[arm_fleet] Unknown alias(es): {bad}. Valid: {sorted(valid_aliases)}", file=sys.stderr)
            return 2

    summary = arm_all(dry_run=dry_run, only=only)
    if summary.get("dry_run"):
        return 0
    return 1 if summary.get("failed", 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
