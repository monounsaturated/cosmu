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

    @classmethod
    def from_store(cls, store) -> UniverseCalendar:  # noqa: ANN001 - Store import would be circular
        rows = store.rows("SELECT symbol, listed_at, delisted_at FROM instruments")
        return cls([Listing(symbol=r["symbol"], listed_at=_parse(r["listed_at"]), delisted_at=_parse(r["delisted_at"])) for r in rows])


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
