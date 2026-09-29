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
from datetime import UTC, datetime, timedelta
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
    `/prices-history?market={YES_token}&fidelity={fidelity}&interval=max` → {t, p} rows where p ∈ [0,1] is the
    implied probability. `fidelity` is the bucket size in MINUTES: 1440 = daily (the macro-feature cadence),
    60 = hourly (the cadence the per-cell min-trades Gate can clear — ~24× the rows). The series is stored keyed
    by the conditionId so the adapter can read it back without re-resolving the token (the universe_pairs symbol
    IS the conditionId).

    PIT (look-ahead fix, scout #385 Fix-C5): available_at = ts + ONE BUCKET, NOT ts. A CLOB bucket carries the
    midpoint as of the bucket's START, so stamping it `available_at == ts` would hand a backtest the bucket's own
    price on its entry bar — a 1-bucket look-ahead. Lagging availability by one bucket (`ts + fidelity minutes`)
    means a backtest's per-bar as-of join can only ever see a bucket that has fully closed. Revision-safe + shared
    `read_asof(available_at <= as_of)` contract; the lag is the only honest entry-bar timing.

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

    # Number of CALENDAR DAYS per windowed sub-daily page. The trust experiment (#389) measured that
    # `interval=max&fidelity=60` silently returns daily-or-NOTHING — true hourly spacing requires explicit
    # `startTs`/`endTs` windows (~335 rows / 14-day window at fidelity=60). 14 days is the proven window size that
    # returns ~3600s-spaced rows; we page it across the market's life so the hourly series is genuinely hourly.
    _WINDOW_DAYS = 14
    # Cap the number of windowed pages per market so one long-lived market can't hammer the public CLOB unbounded
    # (14 days × 180 pages ≈ 7 years of hourly history — far more than any open market needs). A market older than
    # this simply starts its hourly history this many windows back, which is plenty for the per-cell Gate.
    _MAX_WINDOWS = 180

    def fetch_odds(self, condition_id: str, *, fidelity: int = 1440, limit: int = 100_000) -> list[AltDataPoint]:
        """Full YES-odds history for one conditionId at `fidelity`-minute buckets (1440 = daily, 60 = hourly),
        ascending by ts. Empty on any failure (unresolvable token, dead CLOB fetch, no history) — the ingest
        treats it as 0 rows for that market, never an abort. PIT: `available_at = ts + one bucket` (the look-ahead
        fix), so a backtest only sees a bucket after it has fully closed.

        DAILY (`fidelity>=1440`) uses the single `interval=max` call (byte-identical to before). SUB-DAILY
        (`fidelity<1440`, i.e. hourly/minute) MUST use explicit `startTs`/`endTs` WINDOWS — the trust experiment
        proved `interval=max&fidelity=60` silently collapses to daily-or-nothing, so the hourly cadence the
        per-cell min-trades Gate needs only materializes via windowed/paged requests (~335 rows / 14-day window).
        Both paths converge on the SAME {t,p} row parse + the SAME +1-bucket PIT lag, so the only difference is the
        request shape."""
        token = self.yes_token_for(condition_id)
        if not token:
            return []
        bucket = timedelta(minutes=int(fidelity))  # +1-bucket PIT lag: a closed bucket is knowable only at its end
        raw_rows = (
            self._fetch_max(token, fidelity)
            if int(fidelity) >= 1440
            else self._fetch_windowed(token, fidelity)
        )
        out: list[AltDataPoint] = []
        for row in raw_rows:
            try:
                ts = datetime.fromtimestamp(int(row["t"]), tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts + bucket, value=float(row["p"])))
            except (KeyError, TypeError, ValueError, OSError):
                continue
        # Dedup by ts (windowed pages can overlap at the boundary), keep the last seen, then sort + tail.
        by_ts: dict[datetime, AltDataPoint] = {p.ts: p for p in out}
        return sorted(by_ts.values(), key=lambda p: p.ts)[-limit:]

    def _fetch_max(self, token: str, fidelity: int) -> list[dict]:
        """The single full-history call (`interval=max`) — the DAILY path, unchanged. Dead fetch → []."""
        query = urllib.parse.urlencode({"market": token, "fidelity": int(fidelity), "interval": "max"})
        url = f"{self.CLOB_BASE}/prices-history?{query}"
        try:
            payload = self._clob_fetcher(url)
        except Exception:  # noqa: BLE001 — network/timeout/404 → skip, never abort
            return []
        return payload.get("history", []) if isinstance(payload, dict) else []

    def _fetch_windowed(self, token: str, fidelity: int) -> list[dict]:
        """The SUB-DAILY (hourly/minute) path: page backward in `_WINDOW_DAYS`-day `startTs`/`endTs` windows from
        now, stopping when a window returns no rows (the market predates it) or `_MAX_WINDOWS` is reached. This is
        the windowed fetch the trust experiment proved is the ONLY way to get true sub-daily spacing from the CLOB
        (`interval=max&fidelity=60` collapses to daily-or-nothing). Each window is best-effort: one dead page is
        skipped, never aborts the market. Returns the concatenated raw {t,p} rows (the caller dedups + sorts)."""
        now = datetime.now(tz=UTC)
        window = timedelta(days=self._WINDOW_DAYS)
        end = now
        rows: list[dict] = []
        for _ in range(self._MAX_WINDOWS):
            start = end - window
            query = urllib.parse.urlencode({
                "market": token, "fidelity": int(fidelity),
                "startTs": int(start.timestamp()), "endTs": int(end.timestamp()),
            })
            url = f"{self.CLOB_BASE}/prices-history?{query}"
            try:
                payload = self._clob_fetcher(url)
            except Exception:  # noqa: BLE001 — one dead window is skipped, never aborts the market
                break
            page = payload.get("history", []) if isinstance(payload, dict) else []
            if not page:
                break  # the market predates this window (no older history) → stop paging
            rows.extend(page)
            end = start  # step the window back one full span
        return rows


def _parse_resolution_ts(m: dict) -> datetime | None:
    """The REAL UMA resolution time of a Polymarket market from its Gamma row — the instant the outcome became
    authoritative ($1/$0). Tries the explicit UMA fields first (`umaResolutionStatus` carries `resolvedTime` /
    the data-api `resolvedAt`), then the market-level `closedTime`, and ONLY as a last resort the SCHEDULED
    `endDate` (when no real resolution stamp is published). Returns None when no time can be parsed at all (the
    caller then refuses to mint a resolution point — never an unstamped settlement that would PIT-leak). The
    distinction matters: `available_at` MUST be the real resolution ts (when we could have known the payout), not
    the scheduled end, or a backtest would settle a contract before the chain actually resolved it."""
    for key in ("resolvedTime", "resolvedAt", "umaResolutionTime", "closedTime", "resolutionTime"):
        ts = _coerce_ts(m.get(key))
        if ts is not None:
            return ts
    # Gamma sometimes nests the resolution stamp under the UMA status object rather than a flat field.
    status = m.get("umaResolutionStatus") or m.get("umaResolutionStatuses")
    if isinstance(status, dict):
        for key in ("resolvedTime", "resolvedAt", "timestamp"):
            ts = _coerce_ts(status.get(key))
            if ts is not None:
                return ts
    if isinstance(status, list):
        for s in status:
            if isinstance(s, dict):
                for key in ("resolvedTime", "resolvedAt", "timestamp"):
                    ts = _coerce_ts(s.get(key))
                    if ts is not None:
                        return ts
    return _coerce_ts(m.get("endDate"))  # last resort: the SCHEDULED end (no real resolution stamp published)


def _coerce_ts(raw: Any) -> datetime | None:
    """A Gamma timestamp (unix-seconds int/str, unix-millis, or an ISO-8601 string) → an aware UTC datetime, or
    None when unparseable/empty. Tolerant of the trailing 'Z' (pre-3.11 fromisoformat rejected it)."""
    if raw is None or raw == "":
        return None
    # Numeric (unix seconds or millis).
    try:
        n = float(raw)
        if n > 1e12:  # plausibly milliseconds
            n /= 1000.0
        if n > 0:
            return datetime.fromtimestamp(n, tz=UTC)
    except (TypeError, ValueError):
        pass
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _yes_payout_from_market(m: dict) -> float | None:
    """The authoritative YES payout ∈ {1.0, 0.0} for a RESOLVED Polymarket market, from its Gamma/CTF row.
    Preference order (most authoritative first):
      1. `payoutNumerators` — the on-chain CTF settlement vector (e.g. [1, 0] = YES wins, [0, 1] = NO wins). The
         YES payout is numerators[0] / sum(numerators). This is the SAME field the exec/settlement path trusts.
      2. `outcomePrices` — Gamma's resolved outcome prices; after resolution the YES leg is exactly 1.0 or 0.0.
    Returns None when the market is not yet resolved or carries no parseable payout (the caller skips it — a market
    with no authoritative outcome must NOT settle at a fabricated $1/$0). A near-but-not-exact value (a still-live
    0.97 odds masquerading as a price) is rejected: only a genuine {0,1} payout (within a tiny epsilon) settles."""
    nums = _as_float_list(m.get("payoutNumerators"))
    if nums and len(nums) >= 1:
        total = sum(nums)
        if total > 0:
            yes = nums[0] / total
            return 1.0 if yes >= 0.5 else 0.0  # CTF numerators are integral → an exact binary payout
    # Fall back to Gamma's resolved outcomePrices, but ONLY when the market is actually resolved AND the YES leg
    # is a genuine 0/1 (not a still-trading mid-odds): a resolved binary market prices YES at exactly 1.0 or 0.0.
    if _is_resolved(m):
        prices = _as_float_list(m.get("outcomePrices"))
        if prices and len(prices) >= 1:
            yes = prices[0]
            if abs(yes - 1.0) <= 1e-6:
                return 1.0
            if abs(yes - 0.0) <= 1e-6:
                return 0.0
    return None


def _is_resolved(m: dict) -> bool:
    """True when a Polymarket Gamma row reports the market as resolved/closed (the UMA outcome is final)."""
    status = m.get("umaResolutionStatus")
    if isinstance(status, str) and status.strip().lower() == "resolved":
        return True
    if isinstance(status, dict) and str(status.get("status", "")).strip().lower() == "resolved":
        return True
    return bool(m.get("closed")) and not m.get("active", False)


def _as_float_list(raw: Any) -> list[float]:
    """A Gamma numeric vector — a JSON-encoded string ('[1, 0]'), a real list, or [] — coerced to floats. Any
    unparseable entry collapses the whole vector to [] (a partial parse must never settle a market half-right)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for v in raw:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            return []
    return out


class PolymarketResolutionSource:
    """The authoritative UMA/CTF RESOLUTION of a Polymarket conditionId — the missing settlement join. For each
    conditionId it resolves (via Gamma `/markets?condition_ids={cid}`) the binary outcome that became final on
    chain: the YES share's true payout ∈ {$1, $0} from `payoutNumerators` (the CTF settlement vector the exec
    path already trusts), falling back to Gamma's resolved `outcomePrices`. This converts the prediction lane
    from 'odds mean-reversion' (a position held to resolution settles at the LAST odds quote — untestable) to a
    real resolution-settled backtest (it settles at the authoritative $1/$0).

    PIT contract (the whole point): the single resolution AltDataPoint is stamped
        ts          = the real resolution time (when the outcome became authoritative)
        available_at = the SAME real resolution time (NEVER the scheduled endDate, never earlier)
    so a backtest's per-bar as-of read can see the payout ONLY after the chain actually resolved it. A market
    that is NOT yet resolved (no parseable payout, or no resolution timestamp) yields NO point — the backtest
    then has no settlement to apply and the position marks at the last odds, exactly as before (honest: we never
    fabricate a resolution that hasn't happened). `value` is the YES payout (1.0 or 0.0).

    Offline-testable via the same injected `_gamma_fetcher(url)->list|dict` the odds source uses."""

    GAMMA_BASE = "https://gamma-api.polymarket.com"

    def __init__(self, *, _gamma_fetcher: Callable[[str], Any] | None = None) -> None:
        self._gamma_fetcher = _gamma_fetcher or self._fetch

    def _fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_resolution(self, condition_id: str) -> list[AltDataPoint]:
        """The authoritative resolution point(s) for one conditionId — a list of AT MOST ONE AltDataPoint:
        the YES payout (1.0/0.0) stamped at the real resolution time (ts == available_at == resolution ts). Empty
        when the market is unresolved, unfetchable, or carries no parseable payout/timestamp — the caller treats
        that as 'no settlement yet' and never fabricates one. Returns a list (not a scalar) so the ingest reuses
        the SAME append_dedup primitive as the odds series (append-only, ts-keyed, idempotent)."""
        url = f"{self.GAMMA_BASE}/markets?condition_ids={urllib.parse.quote(condition_id)}"
        try:
            data = self._gamma_fetcher(url)
        except Exception:  # noqa: BLE001 — network/timeout/404 → no resolution for this market, never abort
            return []
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        for m in rows:
            if not isinstance(m, dict):
                continue
            payout = _yes_payout_from_market(m)
            if payout is None:
                continue  # not resolved (or no authoritative payout) → no settlement point
            resolved_at = _parse_resolution_ts(m)
            if resolved_at is None:
                continue  # resolved but no knowable timestamp → refuse (an unstamped settlement would PIT-leak)
            # ts == available_at == the real resolution time: the payout is knowable ONLY once the chain resolved.
            return [AltDataPoint(ts=resolved_at, available_at=resolved_at, value=payout)]
        return []
