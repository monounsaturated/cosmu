# intent: shared state + helpers for the api routers (store, settings, coercers); inputs: store rows/env; outputs: reused primitives; invariants: a single Store/Settings instance is shared across every router.

from __future__ import annotations

import json
import math
from typing import Any

from cosmu.api.models import CohortSummaryResponse, EvaluatedStrategy
from cosmu.config.settings import get_settings
from cosmu.evolution.loop import CohortSummary
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio

ORIGIN_TO_LANE = {"seed": "seed", "mutation": "exploit", "wildcard": "explore", "pine": "pine", "agent": "exploit"}

_MONTHS_PER_YEAR = 12
_DAYS_PER_MONTH = 30.0  # coarse: the backtest OOS window is stored as YYYY-MM, so day precision isn't available.


def oos_window_days(oos_start: object, oos_end: object) -> float | None:
    """Length of the backtest OOS window in days, derived from its `YYYY-MM` bounds (inclusive of both endpoint
    months). Lets the UI show the OOS return WITH its window ("+8.2% over ~2.4yr") and feeds the divergence
    pro-rating. Returns None when either bound is missing/malformed. Coarse by design (the bounds are monthly).
    Shared by the leaderboard router AND the strategy-detail router (the Backtest contract column)."""
    if oos_start is None or oos_end is None:
        return None
    try:
        sy, sm = (int(p) for p in str(oos_start).split("-")[:2])
        ey, em = (int(p) for p in str(oos_end).split("-")[:2])
    except (ValueError, TypeError):
        return None
    months = (ey - sy) * _MONTHS_PER_YEAR + (em - sm) + 1  # inclusive of both endpoint months
    if months <= 0:
        return None
    return months * _DAYS_PER_MONTH


def annualized_return(total_return: object, window_days: float | None) -> float | None:
    """CAGR — the total OOS return compounded to a YEARLY rate so combos of different window lengths are directly
    comparable (a +6% over 3 months and a +6% over 2 years are NOT the same edge; annualized they read +27%/yr vs
    +3%/yr). `total_return` is a FRACTION (0.08 = +8%); `window_days` from oos_window_days(). Returns a fraction
    (0.034 = +3.4%/yr), or None when the window is unknown/≤0 or the total wiped out (≤ -100%). Uses CALENDAR days
    (365.25/yr) — the right convention for a holding-period return (trading-session counts annualize vol/Sharpe, a
    separate axis). Short windows AMPLIFY (a +50% month → a huge CAGR) — honest, but read alongside the window."""
    if window_days is None or window_days <= 0:
        return None
    try:
        total = float(total_return)
    except (TypeError, ValueError):
        return None
    if total <= -1.0:
        return None
    years = window_days / 365.25
    if years <= 0:
        return None
    return (1.0 + total) ** (1.0 / years) - 1.0


def annualized_return_lo(total_return: object, window_days: float | None, sharpe: object, n_trades: object) -> float | None:
    """A CONSERVATIVE lower-bound on the annualized return — the honest "≥ x%/yr" that turns a point estimate into a
    confidence read so the screener can't present a noisy +400%/yr as fact (and over-allocate to it).

    The cell carries no return-series, only summary stats, so we lean on the textbook Sharpe-ratio standard error
    SE(SR) ≈ sqrt((1 + 0.5·SR²)/n) (Lo 2002, n = the cell's OWN trade count). A LARGE relative noise SE(SR)/|SR|
    means the edge is poorly estimated, so we SHRINK the total return toward 0 by exactly that relative noise
    (clamped to [0,1]) BEFORE annualizing over the SAME window — i.e. lo = annualize(total · max(0, 1 − SE/|SR|)).
    A high-Sharpe / many-trade cell barely shrinks; a 3-trade fluke collapses toward 0%/yr. This is a deliberately
    simple, MONOTONE lower-bound (always ≤ the point CAGR for a positive return), NOT a calibrated CI — display-only,
    never a gate. Returns None (honest "—") when the inputs can't support it: n < 2, |SR| ~ 0 (noise undefined), the
    window is unknown, or the total wiped out. NEVER fabricates a number where the estimate is meaningless."""
    if window_days is None or window_days <= 0:
        return None
    try:
        total = float(total_return)
        sr = float(sharpe)
        n = int(n_trades)
    except (TypeError, ValueError):
        return None
    if total <= -1.0 or n < 2 or abs(sr) < 1e-9:
        return None
    se = math.sqrt((1.0 + 0.5 * sr * sr) / n)
    rel_noise = se / abs(sr)
    shrink = max(0.0, 1.0 - rel_noise)  # 1 = tight estimate (no haircut); 0 = pure noise (collapse to 0%)
    return annualized_return(total * shrink, window_days)


settings = get_settings()
try:
    store = Store(settings)
except Exception:
    from cosmu.config.settings import Settings as _S
    store = Store(_S(database_url="sqlite:///.cosmu/fallback.sqlite3"))


def _metric(value: object, default: float = 0.0) -> float:
    """Coerce a DB numeric into a real, FINITE float for the typed web contract.

    Several response models (e.g. LeaderboardRow) promise non-null `number` for
    every metric, but the source rows come from a LEFT JOIN on `backtests`:
    a Version with no backtest yields NULL, and a degenerate backtest can yield
    NaN/inf. Both break the contract downstream — NULL becomes `undefined` and
    crashes `x.toFixed()` in the web build, NaN/inf serialize as invalid JSON.
    So we collapse anything null/non-numeric/non-finite to a documented 0.0
    sentinel BEFORE serialization. (Plain `x or 0` is NOT enough: `NaN or 0`
    is NaN, since NaN is truthy.)
    """
    try:
        out = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _portfolio() -> Portfolio:
    return Portfolio(store, bankroll=settings.sim_bankroll, daily_loss_cap=settings.live.daily_loss_cap)


def _market_reference_bars(asset_class: str):
    """The CURRENT-regime reference for an ASSET CLASS — the market 'brain' for THAT class: crypto → REAL Binance
    BTCUSDT; equity/ETF → SPY total-return (Alpaca-when-keyed else keyless Yahoo). Offline-safe: no bars → []
    (current_regime then reports a neutral 'chop' default) — NEVER a synthetic series. So an equity strategy's
    regime is judged by the EQUITY market, not BTC."""
    try:
        if asset_class == "equity":
            from cosmu.orchestrator.loop import _default_equity_provider

            bars = _default_equity_provider(settings).fetch_bars("SPY", "1d", limit=240)
        else:
            from cosmu.data.market import BinanceSpotOHLCVProvider

            bars = BinanceSpotOHLCVProvider().fetch_bars("BTCUSDT", "1d", limit=240)
        if len(bars) >= 60:
            return bars
    except Exception:  # noqa: BLE001 — offline/no-network: report neutral, never fabricate a regime
        pass
    return []


def _brain_reference_bars():
    """Back-compat crypto-market brain (BTCUSDT). Prefer _version_reference_bars for per-strategy regime checks
    so a non-crypto strategy is never judged by BTC."""
    return _market_reference_bars("crypto")


def _version_reference_bars(version_id: str):
    """The regime reference for a SPECIFIC version, resolved from its OWN universe/asset class (NOT BTC for all):
    crypto → BTC, equity → SPY. Falls back to the crypto brain when the spec is missing/unparsable."""
    from cosmu.orchestrator.loop import _survivor_asset_class

    row = store.row("SELECT spec FROM strategy_versions WHERE id = ?", (version_id,))
    return _market_reference_bars(_survivor_asset_class(row["spec"]) if row else "crypto")


def ensure_recommendations() -> None:
    if store.row("SELECT id FROM recommendations LIMIT 1"):
        return
    store.insert(
        "recommendations",
        {
            "ts": utcnow(),
            "kind": "paper_promotion_watch",
            "body": "One seeded strategy cleared the deterministic WFO gates. Keep it in realistic sim until it survives 4+ weeks with positive net edge before live promotion.",
            "state": "open",
            "payload": {"requires": ["4w_paper_survival", "regime_match", "caps_available"]},
        },
    )


def _summary_to_response(summary: CohortSummary) -> CohortSummaryResponse:
    def rows(items: list) -> list[EvaluatedStrategy]:
        return [
            EvaluatedStrategy(
                version_id=e.version_id,
                name=e.name,
                origin=e.origin,
                lane=e.lane,
                deflated_sharpe=round(e.deflated_sharpe, 4),
                oos_return_pct=round(e.oos_return_pct, 3),
                passed=e.passed,
                reasons=e.reasons,
            )
            for e in items
        ]

    return CohortSummaryResponse(
        cohort_id=summary.cohort_id,
        seed=summary.seed,
        generated=summary.generated,
        invalid=summary.invalid,
        killed=summary.killed,
        passed=summary.passed,
        kill_rate=summary.kill_rate,
        lanes=summary.lanes,
        pine_imported=summary.pine_imported,
        survivors=rows(summary.survivors),
        graveyard=rows(summary.graveyard),
        pine_notes=summary.pine_notes,
        duplicates=summary.duplicates,
    )
