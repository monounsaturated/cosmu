# intent: the compounding engine — rotate capital toward live-edge survivors, defund decayed ones, size with
# capped fractional-Kelly, concentrate at small AUM; inputs: per-sleeve live evidence + per-source attribution;
# outputs: allocation weights in [0,1] summing to <= 1 (rest is cash); invariants: decayed sleeves get exactly 0,
# sizing is memoryless, and capital follows what actually pays net-of-cost (not raw backtest Sharpe).

from __future__ import annotations

from dataclasses import dataclass, field


def kelly_fraction(edge: float, variance: float, *, cap: float = 0.25) -> float:
    """Fractional Kelly, capped. `edge` = expected net-of-cost return per period, `variance` = its variance.
    Full Kelly = edge/variance; we cap hard (default quarter-Kelly) because Kelly is brutal under estimation
    error — the cap is the difference between compounding and blowing up."""
    if variance <= 0 or edge <= 0:
        return 0.0
    return min(edge / variance, cap)


@dataclass(frozen=True)
class Sleeve:
    id: str
    edge: float                                   # recent net-of-cost return per period (the money signal)
    variance: float
    rolling_dsr: float                            # rolling deflated-Sharpe prob — decays as edge dies
    paper_live_divergence: float = 0.0            # |paper - live| net edge; large = the backtest was a lie
    source_attribution: dict[str, float] = field(default_factory=dict)  # drop-one marginal edge per alt-data source


def is_decayed(sleeve: Sleeve, *, min_dsr: float = 0.90, max_divergence: float = 0.5) -> bool:
    """A sleeve is decayed (→ defund) if its rolling deflated-Sharpe has fallen below the floor OR live results
    diverge too far from paper. Either is grounds to pull capital fast — crypto edges die in weeks."""
    return sleeve.rolling_dsr < min_dsr or sleeve.paper_live_divergence > max_divergence


@dataclass(frozen=True)
class Allocation:
    sleeve_id: str
    weight: float
    reason: str


def rotate(
    sleeves: list[Sleeve],
    *,
    max_positions: int = 3,
    kelly_cap: float = 0.25,
    min_dsr: float = 0.90,
    max_divergence: float = 0.5,
) -> list[Allocation]:
    """Rotate capital toward live edge: defund decayed sleeves, capped-Kelly-size the rest, concentrate on the
    top `max_positions` (concentration compounds faster than a sprawl of marginal bets at small AUM), and
    normalize so weights sum to <= 1 (leftover stays in cash). Deterministic and seed-free."""
    allocations: list[Allocation] = []
    live: list[tuple[Sleeve, float]] = []
    for s in sleeves:
        if is_decayed(s, min_dsr=min_dsr, max_divergence=max_divergence):
            allocations.append(Allocation(s.id, 0.0, "defunded: edge decayed or live/paper divergence"))
            continue
        k = kelly_fraction(s.edge, s.variance, cap=kelly_cap)
        if k <= 0:
            allocations.append(Allocation(s.id, 0.0, "no positive net edge"))
            continue
        live.append((s, k))

    # concentrate: keep the top-N by Kelly score, defund the marginal tail
    live.sort(key=lambda pair: pair[1], reverse=True)
    kept = live[:max_positions]
    for s, _ in live[max_positions:]:
        allocations.append(Allocation(s.id, 0.0, "below concentration cut (top-N only)"))

    total = sum(k for _, k in kept)
    if total > 1.0:  # scale down to fully-invested; otherwise keep raw Kelly and leave the rest in cash
        kept = [(s, k / total) for s, k in kept]
    for s, w in kept:
        allocations.append(Allocation(s.id, round(w, 6), "live edge: capped-Kelly, concentrated"))
    return allocations


def paying_sources(sleeves: list[Sleeve], *, min_marginal: float = 0.0) -> dict[str, float]:
    """Aggregate per-source marginal edge across live sleeves (from the drop-one ablation in research/gate.py).
    Sources with total marginal edge <= `min_marginal` are dead weight — cut them from ingestion to save cost."""
    totals: dict[str, float] = {}
    for s in sleeves:
        if is_decayed(s):
            continue
        for src, marginal in s.source_attribution.items():
            totals[src] = totals.get(src, 0.0) + marginal
    return {src: round(v, 6) for src, v in totals.items() if v > min_marginal}
