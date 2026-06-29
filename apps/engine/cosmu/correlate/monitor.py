# intent: a KEYLESS Polymarket event monitor — it polls the public Gamma API for the watchlist event-TYPES
# (correlation_map.DEFAULT_WATCHLIST), reads each matching market's current YES probability, PIT-stamps it, and
# FORWARD-HOARDS it append-only into the alt-data store (the same `append_dedup` primitive the per-market odds
# ingest uses), then reads a signed probability MOVE off the hoarded series via the dates util. This is the
# "attention signal" feed for the LLM/Conviction lane: a probability that jumps (30¢ yesterday → 40¢ today) on a
# watched event-type is the catalyst the correlation-conviction template proposes a trade on.
#
# WHY forward-hoard (not backfill): a LIVE snapshot is knowable NOW (available_at == ts == poll time), so each
# poll banks one honest point we could not have reconstructed historically — the classic forward-hoard pattern
# (mirrors scripts/ingest_hyperliquid_bars.py + ingest/polymarket_odds.py). Stored under a DISTINCT metric
# ("monitor_yes_prob") so it never co-mingles with the CLOB "odds"/"odds_60"/"resolution" series and is OUTSIDE
# the quant-gate's store routing — this lane is propose-only, not a gate feature.
#
# Offline-testable: inject `_fetcher(url) -> list|dict`. One dead fetch is isolated (that market/tag contributes
# nothing, the scan never aborts). urllib + the shared certifi SSL context, like every other keyless source here.

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cosmu.correlate.correlation_map import (
    DEFAULT_WATCHLIST,
    EventType,
    all_gamma_tags,
    infer_polarity,
    match_event_type,
)
from cosmu.correlate.dates import ProbMove, latest_move, normalize_prob_series
from cosmu.data.altdata import AltDataPoint, _ssl_context
from cosmu.ingest.pipeline import append_dedup

logger = logging.getLogger("cosmu.correlate.monitor")

GAMMA_BASE = "https://gamma-api.polymarket.com"

# The store coordinates the monitor forward-hoards into. DISTINCT provider+metric so it never collides with the
# CLOB odds ingest (provider="polymarket", metric="odds"/"odds_60"/"resolution"). This series is NOT wired into
# the quant gate's _STORE_PROVIDER_OF — the conviction lane reads it directly, propose-only.
MONITOR_PROVIDER = "polymarket_monitor"
MONITOR_METRIC = "monitor_yes_prob"

# A move below this (in probability units) is noise, not a catalyst. 5pp matches the conviction gate's default
# min-edge and the theory doc's "≥+10pp/day is the candidate trigger" (10pp over a day → comfortably above 5pp).
DEFAULT_MIN_MOVE = 0.05


@dataclass(frozen=True)
class EventObservation:
    """One PIT-stamped reading of a watched market's YES probability. `polarity` (+1/−1) records whether THIS
    market's YES outcome means the event-type's risk is RISING (+1, "Hormuz closes") or FALLING (−1, "Hormuz
    reopens") — the sign the conviction template composes with the move + the asset link's direction."""

    event_type: str
    condition_id: str
    market_id: str
    question: str
    yes_prob: float
    polarity: int
    ts: datetime
    available_at: datetime  # == ts: a live snapshot is knowable at poll time (forward-hoard PIT contract)


@dataclass(frozen=True)
class EventMove:
    """A watched market whose latest hoarded move crossed the threshold — the catalyst the template reads. Carries
    the current observation + the signed `ProbMove` (delta = current − previous hoarded prob)."""

    observation: EventObservation
    move: ProbMove


@dataclass(frozen=True)
class MonitorResult:
    """One monitor pass: every observation made, how many NEW points were forward-hoarded (0 on an idempotent
    re-poll at the same instant), and the subset of observations whose latest move crossed `min_move`."""

    observations: list[EventObservation]
    written: int
    moves: list[EventMove]


def _yes_prob(market: dict) -> float | None:
    """The current YES probability for a Gamma market row, in [0,1], or None if unreadable. Preference: the YES
    leg of `outcomePrices` (the live mid the UI shows), then `lastTradePrice`, then a best-bid/ask midpoint. A
    multi-outcome market with no clear YES leg returns None (we only monitor binary YES/NO macro markets)."""
    prices = _as_float_list(market.get("outcomePrices"))
    outcomes = _as_str_list(market.get("outcomes"))
    if prices:
        # Prefer the leg literally labelled "Yes"; else index 0 (binary macro markets are [Yes, No]).
        idx = 0
        for i, name in enumerate(outcomes):
            if name.strip().lower() == "yes" and i < len(prices):
                idx = i
                break
        if idx < len(prices):
            return _clip01(prices[idx])
    last = _coerce_float(market.get("lastTradePrice"))
    if last is not None:
        return _clip01(last)
    bid, ask = _coerce_float(market.get("bestBid")), _coerce_float(market.get("bestAsk"))
    if bid is not None and ask is not None:
        return _clip01((bid + ask) / 2.0)
    if bid is not None:
        return _clip01(bid)
    if ask is not None:
        return _clip01(ask)
    return None


def _condition_id(market: dict) -> str | None:
    """The conditionId that keys the store (the universe_pairs symbol for a polymarket row IS the conditionId).
    Falls back to the numeric market id only when no conditionId is published."""
    cid = market.get("conditionId") or market.get("condition_id") or market.get("id")
    return str(cid) if cid else None


class PolymarketEventMonitor:
    """Keyless poller over the Polymarket Gamma API for the watchlist event-types. `scan` returns the current
    PIT-stamped observations; `poll_and_hoard` additionally forward-hoards them append-only and reports the moves
    that crossed the threshold. Pure-discovery + offline-injectable via `_fetcher`."""

    def __init__(
        self,
        *,
        watchlist: tuple[EventType, ...] = DEFAULT_WATCHLIST,
        markets_limit: int = 500,
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self._watchlist = watchlist
        self._markets_limit = markets_limit
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _discover_markets(self) -> list[dict]:
        """All candidate OPEN binary markets to consider, deduped by conditionId. Two keyless discovery paths
        (mirrors PolymarketClobSource): a broad `/markets` scan (keyword-matched locally) + a per-tag `/events`
        scan for the watchlist's Gamma tags. Each call is best-effort — one dead URL contributes nothing."""
        seen: set[str] = set()
        out: list[dict] = []

        def _consider(m: dict) -> None:
            if not isinstance(m, dict) or m.get("closed") or m.get("active") is False:
                return
            cid = _condition_id(m)
            if not cid or cid in seen:
                return
            seen.add(cid)
            out.append(m)

        # Path 1: a broad open-markets scan, keyword-matched locally against the watchlist.
        url = f"{GAMMA_BASE}/markets?closed=false&active=true&limit={int(self._markets_limit)}"
        try:
            rows = self._fetcher(url)
        except Exception:  # noqa: BLE001 — dead fetch → no markets from this path, never abort
            rows = []
        for m in rows if isinstance(rows, list) else []:
            _consider(m)

        # Path 2: per-tag events scan (each event nests its markets) for the watchlist's Gamma tags.
        for tag in all_gamma_tags():
            url = f"{GAMMA_BASE}/events?tag={urllib.parse.quote(tag)}&closed=false&limit=30"
            try:
                events = self._fetcher(url)
            except Exception:  # noqa: BLE001 — one dead tag is skipped, never aborts the scan
                continue
            for ev in events if isinstance(events, list) else []:
                for m in (ev.get("markets") or []) if isinstance(ev, dict) else []:
                    _consider(m)
        return out

    def scan(self, *, as_of: datetime | None = None) -> list[EventObservation]:
        """The current PIT-stamped YES-probability observation for every discovered market that matches a
        watchlist event-type and has a readable probability. `as_of` is the poll time (defaults to now); it is
        BOTH ts and available_at — a live snapshot is knowable exactly when polled."""
        now = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
        observations: list[EventObservation] = []
        for m in self._discover_markets():
            question = str(m.get("question") or "")
            et = match_event_type(question)
            if et is None:
                continue
            prob = _yes_prob(m)
            if prob is None:
                continue
            cid = _condition_id(m)
            if cid is None:
                continue
            observations.append(
                EventObservation(
                    event_type=et.key,
                    condition_id=cid,
                    market_id=str(m.get("id") or cid),
                    question=question,
                    yes_prob=prob,
                    polarity=infer_polarity(et, question),
                    ts=now,
                    available_at=now,
                )
            )
        return observations

    def poll_and_hoard(
        self,
        alt_store: Any,
        *,
        as_of: datetime | None = None,
        min_move: float = DEFAULT_MIN_MOVE,
    ) -> MonitorResult:
        """Scan, forward-hoard each observation append-only (idempotent on ts via `append_dedup`), then read the
        latest signed move off each market's hoarded series. Returns the observations, the count of NEW points
        hoarded, and the subset whose latest move's |delta| ≥ `min_move`. Per-market failure is isolated."""
        observations = self.scan(as_of=as_of)
        written = 0
        moves: list[EventMove] = []
        for obs in observations:
            point = AltDataPoint(ts=obs.ts, available_at=obs.available_at, value=obs.yes_prob)
            try:
                written += append_dedup(alt_store, MONITOR_PROVIDER, obs.condition_id, MONITOR_METRIC, [point])
            except Exception:  # noqa: BLE001 — one market's store failure never aborts the pass
                logger.warning("monitor hoard failed for %s", obs.condition_id, exc_info=True)
                continue
            series = normalize_prob_series(alt_store.read_all(MONITOR_PROVIDER, obs.condition_id, MONITOR_METRIC))
            mv = latest_move(series)
            if mv is not None and mv.abs_delta >= min_move:
                moves.append(EventMove(observation=obs, move=mv))
        return MonitorResult(observations=observations, written=written, moves=moves)


# ── small tolerant coercers (Gamma encodes vectors as JSON strings) ───────────────────────────────────────────

def _as_float_list(raw: Any) -> list[float]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for v in raw:
        f = _coerce_float(v)
        if f is None:
            return []
        out.append(f)
    return out


def _as_str_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return [str(v) for v in raw] if isinstance(raw, list) else []


def _coerce_float(raw: Any) -> float | None:
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _clip01(v: float) -> float:
    return min(max(v, 0.0), 1.0)


__all__ = [
    "DEFAULT_MIN_MOVE",
    "GAMMA_BASE",
    "MONITOR_METRIC",
    "MONITOR_PROVIDER",
    "EventMove",
    "EventObservation",
    "MonitorResult",
    "PolymarketEventMonitor",
]
