# intent: the second Pine-import mode — turn a Pine *indicator* (one whose OUTPUT IS the signal, e.g. a 0-100
# classifier score, not entry/exit rules) into a clean, point-in-time COMPUTED DATA SOURCE: a per-bar numeric
# series we can read the latest value of, persist as point-in-time AltDataPoints, and CROSS-ANALYZE / correlate
# against forward returns. strategy/pine.py flattens any script to a 4-condition StrategySpec for the Gate; that
# is lossy for indicators whose number is the whole point (it collapses them to `ret_Nd > 0`). This module is
# the honest alternative: the indicator becomes a feature whose predictive content we MEASURE before trusting.
# inputs: list[Bar] + params; outputs: IndicatorResult (named float|None series) + CorrelationReport;
# invariants: causal (value at bar i uses only bars <= i), deterministic, offline (no network/clock/LLM).

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar


@dataclass(frozen=True)
class IndicatorResult:
    """A Pine-indicator port's output: named, bar-aligned numeric series (None = warm-up / not-yet-computable).
    `primary` names the headline series — the "number" you read (e.g. the KNN confidence)."""

    series: dict[str, list[float | None]]
    primary: str
    asof_semantics: str = "bar close time (causal — value at bar i uses only bars <= i; non-repainting)"

    def latest(self, name: str | None = None) -> float | None:
        """The most recent non-None value of a series — the number you would act on right now."""
        for value in reversed(self.series.get(name or self.primary, [])):
            if value is not None:
                return value
        return None

    def as_altdata(self, bars: list[Bar], name: str | None = None) -> list[AltDataPoint]:
        """Convert one series into point-in-time AltDataPoints so it can be joined like any alt feature
        (available_at == bar close: an indicator computed on the confirmed bar is known at that bar's close).
        This is the seam by which a *validated* indicator becomes a backtest/Gate feature."""
        key = name or self.primary
        values = self.series.get(key, [])
        return [
            AltDataPoint(ts=bar.ts, available_at=bar.ts, value=float(value))
            for bar, value in zip(bars, values)
            if value is not None
        ]


@runtime_checkable
class PineIndicator(Protocol):
    """The contract every ported Pine indicator implements — the pattern for all future indicator imports."""

    name: str

    def compute(self, bars: list[Bar], **params: float) -> IndicatorResult: ...


# ---------------------------------------------------------------- cross-analysis / correlation


@dataclass(frozen=True)
class CorrelationReport:
    """Does the indicator's number actually relate to what happens next? Pearson (linear), Spearman (monotone),
    and a top-quartile lift (mean target when the signal is in its top 25% vs the overall mean). All computed on
    the causally-aligned overlap; never a money decision — a research read on whether the signal earns a place."""

    n: int
    pearson: float | None
    spearman: float | None
    top_quartile_lift: float | None
    note: str = ""


def forward_return(bars: list[Bar], horizon: int) -> list[float | None]:
    """SIGNED forward return over the next `horizon` bars, placed at the bar it is measured FROM. This is a
    LABEL for analysis only (it looks ahead by construction) — never feed it back in as a feature."""
    closes = [float(bar.close) for bar in bars]
    out: list[float | None] = [None] * len(bars)
    for i in range(len(bars) - horizon):
        base = closes[i]
        if base:
            out[i] = closes[i + horizon] / base - 1.0
    return out


def forward_abs_return(bars: list[Bar], horizon: int) -> list[float | None]:
    """ABSOLUTE forward return — the magnitude of the next-`horizon`-bar move. The natural target for a
    classifier that predicts 'a big move is coming' regardless of direction (which is what ML LZC's label is)."""
    return [None if r is None else abs(r) for r in forward_return(bars, horizon)]


def correlate(signal: list[float | None], target: list[float | None]) -> CorrelationReport:
    """Correlate a bar-aligned signal with a bar-aligned target over the indices where BOTH are present."""
    pairs = [(s, t) for s, t in zip(signal, target) if s is not None and t is not None]
    if len(pairs) < 8:
        return CorrelationReport(len(pairs), None, None, None, "insufficient overlap (<8 paired points)")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    pearson = _pearson(xs, ys)
    spearman = _pearson(_ranks(xs), _ranks(ys))
    thr = _quantile(xs, 0.75)
    top = [t for s, t in pairs if s >= thr]
    overall = statistics.fmean(ys)
    lift = (statistics.fmean(top) / overall - 1.0) if top and overall else None
    return CorrelationReport(len(pairs), pearson, spearman, lift)


# ---------------------------------------------------------------- stats helpers


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 2:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((a[k] - ma) * (b[k] - mb) for k in range(n))
    return cov / math.sqrt(va * vb)


def _ranks(values: list[float]) -> list[float]:
    """Average (tie-corrected) ranks, for Spearman."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]
