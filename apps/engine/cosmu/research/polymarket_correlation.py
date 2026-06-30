# intent: the LLM/Conviction lane's "find a REAL Polymarket→correlated-asset play" machinery, made reusable +
# offline-testable. Three pure-ish pieces, no money path, propose-only:
#   1. EVENT_THEMES — a CURATED map of macro/geopolitical/commodity/rates/regulatory event TYPES → the liquid
#      tradeable asset(s) whose price the event should move, each with a one-line CAUSAL mechanism + a REPUTABLE
#      citation (EIA / Fed / academic — never a course-seller). This is the human-vetted knowledge the LLM lane
#      leans on; the keywords are how a live market's question text routes to a theme.
#   2. LiveEventScanner — hits Polymarket's keyless Gamma API, keeps the OPEN/orderbook/liquid markets, routes
#      each to a theme, and ranks by a TRANSPARENT leverage score (attention × liquidity-gate × room-to-move ×
#      proximity-window × mappability). Thin / non-orderbook / pinned-at-extreme / unmappable markets score ~0.
#   3. lead_lag_profile — the honest measurement: given a market's daily probability series and a correlated
#      asset's daily price series, it computes the cross-correlation of Δprob_t vs asset-return_{t+lag} across
#      lags and returns a verdict {LEADS | COINCIDENT | LAGS | NONE}. A "tradeable lead" requires a positive-lag
#      correlation that beats the coincident (lag-0) one — anything else means the move is already priced (the
#      strong prior for deep, fast assets like crude/rates) and there is no latency-free edge.
#
# Everything network-touching is injectable (`_gamma_fetcher`, `now`) so the unit tests are hermetic. The live
# wiring (CLOB probability history, FRED prices) lives in scripts/research/polymarket_live_opportunities_*.py.

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cosmu.data.providers._types import _ssl_context

# --------------------------------------------------------------------------- curated knowledge


@dataclass(frozen=True)
class AssetLink:
    """How a prediction-market probability maps to a tradeable asset's price.

    `direction` is the sign of the move IF the YES probability RISES:
      "inverse" — prob↑ ⇒ asset price DOWN (e.g. de-escalation odds↑ ⇒ oil risk-premium bleeds out)
      "same"    — prob↑ ⇒ asset price UP
    `mechanism` is the one-line causal story; `source` is a reputation-to-lose citation (the trust heuristic:
    EIA / Federal Reserve / peer-reviewed — NEVER retail-TA / course-seller content)."""

    asset: str
    direction: str
    mechanism: str
    source: str


@dataclass(frozen=True)
class EventTheme:
    key: str
    keywords: tuple[str, ...]
    asset_links: tuple[AssetLink, ...]


# The curated event-TYPE → correlated-asset map. Order matters only for display; routing is by keyword hit.
EVENT_THEMES: tuple[EventTheme, ...] = (
    EventTheme(
        key="oil_geopolitics",
        keywords=(
            "strait of hormuz", "hormuz", "opec", "crude", "wti", "brent", "oil",
            "iran", "israel", "saudi", "kharg", "tanker", "refinery", "pipeline",
        ),
        asset_links=(
            AssetLink(
                asset="WTI crude (CL=F / USO)",
                direction="inverse",
                mechanism="The Strait of Hormuz carries ~20% of global petroleum liquids; a higher 'returns to "
                "normal / ceasefire holds' probability removes the supply-disruption risk premium → crude falls.",
                source="U.S. EIA, 'The Strait of Hormuz is the world's most important oil transit chokepoint' "
                "(eia.gov, 2023-11) — ~20 Mb/d, ~20% of global petroleum liquids consumption.",
            ),
            AssetLink(
                asset="Brent crude (BZ=F)",
                direction="inverse",
                mechanism="Brent is the seaborne benchmark most exposed to Gulf/Hormuz transit risk; de-escalation "
                "odds↑ compress the geopolitical premium faster in Brent than in landlocked WTI.",
                source="U.S. EIA chokepoint brief (2023-11); IMF WP/15/268 on oil-price geopolitical risk premia.",
            ),
        ),
    ),
    EventTheme(
        key="us_rates",
        keywords=(
            "fed ", "fomc", "interest rate", "rate cut", "rate hike", "powell",
            "basis point", "bps", "jerome", "federal reserve",
        ),
        asset_links=(
            AssetLink(
                asset="2Y Treasury yield (DGS2 / SHY)",
                direction="same",
                mechanism="The 2Y yield is the purest market proxy for the expected Fed path; a higher 'hike' (or "
                "lower 'cut') probability lifts the 2Y. The front end reprices on the same data the PM reprices on.",
                source="Federal Reserve H.15; Gürkaynak-Sack-Swanson (2005) on policy-expectation sensitivity of "
                "the short end.",
            ),
            AssetLink(
                asset="10Y Treasury yield (DGS10 / TLT inverse)",
                direction="same",
                mechanism="Hawkish repricing lifts the whole curve; 10Y moves less than 2Y (bull/bear flattening), "
                "so the 2Y is the higher-beta read on a Fed-decision market.",
                source="Federal Reserve H.15; Nakamura-Steinsson (2018) high-frequency monetary-policy shocks.",
            ),
        ),
    ),
    EventTheme(
        key="macro_inflation_growth",
        keywords=(
            "recession", "gdp", "inflation", "cpi", "pce", "unemployment", "jobs report",
            "debt ceiling", "default", "tariff", "trade war",
        ),
        asset_links=(
            AssetLink(
                asset="S&P 500 (SPY)",
                direction="inverse",
                mechanism="Higher recession / hot-inflation odds raise the discount rate and cut earnings "
                "expectations → equities down. But CPI/jobs prints hit equities within seconds of release.",
                source="Federal Reserve / BLS release calendars; Boyd-Hu-Jagannathan (2005) on news-vs-stocks.",
            ),
            AssetLink(
                asset="Gold (GC=F / GLD)",
                direction="same",
                mechanism="Recession / stagflation odds↑ → real-yield down + safe-haven bid → gold up.",
                source="Erb-Harvey (2013) 'The Golden Dilemma' on gold as a macro hedge.",
            ),
        ),
    ),
    EventTheme(
        key="geopolitics_broad",
        keywords=(
            "war", "invade", "invasion", "missile", "nuclear", "ceasefire", "nato",
            "russia", "ukraine", "china", "taiwan", "putin", "venezuela", "north korea",
            "military", "troops", "coup",
        ),
        asset_links=(
            AssetLink(
                asset="Gold (GC=F / GLD)",
                direction="inverse",
                mechanism="Escalation odds↑ → safe-haven bid → gold up; so a 'de-escalation/ceasefire' YES↑ implies "
                "gold down. Gold is deep and reacts to the same headlines, so the lead is usually not tradeable.",
                source="Baur-Lucey (2010) on gold as a safe haven; academic flight-to-safety literature.",
            ),
            AssetLink(
                asset="Defense equities (ITA)",
                direction="inverse",
                mechanism="Sustained-conflict odds↑ support defense order books; a ceasefire/de-escalation YES↑ "
                "removes that bid.",
                source="Defense-spending event-study literature (e.g. Capelle-Blancard on conflict & equities).",
            ),
        ),
    ),
    EventTheme(
        key="crypto_price",
        keywords=("bitcoin", "btc", "ethereum", "eth ", "solana", "crypto", "microstrategy"),
        asset_links=(),  # intentionally empty: see note below
    ),
    EventTheme(
        key="regulatory",
        keywords=(
            "sec ", "etf", "approve", "ban", "regulat", "executive order",
            "supreme court", "antitrust", "merger",
        ),
        asset_links=(),  # mapped case-by-case to the named entity; no generic liquid proxy
    ),
)

# Crypto price-threshold markets ("Will BTC be above $X on date") are DELIBERATELY left unmapped: their
# probability is a deterministic function of the spot price (a digital option on BTC), so the asset CANNOT follow
# the market — the market mechanically follows the asset. They are the canonical "coincident / already priced /
# no lead" exclusion and exist here only so the scanner can label and drop them rather than chase them.
_NO_LEAD_THEMES = frozenset({"crypto_price"})


def classify_theme(question: str) -> EventTheme | None:
    """Route a market's question text to the FIRST theme whose keywords it hits (None = off-theme, e.g. sports).
    First-match-wins is intentional: the themes are ordered most-specific-cause first (oil/rates before the broad
    geopolitics bucket) so 'Strait of Hormuz' lands on oil, not the generic geopolitics catch-all."""
    q = f" {question.lower()} "
    for theme in EVENT_THEMES:
        if any(kw in q for kw in theme.keywords):
            return theme
    return None


# --------------------------------------------------------------------------- live scanner


@dataclass(frozen=True)
class EventCandidate:
    question: str
    condition_id: str
    yes_token: str | None
    yes_prob: float | None
    end_date: str | None
    days_to_event: float | None
    volume_24h: float
    volume_1wk: float
    liquidity: float
    theme: str | None
    asset_links: tuple[AssetLink, ...]
    leverage: float
    components: dict[str, float] = field(default_factory=dict)
    excluded_reason: str | None = None


# A market thinner than this much resting USD liquidity is treated as un-tradeable noise (the practical
# "thin / ambiguous" filter — a deep book is the cheapest proxy for a market the venue + bettors take seriously).
DEFAULT_MIN_LIQUIDITY = 20_000.0
# The proximity window (calendar days to resolution) where a prediction market is most useful: far enough out to
# trade the correlated asset, near enough that the probability actually MOVES. Outside [min,max] the leverage is
# down-weighted, not zeroed (a long-dated market can still matter, it just has less per-day information).
PROXIMITY_MIN_DAYS = 3.0
PROXIMITY_MAX_DAYS = 90.0


class LiveEventScanner:
    """Scan live Polymarket (keyless Gamma) for the highest-leverage macro/geo/commodity/rates/regulatory event
    markets to monitor RIGHT NOW, ranked by a transparent leverage score. Discovery only — no odds history, no
    execution. Inject `_gamma_fetcher(url)->list|dict` and `now()->datetime` for hermetic tests."""

    GAMMA_BASE = "https://gamma-api.polymarket.com"
    # The orders we page through to assemble the candidate set: most-traded, deepest-book, and busy-this-week.
    # The union is what a human monitoring "what's hot AND liquid" would watch.
    _ORDERS = ("volume24hr", "liquidity", "volume1wk")

    def __init__(
        self,
        *,
        gamma_url: str | None = None,
        min_liquidity: float = DEFAULT_MIN_LIQUIDITY,
        _gamma_fetcher: Callable[[str], Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.gamma_url = (gamma_url or self.GAMMA_BASE).rstrip("/")
        self.min_liquidity = float(min_liquidity)
        self._gamma_fetcher = _gamma_fetcher or self._fetch
        self._now = now or (lambda: datetime.now(tz=UTC))

    def _fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _pull(self, max_per_page: int, pages: int) -> dict[str, dict]:
        """Union of the top open markets across the _ORDERS, deduped by conditionId (fallback id). One dead page
        is skipped, never aborts the scan."""
        seen: dict[str, dict] = {}
        for order in self._ORDERS:
            for page in range(pages):
                offset = page * max_per_page
                url = (
                    f"{self.gamma_url}/markets?closed=false&active=true"
                    f"&order={order}&ascending=false&limit={max_per_page}&offset={offset}"
                )
                try:
                    rows = self._gamma_fetcher(url)
                except Exception:  # noqa: BLE001 — one dead page never aborts the scan
                    continue
                if not isinstance(rows, list):
                    continue
                for m in rows:
                    if not isinstance(m, dict):
                        continue
                    cid = str(m.get("conditionId") or m.get("id") or "")
                    if cid and cid not in seen:
                        seen[cid] = m
        return seen

    @staticmethod
    def _yes_prob(m: dict) -> float | None:
        raw = m.get("outcomePrices") or "[]"
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None
        try:
            return float(raw[0]) if raw else None
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _yes_token(m: dict) -> str | None:
        tids = m.get("clobTokenIds") or "[]"
        if isinstance(tids, str):
            try:
                tids = json.loads(tids)
            except (json.JSONDecodeError, TypeError):
                tids = []
        return str(tids[0]) if tids else None

    def _days_to_event(self, m: dict) -> float | None:
        end = m.get("endDateIso") or m.get("endDate")
        if not end:
            return None
        try:
            s = str(end).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s if "T" in s else f"{s}T00:00:00+00:00")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            return None
        return (dt - self._now()).total_seconds() / 86400.0

    @staticmethod
    def _proximity_weight(days: float | None) -> float:
        """1.0 inside [PROXIMITY_MIN_DAYS, PROXIMITY_MAX_DAYS]; decays toward the edges. <0 (already past its
        scheduled end but still open) or unknown → a small floor (still watchable, low priority)."""
        if days is None:
            return 0.3
        if days < 0:
            return 0.2
        if days < PROXIMITY_MIN_DAYS:
            return 0.3 + 0.7 * (days / PROXIMITY_MIN_DAYS)  # ramps 0.3→1.0 as it leaves the too-soon zone
        if days <= PROXIMITY_MAX_DAYS:
            return 1.0
        # Beyond the window: gently decay (a 1y-out market still has some, just less, per-day information).
        return max(0.25, 1.0 - (days - PROXIMITY_MAX_DAYS) / 365.0)

    @staticmethod
    def _room_to_move(prob: float | None) -> float:
        """Bernoulli-variance room: 4·p·(1−p) ∈ [0,1], peaks at p=0.5, →0 at the pinned extremes (a market at
        0.99/0.01 has essentially resolved and its probability can no longer move the correlated asset)."""
        if prob is None:
            return 0.0
        p = min(max(prob, 0.0), 1.0)
        return 4.0 * p * (1.0 - p)

    def _score(self, m: dict) -> EventCandidate:
        question = str(m.get("question") or "")
        cid = str(m.get("conditionId") or m.get("id") or "")
        prob = self._yes_prob(m)
        vol24 = float(m.get("volume24hr") or 0.0)
        vol1wk = float(m.get("volume1wk") or 0.0)
        liq = float(m.get("liquidityNum") or m.get("liquidity") or 0.0)
        days = self._days_to_event(m)
        theme = classify_theme(question)
        links = theme.asset_links if theme else ()

        # Attention: a blend of 24h flow (what's hot NOW) and 1wk flow (sustained), log-compressed so a single
        # whale day can't dominate the ranking.
        attention = math.log10(1.0 + vol24) + 0.3 * math.log10(1.0 + vol1wk)
        room = self._room_to_move(prob)
        prox = self._proximity_weight(days)
        mappable = 1.0 if (theme and links) else (0.3 if theme else 0.0)

        components = {
            "attention": round(attention, 3),
            "room_to_move": round(room, 3),
            "proximity": round(prox, 3),
            "mappable": mappable,
            "liquidity": round(liq, 0),
        }

        # Hard exclusions → leverage 0, with a reason (kept in the output for transparency, never silently dropped).
        reason: str | None = None
        if not m.get("enableOrderBook", False):
            reason = "no orderbook"
        elif liq < self.min_liquidity:
            reason = f"thin (<${self.min_liquidity:,.0f} liquidity)"
        elif theme is None:
            reason = "off-theme (not macro/geo/commodity/rates/regulatory)"
        elif theme.key in _NO_LEAD_THEMES:
            reason = "no-lead theme (price-threshold market mechanically follows its asset)"

        leverage = 0.0 if reason else attention * room * prox * mappable
        return EventCandidate(
            question=question, condition_id=cid, yes_token=self._yes_token(m), yes_prob=prob,
            end_date=str(m.get("endDateIso") or m.get("endDate") or "") or None,
            days_to_event=days, volume_24h=vol24, volume_1wk=vol1wk, liquidity=liq,
            theme=theme.key if theme else None, asset_links=links,
            leverage=round(leverage, 4), components=components, excluded_reason=reason,
        )

    def scan(
        self, *, max_per_page: int = 100, pages: int = 3, top_n: int = 10,
    ) -> list[EventCandidate]:
        """Return the top-`top_n` live macro/geo/commodity/rates/regulatory markets by leverage (excluded ones
        have leverage 0 and an `excluded_reason`; they are ranked out, not returned). Deterministic given a fixed
        `_gamma_fetcher` + `now`."""
        raw = self._pull(max_per_page, pages)
        scored = [self._score(m) for m in raw.values()]
        scored.sort(key=lambda c: c.leverage, reverse=True)
        return [c for c in scored if c.leverage > 0][:top_n]


# --------------------------------------------------------------------------- lead/lag measurement


@dataclass(frozen=True)
class LeadLagResult:
    asset: str
    n_common_days: int
    n_paired: int
    corr_by_lag: dict[int, float]  # lag k → corr(Δprob_t, asset_return_{t+k}); k>0 = PM leads, k<0 = asset leads
    best_lag: int | None
    sig_threshold: float  # ≈ 2/sqrt(n_paired): a |corr| below this is indistinguishable from zero at this N
    verdict: str  # LEADS | COINCIDENT | LAGS | NONE | INSUFFICIENT_DATA
    note: str


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 4:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def lead_lag_profile(
    prob_by_date: dict[str, float],
    price_by_date: dict[str, float],
    *,
    asset: str = "asset",
    max_lag: int = 2,
    min_paired: int = 5,
) -> LeadLagResult:
    """The honest 'does the PM move LEAD the asset, or is it already priced?' test.

    Align the two daily series on their common dates, form Δprob_t (day-over-day probability change) and
    asset_return_t (daily log return), then for each lag k ∈ [-max_lag, +max_lag] compute corr(Δprob_t,
    return_{t+k}):
      k = 0  → COINCIDENT (they move together same-day — no latency-free edge)
      k > 0  → PM LEADS the asset (Δprob today predicts the asset's return k days later — the tradeable case)
      k < 0  → asset LEADS PM (PM is the follower — not tradeable)

    Verdict rule (deliberately demanding, because the prior for deep/fast assets is 'already priced'): a tradeable
    LEADS verdict requires the best positive-lag |corr| to (a) clear the ≈2/√n significance threshold AND (b)
    exceed the coincident |corr| by a clear margin. Otherwise the move is COINCIDENT (lag-0 dominates), LAGS
    (a negative lag dominates), or NONE (nothing clears the noise floor).

    ⚠️ DAILY TIMESTAMP CAVEAT — a positive-lag "LEADS" on DAILY data is NOT a tradeable lead until the two
    series' intra-day stamps are reconciled. Polymarket's CLOB daily bucket is stamped at 00:00 UTC (start of
    day, reflecting info through the prior evening), whereas an equity/commodity daily close lands ~20:00 UTC.
    A naive calendar-date join therefore already hands the prediction-market series a ~1-day head start, and a
    lag+1 hit can be that artifact rather than real predictive power. Trust a LEADS verdict only after an HOURLY
    (intra-day) re-run aligns the stamps; on daily data, read LEADS as 'correlation concentrated at lag 0–1,
    direction-consistent, lead UNCONFIRMED'."""
    common = sorted(set(prob_by_date) & set(price_by_date))
    if len(common) < min_paired + 1:
        return LeadLagResult(
            asset=asset, n_common_days=len(common), n_paired=0, corr_by_lag={}, best_lag=None,
            sig_threshold=float("inf"), verdict="INSUFFICIENT_DATA",
            note=f"only {len(common)} common days; need ≥{min_paired + 1}.",
        )
    dprob = [prob_by_date[common[i]] - prob_by_date[common[i - 1]] for i in range(1, len(common))]
    rets = [math.log(price_by_date[common[i]] / price_by_date[common[i - 1]]) for i in range(1, len(common))]
    n = len(dprob)

    corr_by_lag: dict[int, float] = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = dprob[: n - lag], rets[lag:]
        else:
            x, y = dprob[-lag:], rets[: n + lag]
        c = _pearson(x, y)
        if c is not None:
            corr_by_lag[lag] = round(c, 4)

    sig = 2.0 / math.sqrt(n) if n > 0 else float("inf")
    if not corr_by_lag:
        return LeadLagResult(asset, len(common), n, {}, None, sig, "INSUFFICIENT_DATA",
                             "no lag had ≥4 paired observations.")

    best_lag = max(corr_by_lag, key=lambda k: abs(corr_by_lag[k]))
    c0 = abs(corr_by_lag.get(0, 0.0))
    best_pos = max((abs(corr_by_lag[k]) for k in corr_by_lag if k > 0), default=0.0)
    best_neg = max((abs(corr_by_lag[k]) for k in corr_by_lag if k < 0), default=0.0)

    if max(abs(v) for v in corr_by_lag.values()) < sig:
        verdict, note = "NONE", f"no lag clears the ≈{sig:.2f} (2/√{n}) noise floor — undetectable at this N."
    elif best_pos >= sig and best_pos > c0 + sig / 2:
        verdict, note = "LEADS", f"positive-lag |corr|={best_pos:.2f} beats coincident {c0:.2f} — lead UNCONFIRMED on daily data (see timestamp caveat); re-run HOURLY before trusting."
    elif c0 >= best_pos and c0 >= best_neg:
        verdict, note = "COINCIDENT", f"lag-0 |corr|={c0:.2f} dominates — the move is already priced same-day (no latency-free edge)."
    elif best_neg > c0 and best_neg >= best_pos:
        verdict, note = "LAGS", f"a negative lag dominates (|corr|={best_neg:.2f}) — the asset leads the PM; PM is the follower."
    else:
        verdict, note = "COINCIDENT", f"lag-0 |corr|={c0:.2f}; no positive lag clears the bar."

    return LeadLagResult(asset, len(common), n, corr_by_lag, best_lag, round(sig, 4), verdict, note)


__all__ = [
    "AssetLink",
    "EventTheme",
    "EVENT_THEMES",
    "classify_theme",
    "EventCandidate",
    "LiveEventScanner",
    "LeadLagResult",
    "lead_lag_profile",
    "DEFAULT_MIN_LIQUIDITY",
]
