# intent: the LOCAL entrypoint of the AUTHORITY feature — NOT a cron, NOT on the autonomous tick (this is
# proprietary-data curation the operator drives locally, where the xAI key / Claude-in-Chrome live). Two steps,
# both idempotent: `ingest <dump.json>` parses a data-agnostic dump through the ingest seam and persists the new
# calls; `score` re-scores the whole corpus against the tape and persists the composite scoreboard the dashboard
# serves. invariants: deterministic + offline-safe — an asset with no fetchable bars resolves as no_data (its
# account reads UNTESTED, never a fabricated score); fetching bars is the ONLY network touch and it degrades to
# empty on failure; observe-only — nothing here funds or fires an order. `python3 -m cosmu.authority.run score`.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.authority.ingest import parse_calls
from cosmu.authority.models import PricePoint
from cosmu.authority.scoring import DEFAULT_HORIZON_DAYS
from cosmu.authority.store import (
    build_scoreboard,
    load_calls,
    persist_calls,
    persist_scoreboard,
    prices_from_bars,
)
from cosmu.knowledge.store import Store

# Crypto asset → reference venue symbol for the tape. Non-crypto assets (equities, FX) have no mapping here yet;
# their calls resolve as no_data until an equity/FX reference is wired (named, never guessed). Extend as needed.
DEFAULT_ASSET_SYMBOL: dict[str, str] = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT", "ADA": "ADAUSDT", "AVAX": "AVAXUSDT", "LINK": "LINKUSDT", "DOT": "DOTUSDT",
    "LTC": "LTCUSDT", "MATIC": "MATICUSDT", "TON": "TONUSDT", "TRX": "TRXUSDT",
}


def _tape_for_assets(assets: set[str], *, asset_symbol: dict[str, str], limit: int = 400) -> dict[str, list[PricePoint]]:
    """Daily-bar tape per asset via the reference provider, adapted to PricePoints. Offline-safe: an unmapped or
    unfetchable asset is omitted (its calls resolve no_data → the account reads UNTESTED, never guessed)."""
    from cosmu.data.market import default_crypto_reference

    provider = default_crypto_reference()
    bars_by_asset: dict[str, list] = {}
    for asset in sorted(assets):
        symbol = asset_symbol.get(asset)
        if symbol is None:
            continue
        try:
            bars = provider.fetch_bars(symbol, "1d", limit=limit)
        except Exception:  # noqa: BLE001 — offline / throttled: this asset is no_data this pass
            bars = []
        if bars:
            bars_by_asset[asset] = bars
    return prices_from_bars(bars_by_asset)


def ingest_dump(store: Store, text: str, *, source: str = "json") -> int:
    """Parse a data-agnostic dump (JSON string) and persist the new calls. Returns rows written."""
    calls = parse_calls(text, source=source)
    return persist_calls(store, calls)


def score(
    store: Store,
    *,
    asset_symbol: dict[str, str] | None = None,
    now: datetime | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> int:
    """Re-score the whole corpus against the live tape and persist the scoreboard. Returns accounts scored."""
    now = now or datetime.now(tz=UTC)
    assets = {c.asset for c in load_calls(store)}
    tape = _tape_for_assets(assets, asset_symbol=asset_symbol or DEFAULT_ASSET_SYMBOL)
    scores = build_scoreboard(store, tape, now=now, horizon_days=horizon_days)
    return persist_scoreboard(store, scores)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from cosmu.config.settings import get_settings

    parser = argparse.ArgumentParser(description="Authority feature — local ingest + score (observe-only).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ingest = sub.add_parser("ingest", help="parse a JSON dump and persist the new calls")
    p_ingest.add_argument("path", help="path to a JSON dump of account calls")
    sub.add_parser("score", help="re-score the corpus against the tape and persist the scoreboard")
    args = parser.parse_args(argv)

    store = Store(get_settings())
    if args.cmd == "ingest":
        with open(args.path, encoding="utf-8") as fh:
            written = ingest_dump(store, fh.read())
        print(f"AUTHORITY INGEST — {written} new call(s) persisted from {args.path}")
        return 0
    scored = score(store)
    print(f"AUTHORITY SCORE — {scored} account(s) scored and persisted to the scoreboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
