# intent: DERIVE an arm's proven-regime passport from its OWN per-regime PnL instead of hardcoding the full
# set ['bull','bear','chop']. The hardcode neutralized master/live_eligibility's regime gate — an arm claimed
# it works in EVERY trend regime for free, so a strategy that loses money in bear months could still clear the
# live-eligibility gate during a bear market. This module closes that hole by EARNING each regime: it classifies
# every INVESTED period's trend with the SAME deterministic classifier the screen folds + the live gate use
# (cosmu.data.backtest._regime_labels, via cosmu.ml.regime), buckets the arm's realized net returns into per-regime
# compounded PnL, and returns ONLY the regimes with strictly positive net PnL (cosmu.ml.regime.proven_regimes).
#
# This is a TIGHTENING (a strategy can now only go live in a regime it was actually profitable in); it loosens
# nothing and touches no Gate threshold. Point-in-time honest: the trend label for period i reads only the
# benchmark series up to i (the same look-back-only contract _regime_labels guarantees).
#
# Two reference-series modes, both reusing _regime_labels verbatim (no new classifier):
#   - BENCHMARK-relative (the TAA equity arms): the arm exposes a per-period benchmark return stream (SPY/AGG
#     total return over the SAME invested months). We rebuild the benchmark's cumulative close path and label each
#     invested month's trend off THAT — so "bull/bear/chop" means the equity-market regime the arm earned its
#     return in, exactly the axis the live gate later re-derives from live SPY closes.
#   - SELF-relative fallback (a market-neutral / cash-benchmark book like the perp L/S arm): there is no market
#     benchmark to define a trend, so the reference IS the strategy's own cumulative net-return path. A dollar-
#     neutral book has no market beta, so its "regime" is its own equity trend; bucketing its net PnL by that
#     still enforces "earn the regime, don't assume it".

from __future__ import annotations

from collections.abc import Sequence

from cosmu.data.backtest import _regime_labels
from cosmu.ml.regime import proven_regimes

# Trend look-back in PERIODS (months for the monthly TAA arms / rebalances for the perp arm). The screen's daily
# classifier defaults to 30 *bars*; at monthly cadence that would need 30 months of warm-up before the first label
# is anything but "chop". 6 periods is the documented monthly trend window these TAA strategies are built around
# (the 6m leg of the 13612W score), so it folds the same trend vocabulary at the right cadence — not a knob tuned
# to pass any single arm. The band is the screen's own ±5% default (cosmu.data.backtest._regime_labels), reused.
_PERIOD_LOOKBACK = 6


def _cumulative_closes(returns: Sequence[float], *, base: float = 100.0) -> list[float]:
    """Rebuild a cumulative close path from a per-period return stream so _regime_labels (which reads CLOSES) can
    label its trend. close[0] = base; close[i] = close[i-1] * (1 + r[i]). Deterministic, no look-ahead."""
    closes = [base]
    for r in returns:
        closes.append(closes[-1] * (1.0 + float(r)))
    return closes


def derive_proven_regimes(
    net_returns: Sequence[float],
    benchmark_returns: Sequence[float] | None = None,
    *,
    lookback: int = _PERIOD_LOOKBACK,
) -> list[str]:
    """The arm's EARNED proven-regime passport (sorted) from its own per-regime PnL.

    `net_returns`        — the arm's realized per-period NET-of-fee return stream (e.g. DaaResult.net_returns,
                           StratResult.net). One entry per INVESTED period.
    `benchmark_returns`  — the per-period benchmark return stream over the SAME periods (SPY/AGG total return for
                           the TAA equity arms). When None/empty (a market-neutral / cash-benchmark book) the
                           reference is the strategy's OWN cumulative net path (self-relative fallback).

    Each invested period is tagged bull/bear/chop by running _regime_labels on the reference's cumulative close
    path; the arm's net return for that period is bucketed (COMPOUNDED) into its regime; a regime is PROVEN iff its
    compounded net PnL is strictly positive (cosmu.ml.regime.proven_regimes). An arm with NEGATIVE bear-month PnL
    therefore DROPS 'bear' from its passport — it must earn each regime, never assume the full set."""
    rets = [float(r) for r in net_returns]
    if not rets:
        return []
    # Reference series for the trend axis: the benchmark (market-relative) when present, else self (cash-benchmark).
    ref = [float(b) for b in benchmark_returns] if benchmark_returns else rets
    # Guard: a benchmark stream MUST be aligned period-for-period with the arm's returns; if it isn't (a malformed
    # caller), fail closed to self-relative rather than mislabel — never fabricate or pad to force alignment.
    if len(ref) != len(rets):
        ref = rets
    closes = _cumulative_closes(ref)  # len = len(ref) + 1; closes[i+1] is the close AT the end of invested period i
    lb = min(lookback, max(2, len(ref) - 1))
    labels = _regime_labels(closes, lookback=lb)  # labels[j] tags close[j]; closes[1:] are the invested periods
    period_labels = labels[1:]  # align to the invested periods (one label per net return)

    # Bucket each period's net return into its trend regime, COMPOUNDED (so a regime is proven by its realized
    # cumulative edge, not by an arithmetic-mean artifact). Start each touched bucket at 1.0 and subtract at the end.
    growth: dict[str, float] = {}
    for label, r in zip(period_labels, rets, strict=False):
        growth[label] = growth.get(label, 1.0) * (1.0 + r)
    regime_returns = {label: g - 1.0 for label, g in growth.items()}
    return sorted(proven_regimes(regime_returns))


def proven_regimes_from_validation(v: dict) -> list[str]:
    """Derive the proven-regime passport straight from an arm's `validate()` verdict dict. Pulls the realized net
    return stream and (when present) the per-period benchmark stream off `v["result"]`, tolerating the field-name
    variation across the research modules:
        net stream:       result.net_returns   (TAA equity arms)  | result.net   (the perp L/S book)
        benchmark stream: result.spy_returns   |  result.bench_returns  |  none (cash-benchmark -> self-relative)
    Returns [] (NO proven regime -> fails the live-eligibility gate safely) when no result/return stream is present,
    so a malformed verdict can never silently grant the full passport."""
    result = v.get("result")
    if result is None:
        return []
    net = getattr(result, "net_returns", None)
    if net is None:
        net = getattr(result, "net", None)
    if not net:
        return []
    bench = getattr(result, "spy_returns", None)
    if bench is None:
        bench = getattr(result, "bench_returns", None)
    return derive_proven_regimes(net, bench)
