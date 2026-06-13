# The fee-optimizing venue router: "know where to send". For a base asset it compares every venue that lists
# it and picks the cheapest LEGAL one (jurisdiction-aware). These tests pin the base-asset normalization
# (incl. the XBT→BTC Kraken alias), the cheapest-pick, the legality + live-wiring filters, and the volume-tier
# effect. Pure planning — no money path, fully offline (catalog fees, no store).

from __future__ import annotations

from cosmu.spine.fee_router import base_asset, best_venue, fee_matrix, routes_for
from cosmu.spine.venue import default_catalog

CAT = default_catalog()


def test_base_asset_normalizes_across_venue_symbologies():
    assert base_asset("BTCUSDT") == "BTC"          # binance
    assert base_asset("BTC-USDT") == "BTC"          # okx spot
    assert base_asset("BTC-USDT-SWAP") == "BTC"     # okx perp
    assert base_asset("BTC/USD") == "BTC"           # kraken
    assert base_asset("PF_XBTUSD") == "BTC"         # kraken futures (XBT alias)
    assert base_asset("BTC") == "BTC"               # hyperliquid
    assert base_asset("ETH-USDT-SWAP") == "ETH"


def test_best_venue_picks_cheapest_legal_for_a_french_resident():
    r = best_venue(CAT, "BTC", side="taker", jurisdiction="FR")
    assert r is not None and r.venue_id == "hyperliquid" and r.fee_bps == 4.5  # cheapest taker, FR-legal
    # XBT alias means Kraken Futures' BTC perp is now in the comparison set
    venues = {row.venue_id for row in routes_for(CAT, "BTC", jurisdiction="FR")}
    assert {"hyperliquid", "binance", "kraken_futures"} <= venues


def test_legality_filter_excludes_jurisdiction_restricted_venues():
    # BNB is only on Binance (restricted in the US) → no legal venue for a US resident, one for FR.
    assert best_venue(CAT, "BNB", jurisdiction="US") is None
    fr = best_venue(CAT, "BNB", jurisdiction="FR")
    assert fr is not None and fr.venue_id == "binance"


def test_require_live_filters_to_exec_wired_venues():
    # Without require_live the cheapest BTC venue is Hyperliquid (no exec adapter yet); with it, only
    # exec-wired venues (binance/kraken/coinbase) qualify → Binance is the cheapest of those.
    assert best_venue(CAT, "BTC", require_live=False).venue_id == "hyperliquid"
    live = best_venue(CAT, "BTC", require_live=True)
    assert live is not None and live.venue_id == "binance" and live.live_wired


def test_volume_tier_lowers_the_fee():
    base = best_venue(CAT, "ETH", side="maker", volume_30d=0).fee_bps
    whale = best_venue(CAT, "ETH", side="maker", volume_30d=200_000_000).fee_bps
    assert whale < base  # high 30d volume reaches a cheaper maker tier (Kraken Futures rebate / HL discount)


def test_fee_matrix_reports_best_per_asset():
    m = fee_matrix(CAT, ["BTC", "ETH", "BNB"], jurisdiction="FR")
    assert m["BTC"]["best"] == "hyperliquid" and m["BTC"]["best_fee_bps"] == 4.5
    assert m["BNB"]["best"] == "binance"
    assert "hyperliquid" in m["ETH"]["by_venue"] and "binance" in m["ETH"]["by_venue"]
