# intent: deterministic market-regime classifier — realized-vol tercile x trend sign on a reference close
# series, reusing data/backtest._regime_labels for the trend axis so the screen folds and live gate share one
# vocabulary. This is the interface the ML refines later; today it is fully deterministic, point-in-time
# (only past closes are read at any index), and dependency-free. It (a) labels folds for the survival model
# and (b) gates live-eligibility: a strategy may go live ONLY in a regime it proved itself in. invariants:
# no look-ahead (current_regime reads closes[:now] only), no magic-number tuning beyond the documented
# tercile/trend split, and the scorer/gate are never reached from here.

from __future__ import annotations

import statistics
from dataclasses import dataclass

from cosmu.data.backtest import _regime_labels

# Realized-vol terciles are computed from the reference series' own history, so "high vol" is relative to the
# asset, not an absolute magic threshold. The trend axis reuses the screen's band classifier verbatim.
_VOL_BUCKETS = ("low", "mid", "high")


@dataclass(frozen=True)
class Regime:
    """A point-in-time regime tag. `label` is the composite (trend) used to gate live-eligibility; `vol_bucket`
    and `trend` are the two axes the ML model later refines. `label` mirrors data/backtest's trend vocabulary
    ("bull"/"bear"/"chop") so screen folds and the live gate speak the same language."""

    label: str
    vol_bucket: str
    trend: str

    def as_dict(self) -> dict[str, str]:
        return {"label": self.label, "vol_bucket": self.vol_bucket, "trend": self.trend}


def _realized_vol(closes: list[float], lookback: int) -> float:
    if len(closes) < 3:
        return 0.0
    window = closes[-(lookback + 1) :]
    rets = [window[i] / window[i - 1] - 1.0 for i in range(1, len(window)) if window[i - 1]]
    return statistics.pstdev(rets) if len(rets) > 1 else 0.0


def _vol_bucket(closes: list[float], lookback: int) -> str:
    """Classify the trailing realized vol into a low/mid/high tercile against the asset's own rolling-vol
    history — relative, so no absolute magic threshold. Point-in-time: only closes up to now are read."""
    if len(closes) < lookback * 3:
        # Not enough history to estimate terciles honestly — call it mid rather than fabricate a split.
        return "mid"
    history: list[float] = []
    for end in range(lookback + 1, len(closes) + 1):
        history.append(_realized_vol(closes[:end], lookback))
    history = [v for v in history if v > 0]
    if len(history) < 3:
        return "mid"
    ordered = sorted(history)
    lo = ordered[len(ordered) // 3]
    hi = ordered[2 * len(ordered) // 3]
    now = _realized_vol(closes, lookback)
    if now <= lo:
        return "low"
    if now >= hi:
        return "high"
    return "mid"


def current_regime(bars, *, lookback: int = 30) -> Regime:
    """The current regime from a reference close series (a list of Bar or floats). Reads only bars up to now —
    no look-ahead. Trend reuses data/backtest._regime_labels (the exact classifier the screen folds use); the
    vol axis is a tercile of the asset's own realized-vol history."""
    closes = _closes(bars)
    if len(closes) < 2:
        return Regime(label="chop", vol_bucket="mid", trend="chop")
    trend = _regime_labels(closes, lookback=min(lookback, max(2, len(closes) - 1)))[-1]
    vol = _vol_bucket(closes, min(lookback, max(2, len(closes) // 3)))
    return Regime(label=trend, vol_bucket=vol, trend=trend)


def proven_regimes(regime_returns: dict[str, float]) -> set[str]:
    """The set of trend regimes a strategy demonstrated positive net edge in (from the screen's regime-tagged
    PnL, BacktestMetrics.regime_returns). This is the strategy's live-eligibility passport: it may only trade
    live in a regime it has actually proved in — never a regime it has never been profitable in."""
    return {regime for regime, pnl in regime_returns.items() if pnl > 0}


def regime_eligible(now: Regime, proven: set[str]) -> bool:
    """Live-eligibility gate: True only if the CURRENT regime is one the strategy proved in. An empty proven
    set (never profitable in any regime) is never eligible. This NEVER promotes — it only blocks — so a thin
    proven set fails safe (out-of-regime = blocked)."""
    if not proven:
        return False
    return now.label in proven


def _closes(bars) -> list[float]:
    out: list[float] = []
    for bar in bars:
        if hasattr(bar, "close"):
            out.append(float(bar.close))
        else:
            out.append(float(bar))
    return out
