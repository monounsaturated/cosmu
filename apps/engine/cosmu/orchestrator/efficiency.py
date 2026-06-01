# intent: the capability-per-dollar meter (Amodei lens) — make efficiency visible so the loop optimizes it;
# inputs: spend + work counts per cycle; outputs: $/accepted-candidate, $/backtest, tokens/candidate; invariants:
# pure accounting, monotonic counters, no side effects — the number the thesis says compounds.

from __future__ import annotations

from dataclasses import dataclass

_INF = float("inf")


@dataclass
class EfficiencyMeter:
    """Running capability-per-dollar accounting across cycles. `spend_usd` is LLM+GPU+data $ actually burned;
    `accepted` is gate-promoted candidates; the ratios are what we minimize/track over time."""

    spend_usd: float = 0.0
    accepted: int = 0
    candidates: int = 0
    backtests: int = 0
    tokens: int = 0

    def record(self, *, spend_usd: float = 0.0, accepted: int = 0, candidates: int = 0,
               backtests: int = 0, tokens: int = 0) -> None:
        self.spend_usd += spend_usd
        self.accepted += accepted
        self.candidates += candidates
        self.backtests += backtests
        self.tokens += tokens

    @property
    def cost_per_accepted(self) -> float:
        return self.spend_usd / self.accepted if self.accepted else _INF

    @property
    def cost_per_backtest(self) -> float:
        return self.spend_usd / self.backtests if self.backtests else _INF

    @property
    def tokens_per_candidate(self) -> float:
        return self.tokens / self.candidates if self.candidates else _INF

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.candidates if self.candidates else 0.0

    def snapshot(self) -> dict[str, float]:
        return {
            "spend_usd": round(self.spend_usd, 4),
            "accepted": self.accepted,
            "candidates": self.candidates,
            "cost_per_accepted": self.cost_per_accepted,
            "tokens_per_candidate": self.tokens_per_candidate,
            "acceptance_rate": round(self.acceptance_rate, 4),
        }
