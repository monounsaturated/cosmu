# intent: point-in-time tradable-universe membership so backtests never see survivorship bias; inputs: instrument listing/delisting dates or bar history; outputs: the set of symbols actually tradable at time t; invariants: a symbol is eligible only while listed, liquid, and with enough history — never the current liquid set projected backwards.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cosmu.data.market import Bar


@dataclass(frozen=True)
class Listing:
    symbol: str
    listed_at: datetime | None = None
    delisted_at: datetime | None = None


class UniverseCalendar:
    """Which symbols were tradable at a given instant. The whole point is that a coin which pumped
    then died is *present* before its delisting and *absent* after — excluding it everywhere (the
    current-survivors set) is the classic crypto survivorship bias that inflates every backtest."""

    def __init__(self, listings: list[Listing]) -> None:
        self._listings = list(listings)

    def eligible(self, at: datetime) -> list[str]:
        out: list[str] = []
        for listing in self._listings:
            if listing.listed_at is not None and at < listing.listed_at:
                continue
            if listing.delisted_at is not None and at >= listing.delisted_at:
                continue
            out.append(listing.symbol)
        return sorted(out)

    def is_eligible(self, symbol: str, at: datetime) -> bool:
        return symbol in set(self.eligible(at))

    def window_for(self, symbol: str) -> tuple[datetime | None, datetime | None] | None:
        """The (listed_at, delisted_at) eligibility window for one symbol, resolved ONCE — for trimming a whole bar
        series without the per-bar O(N) `is_eligible` set rebuild. Collapses across the symbol's listings to the
        WIDEST listed-to-delisted span (earliest listing, latest delisting; a None bound stays None = open). None
        when the symbol has no listing at all (caller treats as 'unknown' → no trim, never trim-to-empty)."""
        listed: datetime | None = None
        delisted: datetime | None = None
        found = False
        for listing in self._listings:
            if listing.symbol != symbol:
                continue
            found = True
            if listing.listed_at is not None:
                listed = listing.listed_at if listed is None else min(listed, listing.listed_at)
            else:
                listed = None  # an open-start listing widens the window to the beginning
            if listing.delisted_at is not None:
                delisted = listing.delisted_at if delisted is None else max(delisted, listing.delisted_at)
            else:
                delisted = None  # an open-end listing keeps the window live
        return (listed, delisted) if found else None

    @classmethod
    def from_store(cls, store) -> UniverseCalendar:  # noqa: ANN001 - Store import would be circular
        rows = store.rows("SELECT symbol, listed_at, delisted_at FROM instruments")
        return cls([Listing(symbol=r["symbol"], listed_at=_parse(r["listed_at"]), delisted_at=_parse(r["delisted_at"])) for r in rows])

    @classmethod
    def from_universe_pairs(cls, store, *, venue: str | None = None, asset_class: str | None = None):  # noqa: ANN001
        """PIT calendar from the BROAD venue-tagged `universe_pairs` table (the survivorship superset — includes
        delisted rows backfilled from Binance Vision), not the small `instruments` catalog. Optionally scope to a
        venue/asset_class so a per-venue backtest gets that venue's listed-at-time set. Returns an EMPTY calendar
        (every queried symbol eligible) when the table is absent/unpopulated, so a fresh store never crashes."""
        where = ["1=1"]
        params: list[str] = []
        if venue is not None:
            where.append("venue = ?")
            params.append(venue)
        if asset_class is not None:
            where.append("asset_class = ?")
            params.append(asset_class)
        sql = f"SELECT symbol, listed_at, delisted_at FROM universe_pairs WHERE {' AND '.join(where)}"
        try:
            rows = store.rows(sql, tuple(params))
        except Exception:  # noqa: BLE001 — table not yet created → empty calendar (nothing excluded)
            rows = []
        return cls([
            Listing(symbol=r["symbol"], listed_at=_parse(r["listed_at"]), delisted_at=_parse(r["delisted_at"]))
            for r in rows
        ])


def eligible_from_bars(
    market: dict[str, list[Bar]],
    at: datetime,
    *,
    min_bars: int = 80,
    min_quote_volume: float = 0.0,
) -> list[str]:
    """Fallback eligibility from raw bars: a symbol qualifies at `at` only if it already had
    `min_bars` of history and met the liquidity floor by then — derived, not assumed."""
    out: list[str] = []
    for symbol, bars in market.items():
        prior = [bar for bar in bars if bar.ts <= at]
        if len(prior) < min_bars:
            continue
        recent = prior[-1]
        quote_volume = float(recent.volume) * float(recent.close)
        if quote_volume < min_quote_volume:
            continue
        out.append(symbol)
    return sorted(out)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
