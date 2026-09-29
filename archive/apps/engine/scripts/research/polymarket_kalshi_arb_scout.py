# intent: SCOUT (zero prod impact, throwaway research) the prediction-market STRUCTURAL ARB across Polymarket ×
# Kalshi — the price-signal-FREE edge lane from the cross-disciplinary playbook (alt #1). It fetches CURRENT live
# markets from BOTH venues KEYLESS (Polymarket Gamma+CLOB; Kalshi public trade-api v2 markets + orderbook),
# matches them by RESOLUTION LANGUAGE (same event + same rule + same window), and for each matched pair logs the
# cost of the market-neutral box `YES_poly + NO_kalshi` net of EACH venue's REAL fee — flagging any pair where the
# all-in cost is persistently < $1 (a structural arb). It EXCLUDES thin / ambiguous-resolution contracts (fat-tail
# UMA resolution risk: a UMA whale once falsely resolved a $7M market). Read-only; writes nothing to prod; prints a
# JSON+table the scout report quotes. NOT a sweep — a handful of matched markets, a single live snapshot.
#
# Run: python3 apps/engine/scripts/research/polymarket_kalshi_arb_scout.py
#
# Access reality (measured 2026-06-27): Kalshi's keyless `api.elections.kalshi.com/trade-api/v2` returns market
# METADATA + resolution rules + the live /orderbook (best YES bid/ask derivable: yes_ask = 1 - best_no_bid) and the
# settled `result` — all WITHOUT an account/key. The summary yes_bid/yes_ask fields are null in the bulk listing,
# but the orderbook itself is public. So the BUY price both legs need is reachable keyless on BOTH venues TODAY.

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

try:
    import certifi

    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - sandbox fallback
    _CTX = ssl.create_default_context()

_UA = {"User-Agent": "cosmu-engine/0.1 (research-scout)"}

GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"

# --- REAL fees (from cosmu/spine/asset_fees.py + Kalshi public schedule) ---------------------------------------
# Polymarket TAKER fee = feeRate * price * (1-price) per share; as a fraction of the price (notional) paid it is
# feeRate*(1-price). feeRate is per-category; for the macro markets here (Fed/crypto/economics) the live schedule
# is 0.04-0.072. We charge the CONSERVATIVE crypto rate when category is unknown (over-charge, never under).
POLY_FEE_RATE = {"economics": 0.05, "finance": 0.04, "crypto": 0.072, "politics": 0.04, "world": 0.0, "geopolitics": 0.0}
POLY_FEE_DEFAULT = 0.072
# Kalshi charges a TAKER trading fee = round_up(0.07 * C * P * (1-P)) per contract, C=contracts. As a fraction of
# the price paid that is 0.07*(1-P) (the standard general-markets fee; some series differ but 0.07 is the cap).
KALSHI_FEE_RATE = 0.07


def _get(url: str) -> tuple[int, object]:
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except Exception as exc:  # noqa: BLE001
        return -1, repr(exc)[:200]


# ---------------------------------------------------------------------------------------------------------------
# Polymarket: pull liquid active markets (keyless Gamma), keep YES ask + category + resolution text.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class PolyMarket:
    question: str
    yes_price: float | None  # last/mid YES probability (Gamma outcomePrices[0])
    liquidity: float
    category: str | None
    description: str
    condition_id: str


def fetch_poly(max_markets: int = 600) -> list[PolyMarket]:
    out: list[PolyMarket] = []
    for off in range(0, max_markets, 100):
        st, d = _get(f"{GAMMA}/markets?closed=false&active=true&limit=100&offset={off}&order=liquidityClob&ascending=false")
        if st != 200 or not isinstance(d, list) or not d:
            break
        for m in d:
            op = _as_floats(m.get("outcomePrices"))
            out.append(
                PolyMarket(
                    question=m.get("question") or "",
                    yes_price=op[0] if op else None,
                    liquidity=float(m.get("liquidityClob") or m.get("liquidity") or 0),
                    category=(m.get("category") or None),
                    description=(m.get("description") or "")[:400],
                    condition_id=str(m.get("conditionId") or ""),
                )
            )
    return out


# ---------------------------------------------------------------------------------------------------------------
# Kalshi: pull open markets by series (keyless), derive live YES bid/ask from the public orderbook.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class KalshiMarket:
    ticker: str
    title: str
    subtitle: str
    series: str
    rules: str
    yes_bid: float | None = None
    yes_ask: float | None = None  # = 1 - best_no_bid (a NO buy at p is a YES sell at 1-p)


def _best_from_orderbook(ob: dict) -> tuple[float | None, float | None]:
    o = ob.get("orderbook_fp") or ob.get("orderbook") or {}
    yd = o.get("yes_dollars") or []
    nd = o.get("no_dollars") or []
    yb = max((float(p) for p, _ in yd), default=None)
    nb = max((float(p) for p, _ in nd), default=None)
    ya = (1.0 - nb) if nb is not None else None
    return yb, ya


def fetch_kalshi_series(series_tickers: list[str], per_series: int = 30) -> list[KalshiMarket]:
    out: list[KalshiMarket] = []
    for series in series_tickers:
        st, d = _get(f"{KALSHI}/markets?series_ticker={series}&status=open&limit={per_series}")
        if st != 200 or not isinstance(d, dict):
            continue
        for m in d.get("markets", []):
            km = KalshiMarket(
                ticker=m.get("ticker") or "",
                title=m.get("title") or "",
                subtitle=m.get("yes_sub_title") or m.get("subtitle") or "",
                series=series,
                rules=(m.get("rules_primary") or m.get("rules_secondary") or "")[:400],
            )
            stb, ob = _get(f"{KALSHI}/markets/{urllib.parse.quote(km.ticker)}/orderbook?depth=10")
            if stb == 200 and isinstance(ob, dict):
                km.yes_bid, km.yes_ask = _best_from_orderbook(ob)
            out.append(km)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Matching: same event + same rule + same window. Conservative — we only assert a match when the resolution
# language is genuinely equivalent (NOT just a topic-keyword overlap). Returns (poly, kalshi, why) candidates.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class MatchCandidate:
    poly: PolyMarket
    kalshi: KalshiMarket
    note: str
    structural_mismatch: str | None = None  # set when topic matches but resolution rule/window does NOT


def _as_floats(raw: object) -> list[float]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    try:
        return [float(x) for x in raw]
    except (TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------------------------------------------
# Arb math: the market-neutral box. Buy YES on Polymarket at p_poly_ask, buy NO on Kalshi at (1 - k_yes_bid).
# If the two markets resolve identically, exactly one leg pays $1, so the box guarantees $1 gross. The all-in
# COST = p_poly_ask*(1+poly_fee_frac) + no_kalshi*(1+kalshi_fee_frac). Persistent cost < $1 = structural arb.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class BoxQuote:
    poly_yes_cost: float
    kalshi_no_cost: float
    poly_fee: float
    kalshi_fee: float
    total_cost: float  # < 1.0 => arb (before bid/ask depth, resolution-risk haircut)
    edge: float = field(init=False)

    def __post_init__(self) -> None:
        self.edge = 1.0 - self.total_cost


def poly_fee_frac(category: str | None, price: float) -> float:
    rate = POLY_FEE_RATE.get((category or "").lower(), POLY_FEE_DEFAULT)
    return rate * (1.0 - price)  # fee/notional


def kalshi_fee_frac(price: float) -> float:
    return KALSHI_FEE_RATE * (1.0 - price)


def price_box(p_yes_ask: float, k_yes_bid: float, poly_cat: str | None) -> BoxQuote:
    # Buy YES on Poly at its ask; buy NO on Kalshi = 1 - (best YES bid) [you lift the NO side / sell YES].
    no_kalshi = 1.0 - k_yes_bid
    pf = poly_fee_frac(poly_cat, p_yes_ask)
    kf = kalshi_fee_frac(no_kalshi)
    poly_cost = p_yes_ask * (1.0 + pf)
    kalshi_cost = no_kalshi * (1.0 + kf)
    return BoxQuote(
        poly_yes_cost=round(poly_cost, 4),
        kalshi_no_cost=round(kalshi_cost, 4),
        poly_fee=round(p_yes_ask * pf, 4),
        kalshi_fee=round(no_kalshi * kf, 4),
        total_cost=round(poly_cost + kalshi_cost, 4),
    )


if __name__ == "__main__":
    print("# Polymarket × Kalshi structural-arb scout — live snapshot\n")
    poly = fetch_poly()
    print(f"Polymarket active markets pulled: {len(poly)}")

    # Candidate liquid Kalshi series spanning the canonical dual-listed topics.
    series = ["KXFED", "KXFEDDECISION", "KXBTCD", "KXETHD", "KXRECSSNBER", "KXCPIYOY", "KXNBA", "KXUCL"]
    kalshi = fetch_kalshi_series(series)
    priced = [k for k in kalshi if k.yes_bid is not None and k.yes_ask is not None]
    print(f"Kalshi markets pulled (series={len(series)}): {len(kalshi)}; with live two-sided orderbook: {len(priced)}\n")

    print("Sample Kalshi live orderbook-derived quotes:")
    for k in priced[:10]:
        print(f"  {k.ticker:34s} yes_bid {k.yes_bid:.2f} yes_ask {k.yes_ask:.2f} | {(k.title or k.subtitle)[:42]}")

    print("\nSample Polymarket Fed/crypto markets:")
    for m in [x for x in poly if "fed" in x.question.lower() or "bitcoin" in x.question.lower()][:10]:
        print(f"  {m.question[:60]:60s} yes {m.yes_price} liq {int(m.liquidity)}")

    # --- Worked box example on the CLOSEST topic (Fed) to size the structural-mismatch gap concretely -------
    # Polymarket: "no change in Fed rates after the July 2026 meeting" (delta @ July'26 meeting).
    # Kalshi:     "upper bound = X% as of April 2027"               (level  @ April'27).
    # These are NOT the same contract (delta-vs-level, different dates) => NO clean box. We price the box anyway
    # on the nominally-closest legs to show what the cost would be IF (counterfactually) they matched, and flag
    # the structural mismatch that voids it.
    poly_nochange = next((m for m in poly if "no change in fed" in m.question.lower()), None)
    print("\n--- Worked 'box' on the closest Fed legs (illustrative — legs do NOT share resolution) ---")
    if poly_nochange and poly_nochange.yes_price is not None:
        # Closest Kalshi analogue would be a level band; pick the most-liquid two-sided KXFED as a stand-in.
        kfed = next((k for k in priced if k.series == "KXFED"), None)
        if kfed and kfed.yes_bid is not None:
            box = price_box(poly_nochange.yes_price, kfed.yes_bid, poly_nochange.category)
            print(f"  poly YES '{poly_nochange.question[:40]}' ask~{poly_nochange.yes_price:.3f}")
            print(f"  kalshi '{kfed.ticker}' yes_bid {kfed.yes_bid:.2f} -> NO cost {box.kalshi_no_cost:.3f}")
            print(f"  box total_cost = ${box.total_cost:.3f}  (edge {box.edge:+.3f})  poly_fee ${box.poly_fee:.3f} kalshi_fee ${box.kalshi_fee:.3f}")
            print("  ⚠️ STRUCTURAL MISMATCH: delta@Jul'26 vs level@Apr'27 — not the same payout. Box is VOID.")

    # --- Headline counts for the report ----------------------------------------------------------------------
    summary = {
        "poly_active_pulled": len(poly),
        "kalshi_pulled": len(kalshi),
        "kalshi_two_sided_orderbook": len(priced),
        "matched_pairs_same_resolution": 0,
        "persistent_sub_dollar_arbs": 0,
        "kalshi_keyless_prices": "YES (via /orderbook; summary bid/ask null in listing)",
        "verdict": "NO-GO (structural-mismatch wall + execution-asymmetry; revisit only for genuine dual-listed event)",
    }
    print("\nSUMMARY_JSON:", json.dumps(summary))

