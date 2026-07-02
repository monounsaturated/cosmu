# Hermetic tests for the Polymarket→correlated-asset machinery (cosmu.research.polymarket_correlation):
#   - classify_theme routing (oil / rates / crypto-price / off-theme)
#   - LiveEventScanner ranking + the hard exclusions (thin / no-orderbook / off-theme / no-lead theme), all with
#     an injected Gamma fetcher + a frozen `now` so days-to-event is deterministic
#   - lead_lag_profile: the COINCIDENT vs LEADS vs INSUFFICIENT_DATA verdicts on constructed series
# No network: the Gamma fetcher is injected and the price/prob series are built in-test.

from __future__ import annotations

import math
from datetime import UTC, datetime

from cosmu.research.polymarket_correlation import (
    EVENT_THEMES,
    LeadLagResult,
    LiveEventScanner,
    classify_theme,
    lead_lag_profile,
)

# --------------------------------------------------------------------------- theme routing


def test_classify_theme_routes_specific_cause_first():
    assert classify_theme("Strait of Hormuz traffic returns to normal by July 31?").key == "oil_geopolitics"
    assert classify_theme("Will the Fed increase interest rates by 25 bps after the July meeting?").key == "us_rates"
    assert classify_theme("Will Bitcoin be above $56,000 on June 30?").key == "crypto_price"
    # Iran lands on oil (most-specific) not the broad geopolitics bucket, because oil_themes are ordered first.
    assert classify_theme("Iran leadership change by June 30?").key == "oil_geopolitics"
    # A pure conflict market with no oil keyword falls to the broad geopolitics bucket.
    assert classify_theme("Putin out as President of Russia by December 31?").key == "geopolitics_broad"
    # Off-theme (sports) → None.
    assert classify_theme("Will Paraguay win the 2026 FIFA World Cup?") is None


def test_themes_have_sources_for_every_asset_link():
    # Trust heuristic: every mapped asset must carry a (reputable) citation — no un-sourced mechanism ships.
    for theme in EVENT_THEMES:
        for link in theme.asset_links:
            assert link.source.strip(), f"{theme.key}/{link.asset} missing a source"
            assert link.direction in ("inverse", "same")


# --------------------------------------------------------------------------- scanner

_NOW = datetime(2026, 6, 30, tzinfo=UTC)


def _mkt(**kw) -> dict:
    base = {
        "conditionId": kw.get("cid", "0xCID"),
        "question": "q",
        "outcomePrices": "[\"0.40\", \"0.60\"]",
        "clobTokenIds": "[\"yes_tok\", \"no_tok\"]",
        "endDateIso": "2026-07-30",
        "volume24hr": 100_000.0,
        "volume1wk": 500_000.0,
        "liquidityNum": 300_000.0,
        "enableOrderBook": True,
        "active": True,
        "closed": False,
    }
    base.update(kw)
    return base


def _scanner(markets: list[dict]) -> LiveEventScanner:
    # One-page fetcher: the first order/offset returns everything, the rest return [] (deduped by cid anyway).
    def fetcher(url: str):
        return markets if "offset=0" in url and "order=volume24hr" in url else []

    return LiveEventScanner(_gamma_fetcher=fetcher, now=lambda: _NOW)


def test_scanner_ranks_mappable_macro_market_top_and_excludes_the_rest():
    markets = [
        _mkt(cid="hormuz", question="Strait of Hormuz traffic returns to normal by July 31?",
             outcomePrices="[\"0.375\", \"0.625\"]"),
        _mkt(cid="btc", question="Will Bitcoin be above $56,000 on June 30?",
             outcomePrices="[\"0.99\", \"0.01\"]"),
        _mkt(cid="sport", question="Will Paraguay win the 2026 FIFA World Cup?"),
        _mkt(cid="thin", question="Fed rate cut by July?", liquidityNum=500.0),
        _mkt(cid="nobook", question="Fed rate hike by July?", enableOrderBook=False),
    ]
    out = _scanner(markets).scan(top_n=10)
    # Only the Hormuz market is mappable + liquid + orderbook + on-theme → it's the sole survivor with leverage>0.
    assert [c.condition_id for c in out] == ["hormuz"]
    top = out[0]
    assert top.theme == "oil_geopolitics"
    assert top.asset_links and top.asset_links[0].direction == "inverse"
    assert top.days_to_event is not None and 29 < top.days_to_event < 31  # 2026-07-30 minus 2026-06-30


def test_scanner_exclusion_reasons_are_explicit():
    markets = [
        _mkt(cid="btc", question="Will Bitcoin be above $56,000 on June 30?"),
        _mkt(cid="sport", question="Will Paraguay win the 2026 FIFA World Cup?"),
        _mkt(cid="thin", question="Fed rate cut by July?", liquidityNum=500.0),
        _mkt(cid="nobook", question="Fed rate hike by July?", enableOrderBook=False),
    ]
    by_cid = {c.condition_id: c for c in (_scanner(markets)._score(m) for m in markets)}
    assert by_cid["btc"].excluded_reason and "no-lead" in by_cid["btc"].excluded_reason
    assert "off-theme" in by_cid["sport"].excluded_reason
    assert "thin" in by_cid["thin"].excluded_reason
    assert "orderbook" in by_cid["nobook"].excluded_reason
    assert all(c.leverage == 0.0 for c in by_cid.values())


def test_room_to_move_penalises_pinned_extremes():
    s = _scanner([])
    # Two identical oil markets but one is pinned near-resolved (0.99) and one is uncertain (0.5).
    mid = s._score(_mkt(question="Hormuz oil", outcomePrices="[\"0.50\", \"0.50\"]"))
    pinned = s._score(_mkt(question="Hormuz oil", outcomePrices="[\"0.99\", \"0.01\"]"))
    assert mid.leverage > pinned.leverage
    assert mid.components["room_to_move"] > pinned.components["room_to_move"]


def test_proximity_weight_window():
    s = _scanner([])
    assert s._proximity_weight(30.0) == 1.0          # inside the window
    assert s._proximity_weight(1.0) < 1.0            # too soon to trade
    assert s._proximity_weight(400.0) < 1.0          # too far out
    assert 0.0 < s._proximity_weight(None) < 1.0     # unknown end → small floor


# --------------------------------------------------------------------------- lead/lag


def _lcg(n: int, seed: int = 12345) -> list[float]:
    """Deterministic pseudo-random increments with ~0 serial autocorrelation, so a constructed lag-0 (coincident)
    or lag-1 (lead) relationship separates cleanly from the other lags."""
    out, x = [], seed
    for _ in range(n):
        x = (1103515245 * x + 12345) % (2**31)
        out.append((x / (2**31) - 0.5) * 0.04)  # centered, scale ~0.02
    return out


def _build(dprob: list[float], ret: list[float]) -> tuple[dict[str, float], dict[str, float]]:
    """Turn (Δprob, return) increment sequences into dated prob/price level series (one calendar day apart)."""
    prob: dict[str, float] = {}
    price: dict[str, float] = {}
    p, px = 0.5, 100.0
    base = datetime(2026, 5, 1, tzinfo=UTC)
    from datetime import timedelta
    for i in range(len(dprob) + 1):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        prob[d] = p
        price[d] = px
        if i < len(dprob):
            p = min(max(p + dprob[i], 0.02), 0.98)
            px = px * math.exp(ret[i])
    return prob, price


def test_lead_lag_detects_coincident():
    dprob = _lcg(30)
    ret = [-2.0 * d for d in dprob]  # asset reacts the SAME day as the probability moves (lag 0)
    prob, price = _build(dprob, ret)
    res = lead_lag_profile(prob, price, asset="WTI")
    assert isinstance(res, LeadLagResult)
    assert res.verdict == "COINCIDENT"
    assert res.best_lag == 0
    assert abs(res.corr_by_lag[0]) > abs(res.corr_by_lag.get(1, 0.0))


def test_lead_lag_detects_tradeable_lead():
    dprob = _lcg(30, seed=999)
    # asset moves the day AFTER the probability change: ret_{t+1} = -2·Δprob_t  ⇒  PM leads by one day.
    ret = [0.0] + [-2.0 * dprob[i] for i in range(len(dprob) - 1)]
    prob, price = _build(dprob, ret)
    res = lead_lag_profile(prob, price, asset="WTI")
    assert res.verdict == "LEADS"
    assert res.best_lag == 1


def test_lead_lag_insufficient_data():
    prob = {"2026-06-01": 0.5, "2026-06-02": 0.6}
    price = {"2026-06-01": 100.0, "2026-06-02": 101.0}
    res = lead_lag_profile(prob, price, asset="WTI", min_paired=5)
    assert res.verdict == "INSUFFICIENT_DATA"
    assert res.n_paired == 0


def test_lead_lag_aligns_on_common_dates_only():
    # prob has an extra weekend day the price series lacks; only the intersection is used.
    dprob = _lcg(20)
    ret = [-2.0 * d for d in dprob]
    prob, price = _build(dprob, ret)
    prob["2026-09-09"] = 0.5  # orphan date with no matching price
    res = lead_lag_profile(prob, price, asset="WTI")
    assert res.n_common_days == 21  # the orphan is dropped, 21 original days remain
