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


def _brain_reference_bars():
    """A reference close series for the CURRENT-regime read — REAL Binance BTCUSDT only. If the cache/network is
    unavailable we return no bars (current_regime then reports a neutral 'chop' default) rather than reading a
    synthetic fixture: the displayed regime must never be derived from fabricated data."""
    from cosmu.data.market import BinanceSpotOHLCVProvider

    try:
        bars = BinanceSpotOHLCVProvider().fetch_bars("BTCUSDT", "1d", limit=240)
        if len(bars) >= 60:
            return bars
    except Exception:  # noqa: BLE001 — offline/no-network: report neutral, never fabricate a regime
        pass
    return []


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
    )
