# intent: the LOCAL entrypoint of the AUTHORITY feature — NOT a cron, NOT on the autonomous tick (this is
# proprietary-data curation the operator drives locally, where the xAI key / Claude-in-Chrome live). Two steps,
# both idempotent: `ingest <dump.json>` parses a data-agnostic dump through the ingest seam and persists the new
# calls; `score` re-scores the whole corpus against the tape and persists the composite scoreboard the dashboard
# serves. invariants: deterministic + offline-safe — an asset with no fetchable bars resolves as no_data (its
# account reads UNTESTED, never a fabricated score); fetching bars is the ONLY network touch and it degrades to
# empty on failure; observe-only — nothing here funds or fires an order. `python3 -m cosmu.authority.run score`.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.authority.assets import CRYPTO_SYMBOLS, build_tape
from cosmu.authority.ingest import parse_calls
from cosmu.authority.models import PricePoint
from cosmu.authority.scoring import DEFAULT_HORIZON_DAYS
from cosmu.authority.store import (
    build_scoreboard,
    load_calls,
    persist_calls,
    persist_scoreboard,
)
from cosmu.knowledge.store import Store

# Back-compat alias: the crypto asset → reference venue symbol map now lives in cosmu.authority.assets (alongside
# the equity/commodity maps + the router). Re-exported here under the original name for any caller that imported it.
DEFAULT_ASSET_SYMBOL = CRYPTO_SYMBOLS


class _FallbackProvider:
    """Try each provider in order, returning the first NON-EMPTY bar set. Used to resolve equity/commodity assets
    against FREE Stooq bars first, falling back to Yahoo when Stooq lists nothing — offline-safe (each provider
    already degrades to empty, so the chain degrades to empty, never raises)."""

    def __init__(self, providers: list) -> None:
        self._providers = providers

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list:
        for provider in self._providers:
            try:
                bars = provider.fetch_bars(symbol, timeframe, limit=limit)
            except Exception:  # noqa: BLE001 — this provider is offline/blocked for this symbol; try the next
                bars = []
            if bars:
                return bars
        return []


def _equity_reference():
    """The free equity/commodity reference: Stooq daily CSV (primary), Yahoo chart API (fallback). Both keyless +
    survivorship-biased (discovery-grade, declared) and both degrade to their cache / empty offline."""
    from cosmu.data.market import StooqDailyBarsProvider, YahooDailyBarsProvider

    return _FallbackProvider([StooqDailyBarsProvider(), YahooDailyBarsProvider()])


def _tape_for_assets(
    assets: set[str], *, asset_symbol: dict[str, str] | None = None, limit: int = 400
) -> dict[str, list[PricePoint]]:
    """Daily-bar tape per asset, routed by asset class (crypto via the keyless crypto reference; equities &
    commodities via the free Stooq/Yahoo reference — see cosmu.authority.assets.build_tape). Offline-safe: an
    unmapped or unfetchable asset is omitted (no_data → the account reads UNTESTED, never guessed)."""
    from cosmu.data.market import default_crypto_reference

    return build_tape(
        assets,
        crypto_provider=default_crypto_reference(),
        equity_provider=_equity_reference(),
        limit=limit,
        crypto_symbol_override=asset_symbol,
    )


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
    """Re-score the whole corpus against the live tape and persist the scoreboard. The tape is now MULTI-ASSET —
    crypto, equities and commodities all resolve (see _tape_for_assets); `asset_symbol`, when given, pins/extends
    the crypto symbol map (None → the built-in crypto + equity/commodity maps). Returns accounts scored."""
    now = now or datetime.now(tz=UTC)
    assets = {c.asset for c in load_calls(store)}
    tape = _tape_for_assets(assets, asset_symbol=asset_symbol)
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
