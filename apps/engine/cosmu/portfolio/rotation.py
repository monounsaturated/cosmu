# intent: per-track lifecycle decisions for the standalone paper model — decide which proven tracks stay
# funded and which have decayed (→ defund + close), and attribute net edge back to its data sources; inputs:
# per-track live evidence + per-source attribution; outputs: the set of tracks to keep funded + per-source
# marginal edge; invariants: NO pooled wallet and NO cross-track competition — each survivor proves itself on its
# OWN standalone track, so there is no capital-weighting here; a decayed track is defunded, the rest stay funded.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Track:
    """One strategy version's standalone paper track. It earns or loses on its OWN simulated capital —
    never a share of a pool. `rolling_dsr` is the rolling deflated-Sharpe prob (decays as edge dies);
    `sim_live_divergence` is |sim − live| net edge (large = the backtest was a lie); the drift fields are the
    anticipatory decay signals from master/drift."""

    id: str
    rolling_dsr: float                            # rolling deflated-Sharpe prob — decays as edge dies
    sim_live_divergence: float = 0.0              # |sim − live| net edge; large = the backtest was a lie
    source_attribution: dict[str, float] = field(default_factory=dict)  # drop-one marginal edge per alt-data source
    drift_defund: bool = False                    # ANTICIPATORY: the drift monitor (master/drift) says pull now
    edge_half_life: float | None = None           # estimated periods for the realized edge to halve (None = not decaying)


def is_decayed(track: Track, *, min_dsr: float = 0.90, max_divergence: float = 0.5, min_half_life: float = 4.0) -> bool:
    """A track is decayed (→ defund + close) if its rolling deflated-Sharpe has fallen below the floor, live
    results diverge too far from its sim paper, the anticipatory drift monitor flagged it, OR its estimated
    edge half-life is below the floor (edge dying fast). The last two pull capital BEFORE realized P&L turns —
    crypto edges die in weeks; waiting for the reactive deflated-Sharpe snapshot to cross gives back the gains."""
    return (
        track.rolling_dsr < min_dsr
        or track.sim_live_divergence > max_divergence
        or track.drift_defund
        or (track.edge_half_life is not None and track.edge_half_life < min_half_life)
    )


@dataclass(frozen=True)
class TrackVerdict:
    version_id: str
    funded: bool
    reason: str


def select_tracks(
    tracks: list[Track],
    *,
    max_tracks: int | None = None,
    min_dsr: float = 0.90,
    max_divergence: float = 0.5,
    min_half_life: float = 4.0,
) -> list[TrackVerdict]:
    """Decide which tracks stay funded. There is NO pooled wallet and NO cross-track capital competition: every
    track that has not decayed keeps running on its own standalone capital, and every decayed track is defunded.
    `max_tracks` is an OPTIONAL operational ceiling on how many tracks run concurrently (cost/throughput — never a
    capital-allocation weight); None = no ceiling. Deterministic and seed-free."""
    verdicts: list[TrackVerdict] = []
    live: list[str] = []
    for t in tracks:
        if is_decayed(t, min_dsr=min_dsr, max_divergence=max_divergence, min_half_life=min_half_life):
            anticipatory = t.drift_defund or (t.edge_half_life is not None and t.edge_half_life < min_half_life)
            why = "anticipatory: drift monitor / short edge half-life" if anticipatory else "edge decayed or sim/live divergence"
            verdicts.append(TrackVerdict(t.id, False, f"defunded: {why}"))
            continue
        live.append(t.id)

    kept = live if max_tracks is None else live[:max_tracks]
    over_ceiling = set(live[max_tracks:]) if max_tracks is not None else set()
    for vid in live:
        if vid in over_ceiling:
            verdicts.append(TrackVerdict(vid, False, "above concurrent-track ceiling (operational cap)"))
        else:
            verdicts.append(TrackVerdict(vid, True, "live edge: standalone paper track"))
    _ = kept
    return verdicts


def paying_sources(tracks: list[Track], *, min_marginal: float = 0.0) -> dict[str, float]:
    """Aggregate per-source marginal edge across live tracks (from the drop-one ablation in research/gate.py).
    Sources with total marginal edge <= `min_marginal` are dead weight — cut them from ingestion to save cost."""
    totals: dict[str, float] = {}
    for t in tracks:
        if is_decayed(t):
            continue
        for src, marginal in t.source_attribution.items():
            totals[src] = totals.get(src, 0.0) + marginal
    return {src: round(v, 6) for src, v in totals.items() if v > min_marginal}
