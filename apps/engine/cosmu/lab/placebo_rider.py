# intent: the PLACEBO COHORT-RIDER — the seam that turns the dormant negative-control empirical-null panel
# (research/placebo_panel.py) into a STANDING TRIPWIRE that rides EVERY finder cohort. After a cohort screens, the
# rider runs run_placebo_panel on the SAME real market the finder just used (the same tape its survivors were found
# on), logs PlaceboPanel.render(), and — CRITICAL — if ANY placebo cleared the LOCKED Gate (any_cleared=True, i.e.
# an upstream leak the Gate structurally cannot see) it logs LOUDLY (a structured WARNING + a best-effort
# placebo_leak event row). It is OBSERVE-ONLY / PROPOSE-ONLY: it NEVER blocks, fails, or alters the finder's live
# verdict — it reads the locked gate constants, never writes them, and the finder's promote_brut path is untouched.
#
# WHY A SEPARATE MODULE (not inline in finder.py): the rider is a pure, side-effect-bounded observer that can be
# unit-tested in isolation (the loud-log path, the event row, the OFF-by-default flag) without standing up a whole
# finder screen. finder.py calls ride_cohort() once per cohort behind the flag; everything else here is testable
# without the finder.
#
# THE FLAG: COSMU_PLACEBO_RIDER — DEFAULT OFF (mirrors lab/depth.COSMU_SCREEN_DEEP). When unset/falsey,
# ride_cohort() is a NO-OP that returns None immediately → the finder is byte-identical, zero extra backtests. Only
# when explicitly enabled does the panel run. This keeps a normal production screen unchanged while the instrument
# is validated as an autonomous-run POC.
#
# BOUNDEDNESS: the panel runs ~10 placebo specs × the market's symbols. To keep it cheap on the M2 / a cron, the
# rider CAPS the market it hands the panel to _MAX_RIDER_SYMBOLS symbols (a deterministic, stable-sorted slice of
# the SAME already-screened bars — no re-fetch, no new data) and uses the panel's small default n_per_family. The
# panel reuses the same backtest/metrics/promote_brut path the finder already paid for the imports of, so the only
# added cost is the bounded placebo backtests, run at most once per cohort.

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from cosmu.config.settings import GateSettings
from cosmu.data.market import Bar
from cosmu.research.placebo_panel import (
    PlaceboPanel,
    SurvivorVsNull,
    compare_survivor_to_null,
    run_placebo_panel,
)

_LOG = logging.getLogger(__name__)

# The opt-in env knob — DEFAULT OFF (mirrors lab/depth.COSMU_SCREEN_DEEP). When unset/falsey the rider is a no-op
# and the finder is byte-identical. An EXECUTION-TIME knob (env), never a persisted spec field / a gate input.
_RIDER_ENV = "COSMU_PLACEBO_RIDER"

# Cap on how many symbols of the cohort's market the panel is run over, so a 30-perp × multi-venue cohort can't
# make the (bounded) panel run blow up runtime. A deterministic, stable-sorted slice of the SAME already-screened
# bars — never a re-fetch, never new data. The panel still runs its full ~10 placebo specs on this slice.
_MAX_RIDER_SYMBOLS = 6


def placebo_rider_enabled() -> bool:
    """True iff COSMU_PLACEBO_RIDER is set truthy. DEFAULT OFF → ride_cohort() is a no-op (finder byte-identical)."""
    return os.environ.get(_RIDER_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _bounded_market(market: dict[str, list[Bar]]) -> dict[str, list[Bar]]:
    """A deterministic, bounded slice of the cohort's market for the panel: at most _MAX_RIDER_SYMBOLS symbols,
    chosen by a stable sort of the cell keys (so the same cohort always yields the same placebo null). Reuses the
    SAME already-screened bars — never a re-fetch, never new data. Skips empty-bar cells (the panel needs bars)."""
    keys = sorted(k for k, bars in market.items() if bars)
    return {k: market[k] for k in keys[:_MAX_RIDER_SYMBOLS]}


@dataclass(frozen=True)
class RiderOutcome:
    """What the rider observed for one cohort — RETURNED for the caller/tests, never used to change the verdict.
    `panel` is the measured placebo null; `any_cleared` mirrors panel.any_cleared (the caught-leak flag);
    `survivor_comparisons` places each promoted survivor's DSR in the measured null's right tail (optional)."""

    panel: PlaceboPanel
    any_cleared: bool
    survivor_comparisons: dict[str, SurvivorVsNull]


def ride_cohort(
    *,
    market: dict[str, list[Bar]],
    gates: GateSettings,
    family: str,
    venue_id: str = "binance",
    survivor_dsrs: dict[str, float] | None = None,
    store: object | None = None,
    seed: int = 7,
) -> RiderOutcome | None:
    """Ride one finder cohort with the negative-control placebo panel — OBSERVE-ONLY.

    Flag-gated: returns None immediately (a NO-OP) unless COSMU_PLACEBO_RIDER is truthy, so a normal production
    screen is byte-identical and pays zero extra backtests. When enabled, it runs run_placebo_panel on a bounded,
    deterministic slice of the SAME real market the finder just screened (the same tape the cohort's survivors were
    found on), logs PlaceboPanel.render() at INFO, and — if any_cleared is True (a placebo cleared the LOCKED Gate
    = an upstream leak the Gate cannot see) — logs LOUDLY at WARNING and writes a best-effort `placebo_leak` event
    row (when a Store with append_event is supplied). It NEVER raises, blocks, or alters the finder verdict: the
    panel reads the locked gate constants, the finder's promote_brut path is untouched, and any error inside the
    rider is swallowed (the live run must never be put at risk by an observer).

    `survivor_dsrs` (optional) {label -> DSR} for the cohort's promoted survivors → each is placed in the measured
    null's right tail via compare_survivor_to_null (logged + returned), so a survivor's DSR is read against the
    empirically-measured null, not just the assumed gate floor. Returns a RiderOutcome (for tests/callers) or None
    when the flag is OFF / the market is empty / an error was swallowed."""
    if not placebo_rider_enabled():
        return None
    try:
        bounded = _bounded_market(market)
        if not bounded:
            return None
        panel = run_placebo_panel(market=bounded, gates=gates, venue_id=venue_id, seed=seed)
        # OBSERVE-ONLY: always log the measured null (the standing-instrument breadcrumb) at INFO.
        _LOG.info("[placebo-rider] family=%s\n%s", family, panel.render())
        if panel.any_cleared:
            # THE caught-leak path — log LOUDLY (structured WARNING) and persist a best-effort event row. This is an
            # upstream-leak ALARM the Gate structurally cannot see; it is reported, never used to weaken the gate.
            _LOG.warning(
                "[placebo-rider] UPSTREAM LEAK CAUGHT — family=%s: %d placebo cell(s) cleared the LOCKED Gate "
                "(DSR floor=%.4f). The empirical null is miscalibrated → a leak UPSTREAM of the Gate. "
                "Cleared cells: %s",
                family,
                len(panel.cleared_cells),
                panel.gate_dsr_floor,
                [f"{c.spec_name}/{c.symbol} DSR={c.dsr:.4f} trades={c.trades}" for c in panel.cleared_cells],
            )
            _record_leak_event(store, family=family, panel=panel)
        # OPTIONAL: place each promoted survivor's DSR in the measured null's right tail (propose-only signal).
        comparisons: dict[str, SurvivorVsNull] = {}
        for label, dsr in (survivor_dsrs or {}).items():
            cmp = compare_survivor_to_null(dsr, panel)
            comparisons[label] = cmp
            _LOG.info("[placebo-rider] survivor vs null — family=%s label=%s\n%s", family, label, cmp.render())
        return RiderOutcome(panel=panel, any_cleared=panel.any_cleared, survivor_comparisons=comparisons)
    except Exception:  # noqa: BLE001 — an OBSERVER must NEVER put the live finder run at risk; swallow + move on.
        _LOG.exception("[placebo-rider] panel run failed (observe-only; finder verdict unaffected) family=%s", family)
        return None


def _record_leak_event(store: object | None, *, family: str, panel: PlaceboPanel) -> None:
    """Best-effort: write a `placebo_leak` event row (the same events-table audit trail the finder uses for
    track_opened / finder_survivor / holdout_look) when a Store with append_event is supplied. Swallows any error —
    the WARNING log above is the primary alarm; the event row is durable bookkeeping, never the gate."""
    if store is None or not hasattr(store, "append_event"):
        return
    try:
        store.append_event(  # type: ignore[attr-defined]
            actor="master",
            kind="placebo_leak",
            ref_type="strategy",
            ref_id=family,
            payload={
                "family": family,
                "gate_dsr_floor": panel.gate_dsr_floor,
                "n_cleared": len(panel.cleared_cells),
                "n_cells": panel.n_cells,
                "dsr_max": panel.dsr_max,
                "cleared": [
                    {"spec": c.spec_name, "symbol": c.symbol, "dsr": c.dsr, "trades": c.trades}
                    for c in panel.cleared_cells
                ],
            },
        )
    except Exception:  # noqa: BLE001 — audit trail is best-effort; the loud WARNING already fired.
        _LOG.debug("[placebo-rider] placebo_leak event persist failed (best-effort)", exc_info=True)


__all__ = ["RiderOutcome", "placebo_rider_enabled", "ride_cohort"]
