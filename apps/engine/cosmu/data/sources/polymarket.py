# intent: Polymarket CLOB historical data source — full daily price-history per macro market, aggregated
# into three composite time series (pm_implied_prob / pm_prob_velocity / pm_book_depth) suitable for
# point-in-time backtesting. The fix that unblocked DATA-BLOCKED (#87): the old PolymarketClobProvider
# called PolymarketGammaProvider.fetch_series() which only returns a single snapshot (current yes_prob).
# This source calls the CLOB /prices-history endpoint per market (interval=max, fidelity=1440 → daily),
# returning 180-400+ daily rows per active macro market.
#
# Key API details:
#   - Gamma /events|/markets: discovers markets; returns clobTokenIds (the YES token for CLOB)
#   - CLOB /prices-history?market={YES_token}&fidelity=1440&interval=max: full daily history, free, no key
#   - market param = clobTokenIds[0] (the YES outcome token), NOT the numeric id or conditionId
#
# PIT contract: available_at = ts (midpoint price is stamped at bucket start; no declared release lag).
# Offline testability: inject _gamma_fetcher(url)->list|dict and _clob_fetcher(url)->dict.
# One dead CLOB fetch silently returns [] for that market; the run never aborts.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cosmu.data.altdata import AltDataPoint, PolymarketGammaProvider, _ssl_context


class PolymarketClobSource:
    """Daily Polymarket macro-market metrics via the public CLOB prices-history API (free, no key).

    Discovery: Gamma API events+keywords finds top-N macro/risk markets (same logic as
    PolymarketGammaProvider) but preserves clobTokenIds[0] — the YES-outcome token ID that the
    CLOB prices-history endpoint actually requires (not the numeric market id or conditionId).

    Three aggregate metrics (all market-wide, stored under provider="polymarket"):
      pm_implied_prob   — mean yes_prob across discovered macro markets for each calendar day
      pm_prob_velocity  — day-over-day delta of pm_implied_prob
      pm_book_depth     — fraction of discovered markets with active price data that day
                          (ramps from low to 1.0 as newer markets age into the lookback)

    Typical depth (2026-06): top-8 Polymarket Economy/Finance/Geopolitics markets have 180-400
    daily rows from their launch date. The aggregate series starts from the oldest market's first
    available day.
    """

    CLOB_BASE = "https://clob.polymarket.com"
    GAMMA_BASE = "https://gamma-api.polymarket.com"

    def __init__(
        self,
        pin_token: str | None = None,
        max_markets: int = 8,
        *,
        _gamma_fetcher: Callable[[str], Any] | None = None,
        _clob_fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self._pin_token = pin_token
        self._max_markets = max_markets
        self._gamma_fetcher = _gamma_fetcher or self._fetch
        self._clob_fetcher = _clob_fetcher or self._fetch

    def _fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _clob_token(m: dict) -> str | None:
        """Extract YES-outcome clobTokenId — required by the CLOB prices-history endpoint."""
        tids = m.get("clobTokenIds") or "[]"
        if isinstance(tids, str):
            try:
                tids = json.loads(tids)
            except (json.JSONDecodeError, TypeError):
                tids = []
        return str(tids[0]) if tids else None

    def _discover_macro_markets(self) -> list[dict]:
        """Events+keyword scan identical to PolymarketGammaProvider but retains clobTokenIds[0].
        Only markets with enableOrderBook=True can serve CLOB history; others are skipped."""
        macro_tags_lower = {t.lower() for t in PolymarketGammaProvider.MACRO_TAGS}
        seen: set[str] = set()
        hits: list[dict] = []

        for tag in PolymarketGammaProvider.MACRO_TAGS:
            url = f"{self.GAMMA_BASE}/events?tag={urllib.parse.quote(tag)}&closed=false&limit=30"
            try:
                events = self._gamma_fetcher(url)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(events, list):
                continue
            for ev in events:
                ev_tags = {(t.get("label") or "").lower() for t in (ev.get("tags") or [])}
                if not ev_tags & macro_tags_lower:
                    continue
                for m in ev.get("markets") or []:
                    if not m.get("active") or m.get("closed") or not m.get("enableOrderBook"):
                        continue
                    mid = str(m.get("id") or "")
                    token = self._clob_token(m)
                    if not mid or not token or mid in seen:
                        continue
                    seen.add(mid)
                    liq = float(m.get("liquidity") or m.get("liquidityClob") or 0)
                    hits.append({"id": mid, "clob_token_id": token, "question": m.get("question", ""), "liquidity": liq})

        url = f"{self.GAMMA_BASE}/markets?closed=false&active=true&limit=100"
        try:
            raw = self._gamma_fetcher(url)
        except Exception:  # noqa: BLE001
            raw = []
        for m in raw if isinstance(raw, list) else []:
            q = (m.get("question") or "").lower()
            if not any(kw in q for kw in PolymarketGammaProvider.MACRO_KEYWORDS):
                continue
            if not m.get("active") or m.get("closed") or not m.get("enableOrderBook"):
                continue
            mid = str(m.get("id") or "")
            token = self._clob_token(m)
            if not mid or not token or mid in seen:
                continue
            seen.add(mid)
            liq = float(m.get("liquidity") or m.get("liquidityClob") or 0)
            hits.append({"id": mid, "clob_token_id": token, "question": m.get("question", ""), "liquidity": liq})

        hits.sort(key=lambda h: h["liquidity"], reverse=True)
        return hits[: self._max_markets]

    def _market_history(self, clob_token: str, limit: int) -> list[AltDataPoint]:
        """Full daily price history for one market (YES token → CLOB prices-history). Dead fetch → []."""
        query = urllib.parse.urlencode({"market": clob_token, "fidelity": 1440, "interval": "max"})
        url = f"{self.CLOB_BASE}/prices-history?{query}"
        try:
            payload = self._clob_fetcher(url)
        except Exception:  # noqa: BLE001 — network/timeout/404 → skip, never abort
            return []
        rows = payload.get("history", []) if isinstance(payload, dict) else []
        out: list[AltDataPoint] = []
        for row in rows:
            try:
                ts = datetime.fromtimestamp(int(row["t"]), tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["p"])))
            except (KeyError, TypeError, ValueError, OSError):
                continue
        return sorted(out, key=lambda p: p.ts)[-limit:]

    def _aggregate(self, per_market: list[list[AltDataPoint]]) -> list[AltDataPoint]:
        """Mean yes_prob across all markets for each calendar day (bucket to day boundary)."""
        by_day: dict[datetime, list[float]] = {}
        for series in per_market:
            for pt in series:
                day = pt.ts.replace(hour=0, minute=0, second=0, microsecond=0)
                by_day.setdefault(day, []).append(pt.value)
        return [
            AltDataPoint(ts=day, available_at=day, value=sum(vals) / len(vals))
            for day, vals in sorted(by_day.items())
        ]

    def resolve_token(self, symbol: str) -> str | None:
        """Best-effort core-symbol -> CLOB YES-token-id for the execution adapter. A symbol that is already a
        numeric/hex CLOB token id passes through; otherwise the macro-market discovery is keyword-matched
        against each market's question (the synthetic catalog label, e.g. 'PM-FED-CUT-2026', tokenized on
        '-'/'_'). Returns the best (most liquid) match's YES token, else None — the adapter then treats the
        symbol verbatim. Pure-discovery + offline-injectable via the same _gamma_fetcher."""
        s = symbol.strip()
        if s.isdigit() or (s.startswith("0x") and len(s) > 10):
            return s
        words = {w for w in s.lower().replace("pm-", "").replace("-", " ").replace("_", " ").split() if len(w) > 2}
        if not words:
            return None
        best: tuple[int, float, str] | None = None  # (overlap, liquidity, token)
        for m in self._discover_macro_markets():
            q = (m.get("question") or "").lower()
            overlap = sum(1 for w in words if w in q)
            if overlap == 0:
                continue
            cand = (overlap, float(m.get("liquidity") or 0), str(m["clob_token_id"]))
            if best is None or cand[:2] > best[:2]:
                best = cand
        return best[2] if best else None

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in ("pm_implied_prob", "pm_prob_velocity", "pm_book_depth"):
            return []

        markets = self._discover_macro_markets()
        if not markets:
            return []

        per_market = [self._market_history(m["clob_token_id"], limit) for m in markets]

        if metric == "pm_implied_prob":
            return self._aggregate(per_market)[-limit:]

        if metric == "pm_prob_velocity":
            agg = self._aggregate(per_market)
            if len(agg) < 2:
                return []
            out: list[AltDataPoint] = []
            for i in range(1, len(agg)):
                delta = agg[i].value - agg[i - 1].value
                out.append(AltDataPoint(ts=agg[i].ts, available_at=agg[i].available_at, value=delta))
            return out[-limit:]

        # pm_book_depth: fraction of discovered markets with price data on each calendar day.
        # Genuinely varies: oldest markets contribute from day 1; newest from their own launch.
        n = len(markets)
        active: dict[datetime, int] = {}
        for series in per_market:
            for pt in series:
                day = pt.ts.replace(hour=0, minute=0, second=0, microsecond=0)
                active[day] = active.get(day, 0) + 1
        if not active:
            return []
        return [
            AltDataPoint(ts=day, available_at=day, value=cnt / n)
            for day, cnt in sorted(active.items())
        ][-limit:]


def resolve_clob_token(symbol: str) -> str | None:
    """Module-level convenience: resolve a core symbol to its CLOB YES-token id via live Gamma discovery.
    Used by the Polymarket execution adapter's lazy resolver; returns None on any failure (best-effort)."""
    return PolymarketClobSource().resolve_token(symbol)


class PerMarketOddsSource:
    """Historical per-MARKET YES-odds for a single Polymarket conditionId — the per-conditionId odds series the
    `PredictionDataAdapter` reads (provider="polymarket", symbol=conditionId, metric="odds"), as opposed to the
    aggregate macro composites in `PolymarketClobSource`.

    The CLOB `/prices-history` endpoint is keyed by the YES-outcome clobTokenId, NOT the conditionId — so each
    fetch is two hops: Gamma `/markets?condition_ids={cid}` → `clobTokenIds[0]` (the YES token) → CLOB
    `/prices-history?market={YES_token}&fidelity=1440&interval=max` → daily {t, p} rows where p ∈ [0,1] is the
    implied probability. The series is stored keyed by the conditionId so the adapter can read it back without
    re-resolving the token (the universe_pairs symbol IS the conditionId). PIT: available_at = ts (a midpoint
    quote is known at its own bucket time; no declared release lag — same contract as `PolymarketClobSource`).

    Offline-testable via injected `_gamma_fetcher(url)->list|dict` and `_clob_fetcher(url)->dict`.
    """

    CLOB_BASE = "https://clob.polymarket.com"
    GAMMA_BASE = "https://gamma-api.polymarket.com"

    def __init__(
        self,
        *,
        _gamma_fetcher: Callable[[str], Any] | None = None,
        _clob_fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self._gamma_fetcher = _gamma_fetcher or self._fetch
        self._clob_fetcher = _clob_fetcher or self._fetch

    def _fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def yes_token_for(self, condition_id: str) -> str | None:
        """Resolve a conditionId to its YES-outcome clobTokenId via Gamma. None on any failure / missing token —
        the caller then skips this market (one dead resolution never aborts the batch)."""
        url = f"{self.GAMMA_BASE}/markets?condition_ids={urllib.parse.quote(condition_id)}"
        try:
            data = self._gamma_fetcher(url)
        except Exception:  # noqa: BLE001 — network/timeout/404 → skip, never abort
            return None
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        for m in rows:
            if not isinstance(m, dict):
                continue
            token = PolymarketClobSource._clob_token(m)  # noqa: SLF001 — shared YES-token extractor
            if token:
                return token
        return None

    def fetch_odds(self, condition_id: str, *, limit: int = 100_000) -> list[AltDataPoint]:
        """Full daily YES-odds history for one conditionId, ascending by ts. Empty on any failure (unresolvable
        token, dead CLOB fetch, no history) — the ingest treats it as 0 rows for that market, never an abort."""
        token = self.yes_token_for(condition_id)
        if not token:
            return []
        query = urllib.parse.urlencode({"market": token, "fidelity": 1440, "interval": "max"})
        url = f"{self.CLOB_BASE}/prices-history?{query}"
        try:
            payload = self._clob_fetcher(url)
        except Exception:  # noqa: BLE001 — network/timeout/404 → skip, never abort
            return []
        rows = payload.get("history", []) if isinstance(payload, dict) else []
        out: list[AltDataPoint] = []
        for row in rows:
            try:
                ts = datetime.fromtimestamp(int(row["t"]), tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["p"])))
            except (KeyError, TypeError, ValueError, OSError):
                continue
        return sorted(out, key=lambda p: p.ts)[-limit:]
