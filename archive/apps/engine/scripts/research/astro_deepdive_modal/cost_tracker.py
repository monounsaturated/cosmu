# intent: the BUDGET WATCHDOG for the astro deep-dive Modal run. Modal bills per container-second; this tracks
# accumulated container-hours × a per-container-hour rate, checkpoints the running spend at named milestones, and
# — the whole point — ALERTS and signals STOP the moment spend crosses 0.8×budget so an operator-launched
# ($35–110) run can never silently overrun. Alerts go to Slack when SLACK_WEBHOOK_URL is set (reusing the
# engine's best-effort SlackNotifier), else they print. Pure bookkeeping: it moves no money, writes no DB,
# fires no order — it only observes container-hours and says "keep going" or "STOP".
#
# This is RESEARCH-ONLY scaffolding for scripts/research/astro_deepdive_modal.py and never touches the gate /
# scheduler / trial-ledger / money path.

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

# Modal 8-CPU / 16 GB container ≈ this per container-hour (matches the PLAN's ~$0.40/container-hr estimate and
# the modal_sweep.py perm_cv resource shape). A KNOB, not a contract — override per the live Modal price sheet.
DEFAULT_CONTAINER_HR_USD = 0.40

# Fraction of the budget at which we ALERT + STOP. The deep-dive PLAN pre-registers a hard stop well under the
# ceiling so the operator-controlled spend can never silently overrun.
STOP_FRACTION = 0.80


def _emit(text: str) -> None:
    """Send `text` to Slack when SLACK_WEBHOOK_URL is set, else print. Best-effort, NEVER raises.

    Reuses the engine's SlackNotifier when the package is importable (the harness puts the engine root on
    sys.path); falls back to a plain print so this module is useful even imported standalone.
    """
    if os.environ.get("SLACK_WEBHOOK_URL"):
        try:
            from cosmu.notify.slack import SlackNotifier  # deferred: engine pkg, may not be on path

            SlackNotifier.from_env().send(text)
            return
        except Exception:  # noqa: BLE001 — never let alerting break the run
            pass
    print(text, flush=True)


@dataclass
class CostTracker:
    """Container-hour budget watchdog for the deep-dive run.

    Usage (the harness calls these at phase boundaries):
        ct = CostTracker(budget_usd=110.0)
        ...launch a Modal phase...
        ct.add_container_hours(n_containers * wall_hours, label="phase1_download")
        if ct.checkpoint("phase1 done").should_stop:
            ...abort remaining phases...

    `add_container_hours` accrues spend; `checkpoint` ALERTS + flips `should_stop` once spend crosses
    STOP_FRACTION×budget. Idempotent on the alert (fires once). Pure observation — no spend, no DB, no orders.
    """

    budget_usd: float = 110.0
    container_hr_usd: float = DEFAULT_CONTAINER_HR_USD
    container_hours: float = 0.0
    should_stop: bool = False
    _started: float = field(default_factory=time.time)
    _alerted: bool = False

    @property
    def spent_usd(self) -> float:
        """Estimated spend so far = accrued container-hours × per-container-hour rate."""
        return self.container_hours * self.container_hr_usd

    @property
    def stop_threshold_usd(self) -> float:
        return STOP_FRACTION * self.budget_usd

    @property
    def fraction(self) -> float:
        return self.spent_usd / self.budget_usd if self.budget_usd > 0 else float("inf")

    def add_container_hours(self, hours: float, *, label: str = "") -> "CostTracker":
        """Accrue container-hours for a completed (or estimated) Modal phase. Returns self (chainable)."""
        self.container_hours += max(0.0, float(hours))
        return self

    def estimate_phase_hours(self, n_containers: int, wall_hours_per_container: float) -> float:
        """Convenience: container-hours for a fan-out of `n_containers`, each running `wall_hours_per_container`."""
        return max(0, int(n_containers)) * max(0.0, float(wall_hours_per_container))

    def checkpoint(self, label: str) -> "CostTracker":
        """Record the running spend at a named milestone; ALERT + set should_stop once over the threshold.

        Always prints a one-line milestone (so the run log shows the cost climb); escalates to a STOP alert
        exactly once when spend first crosses STOP_FRACTION×budget. Returns self so the caller can branch on
        `.should_stop` inline.
        """
        line = (
            f"[cost] {label}: {self.container_hours:.1f} container-hrs "
            f"≈ ${self.spent_usd:.2f} / ${self.budget_usd:.2f} budget "
            f"({self.fraction * 100:.0f}%)"
        )
        print(line, flush=True)
        if self.spent_usd > self.stop_threshold_usd:
            self.should_stop = True
            if not self._alerted:
                self._alerted = True
                _emit(
                    ":rotating_light: *Astro deep-dive budget STOP* — estimated spend "
                    f"${self.spent_usd:.2f} crossed {STOP_FRACTION:.0%} of the "
                    f"${self.budget_usd:.2f} budget at `{label}`. Halting remaining Modal phases."
                )
        return self

    def summary(self) -> dict:
        """A JSON-able snapshot for the run report / R2 aggregate metadata."""
        return dict(
            budget_usd=round(self.budget_usd, 2),
            container_hr_usd=self.container_hr_usd,
            container_hours=round(self.container_hours, 3),
            spent_usd=round(self.spent_usd, 2),
            fraction=round(self.fraction, 4),
            stopped=self.should_stop,
            wall_seconds=round(time.time() - self._started, 1),
        )


if __name__ == "__main__":
    # Self-proof (NO Modal, NO network, NO spend): accrue past the stop line and confirm the STOP latch fires.
    ct = CostTracker(budget_usd=10.0, container_hr_usd=1.0)
    ct.add_container_hours(5, label="phase1").checkpoint("phase1 done")
    print("should_stop after $5/$10:", ct.should_stop, "(expect False)")
    ct.add_container_hours(4, label="phase3").checkpoint("phase3 done")  # $9 > 0.8*$10
    print("should_stop after $9/$10:", ct.should_stop, "(expect True)")
    print("summary:", ct.summary())
