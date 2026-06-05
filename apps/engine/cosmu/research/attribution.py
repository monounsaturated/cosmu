# intent: SIM→LIVE VARIANCE ATTRIBUTION — decompose the divergence between a track's sim forward-test and its
# realized live results into named, signed buckets (fees · slippage · funding · signal-decay · regime) plus an
# honest residual, so "the backtest was a lie" becomes "the backtest was a lie BECAUSE …". inputs: a sim reference
# edge + a realized live edge + the per-leg sim/live cost basis + the regime mix + the live return series (for the
# alpha-decay estimate, reusing master/drift); outputs: a deterministic VarianceAttribution (components that sum to
# the explained divergence + the residual). invariants: PURE + offline + deterministic + seed-free, REVIEW-ONLY —
# this only EXPLAINS divergence, it never funds, defunds, sizes, or moves money (out of any LLM path AND out of the
# money path; the deterministic lifecycle + live toggle alone dispose). All quantities are per-period (cost legs:
# per-trade) MEAN fractional returns/drags, so every component is in the same unit as the divergence it explains.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cosmu.master.drift import fit_edge_decay, rolling_edge


@dataclass(frozen=True)
class CostLeg:
    """One cost/cash-flow leg's sim-modeled vs live-realized magnitude, in per-trade fractional units. For fees
    and slippage these are drags (>= 0); for funding it is a signed cash-flow (+ received, − paid)."""

    sim: float
    live: float


@dataclass(frozen=True)
class RegimeBucket:
    """How a regime was weighted and how it paid, sim vs live — the inputs to the regime allocation effect.
    `sim_gross` is the sim mean per-period GROSS return in this regime (the neutral expectation)."""

    label: str
    sim_weight: float   # fraction of sim periods spent in this regime
    live_weight: float  # fraction of live periods spent in this regime
    sim_gross: float    # sim mean per-period gross return for this regime


@dataclass(frozen=True)
class VarianceComponent:
    name: str           # "fees" | "slippage" | "funding" | "signal_decay" | "regime"
    contribution: float # signed: + pushed live ABOVE sim, − dragged live BELOW sim
    note: str


@dataclass(frozen=True)
class VarianceAttribution:
    """The full decomposition of (live − sim) per-period mean net return into named buckets + a residual. The
    residual is first-class and reported honestly: components are independent best-estimates, so what they do not
    explain is named, not hidden."""

    ref_id: str
    sim_reference: str  # "funded-baseline" | "backtest" — what the sim edge was measured against (honest units)
    sim_net: float
    live_net: float
    divergence: float   # live_net − sim_net
    components: tuple[VarianceComponent, ...]
    explained: float    # Σ component contributions
    residual: float     # divergence − explained (unattributed: model/notional mismatch, regimes not supplied, …)
    n_live: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "sim_reference": self.sim_reference,
            "sim_net": self.sim_net,
            "live_net": self.live_net,
            "divergence": self.divergence,
            "explained": self.explained,
            "residual": self.residual,
            "n_live": self.n_live,
            "components": [
                {"name": c.name, "contribution": c.contribution, "note": c.note} for c in self.components
            ],
        }

    def headline(self) -> str:
        verdict = "live ABOVE sim" if self.divergence >= 0 else "live BELOW sim"
        ranked = sorted(self.components, key=lambda c: abs(c.contribution), reverse=True)
        drivers = ", ".join(f"{c.name} {c.contribution:+.4%}" for c in ranked[:3]) or "none"
        return (
            f"{self.ref_id}: {verdict} by {self.divergence:+.4%}/period "
            f"(explained {self.explained:+.4%}, residual {self.residual:+.4%}); "
            f"top drivers: {drivers}"
        )


# --- pure analytics (no I/O, deterministic) --------------------------------------------------------


def decay_contribution(
    live_returns: list[float], sim_reference: float, *, baseline_n: int = 5, window: int = 5
) -> tuple[float, str]:
    """Estimate the signal-decay (alpha-decay) contribution to the divergence: how far the track's CURRENT fitted
    rolling edge has fallen below the sim reference it was funded on. Reuses master/drift's edge-decay primitive so
    sim/live divergence and the anticipatory defund monitor read the same erosion. A non-decaying (flat/rising)
    edge contributes ~0. Signed: negative = the edge eroded since funding (the usual live shortfall)."""
    if len(live_returns) < 3:
        return 0.0, "insufficient live history for a decay estimate"
    decay = fit_edge_decay(rolling_edge(live_returns, window=window))
    contribution = decay.current_edge - sim_reference
    if decay.half_life is not None:
        note = f"current edge {decay.current_edge:+.4%} vs reference {sim_reference:+.4%} (half-life {decay.half_life:.1f} periods)"
    else:
        note = f"current edge {decay.current_edge:+.4%} vs reference {sim_reference:+.4%} (no finite decay)"
    return contribution, note


def regime_contribution(buckets: list[RegimeBucket]) -> tuple[float, str]:
    """The regime allocation effect (Brinson): Σ (live_weight − sim_weight) · sim_gross. It isolates the part of
    the divergence caused by live TRADING IN A DIFFERENT REGIME MIX than the backtest — not by the edge itself
    eroding. Positive = live happened to spend more time in regimes the backtest paid well in; negative = live got
    dealt a worse regime mix than the backtest. Empty buckets → 0 (the effect folds into the residual, honestly)."""
    if not buckets:
        return 0.0, "no regime mix supplied — regime effect folded into residual"
    effect = sum((b.live_weight - b.sim_weight) * b.sim_gross for b in buckets)
    shifted = sorted(buckets, key=lambda b: abs(b.live_weight - b.sim_weight), reverse=True)
    top = shifted[0]
    note = f"regime-mix shift led by '{top.label}' ({(top.live_weight - top.sim_weight):+.0%} weight)"
    return effect, note


def attribute_variance(
    ref_id: str,
    *,
    sim_net: float,
    live_net: float,
    fees: CostLeg = CostLeg(0.0, 0.0),
    slippage: CostLeg = CostLeg(0.0, 0.0),
    funding: CostLeg = CostLeg(0.0, 0.0),
    signal_decay: float = 0.0,
    signal_decay_note: str = "",
    regime: float = 0.0,
    regime_note: str = "",
    n_live: int = 0,
    sim_reference: str = "funded-baseline",
) -> VarianceAttribution:
    """Decompose (live_net − sim_net) into signed buckets + a residual. Sign convention: every component is the
    contribution TO the divergence (live − sim), so a cost that is HIGHER live than sim drags the divergence
    negative. fees/slippage are drags (sim − live: paying more live → negative); funding is a signed cash-flow
    (live − sim). signal_decay and regime are passed in signed (see the helpers). The residual = divergence minus
    the explained sum; it is reported, never absorbed silently — components are independent best-estimates."""
    fee_contrib = fees.sim - fees.live
    slip_contrib = slippage.sim - slippage.live
    fund_contrib = funding.live - funding.sim
    components = (
        VarianceComponent("fees", fee_contrib, f"sim {fees.sim:.4%} → live {fees.live:.4%} per trade"),
        VarianceComponent("slippage", slip_contrib, f"sim {slippage.sim:.4%} → live {slippage.live:.4%} per trade"),
        VarianceComponent("funding", fund_contrib, f"sim {funding.sim:+.4%} → live {funding.live:+.4%} per trade"),
        VarianceComponent("signal_decay", signal_decay, signal_decay_note or "alpha-decay vs funded reference"),
        VarianceComponent("regime", regime, regime_note or "regime-mix allocation effect"),
    )
    explained = sum(c.contribution for c in components)
    divergence = live_net - sim_net
    residual = divergence - explained
    return VarianceAttribution(
        ref_id=ref_id,
        sim_reference=sim_reference,
        sim_net=sim_net,
        live_net=live_net,
        divergence=divergence,
        components=components,
        explained=explained,
        residual=residual,
        n_live=n_live,
    )


# --- store reader (read-only; assembles the legs from real rows, honest about its proxies) ---------


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _exec_cost_rates(store: Any, version_id: str, *, is_paper: int) -> tuple[float, float]:
    """Mean per-trade (fee_rate, slippage) over this version's fills on one side of the sim/live line. fee_rate is
    fee / notional (a fraction, directly comparable as a return drag); slippage is already stored as a fraction."""
    rows = store.rows(
        "SELECT fee, qty, price, slippage FROM executions WHERE strategy_version_id = ? AND is_paper = ?",
        (version_id, is_paper),
    )
    fee_rates: list[float] = []
    slips: list[float] = []
    for r in rows:
        notional = abs(float(r["qty"])) * abs(float(r["price"]))
        if notional > 0:
            fee_rates.append(float(r["fee"]) / notional)
        slips.append(abs(float(r["slippage"])))
    return _mean(fee_rates), _mean(slips)


def attribute_track(
    store: Any,
    version_id: str,
    *,
    sim_edge: float | None = None,
    regimes: list[RegimeBucket] | None = None,
    baseline_n: int = 5,
    window: int = 5,
) -> VarianceAttribution:
    """Assemble a best-effort attribution for a funded track from real persisted rows. Live edge = mean of the
    track's per-period marked returns (portfolio_snapshots, via master/drift's reader). The sim reference is an
    explicit per-period backtest edge if supplied, else the track's own funded baseline (mean of its earliest
    returns — the realized embodiment of what funding promised). Cost legs are mean per-trade fee_rate/slippage on
    each side of the is_paper line (sim fills vs live fills) from the executions ledger. Funding defaults to a spot
    no-op (0,0); regimes default to none → that effect is named in the residual. Read-only + deterministic; this
    EXPLAINS, it never disposes."""
    from cosmu.master.drift import track_return_series

    live_returns = track_return_series(store, version_id)
    live_net = _mean(live_returns)

    if sim_edge is not None:
        sim_net, sim_reference = float(sim_edge), "backtest"
    else:
        head = live_returns[: max(1, min(baseline_n, len(live_returns) // 2))] if live_returns else []
        sim_net, sim_reference = _mean(head), "funded-baseline"

    sim_fee, sim_slip = _exec_cost_rates(store, version_id, is_paper=1)
    live_fee, live_slip = _exec_cost_rates(store, version_id, is_paper=0)

    decay, decay_note = decay_contribution(live_returns, sim_net, baseline_n=baseline_n, window=window)
    reg, reg_note = regime_contribution(regimes or [])

    return attribute_variance(
        version_id,
        sim_net=sim_net,
        live_net=live_net,
        fees=CostLeg(sim_fee, live_fee),
        slippage=CostLeg(sim_slip, live_slip),
        funding=CostLeg(0.0, 0.0),
        signal_decay=decay,
        signal_decay_note=decay_note,
        regime=reg,
        regime_note=reg_note,
        n_live=len(live_returns),
        sim_reference=sim_reference,
    )


# --- CLI (review-only diagnostic; prints the decomposition, moves nothing) -------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    parser = argparse.ArgumentParser(
        description="SIM→live variance attribution: decompose a funded track's sim/live divergence into "
        "fees · slippage · funding · signal-decay · regime (+ residual). Review-only; moves no money."
    )
    parser.add_argument("version_id", help="strategy_version_id of the funded track to attribute")
    parser.add_argument("--sim-edge", type=float, default=None, help="explicit per-period backtest edge (else the funded baseline is used)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    store = Store(Settings())
    attr = attribute_track(store, args.version_id, sim_edge=args.sim_edge)
    if args.json:
        print(json.dumps(attr.to_dict(), indent=2))
    else:
        print(attr.headline())
        for c in attr.components:
            print(f"  {c.name:<14}{c.contribution:+.4%}   {c.note}")
        print(f"  {'residual':<14}{attr.residual:+.4%}   unattributed (proxies / regimes not supplied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
