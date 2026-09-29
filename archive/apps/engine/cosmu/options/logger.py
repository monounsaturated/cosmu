# intent: the FORWARD-ONLY Deribit options logger — the keyless, append-only hoard that makes the fillability
# question answerable AT ALL. The only honest test of an options "inefficiency" is OUR OWN simultaneous top-of-book
# at the instant we'd have acted; you cannot reconstruct that after the fact (Deribit publishes no historical L2),
# so we must capture it live, forward, append-only, never re-pulled. One poll, per currency:
#   1. underlying USD index + the latest DVOL close (the vol regime at capture),
#   2. ONE book_summary call → the WHOLE chain's top-of-book price + mark_iv + OI (cheap, covers the long tail),
#   3. a BOUNDED enrichment: order_book on a selected subset (default = lowest-OI long-tail strikes, the
#      sub-capacity lane) → real best bid/ask SIZES + L2 + greeks, which fillability needs.
# The capture timestamp is stamped HERE (injected clock, default now-UTC) — it is the PIT instant, not any Deribit
# field. Snapshots are append-only to the sink and never overwritten. Bounded by `max_books_per_currency` so a poll
# is a handful of keyless calls (IP-rate-limited), not 870. Propose-only: this module never trades.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cosmu.options.chain import (
    ChainSnapshot,
    OptionQuote,
    enrich_with_order_book,
    parse_book_summary,
)
from cosmu.options.deribit_client import DeribitClient

DEFAULT_CURRENCIES = ("BTC", "ETH")
# How many instruments to ENRICH with a per-instrument order_book per currency. Each is one keyless call; keep it
# small (the long tail is our lane, not the whole 870-strike chain) so a poll stays well inside the IP rate limit.
DEFAULT_MAX_BOOKS = 25


def select_long_tail(quotes: list[OptionQuote], max_books: int) -> list[str]:
    """Default enrichment selection — the LONG TAIL: two-sided quotes with the LOWEST open interest (the
    sub-capacity strikes the latency bots ignore), capped at `max_books`. Returns instrument names. A quote with
    unknown OI sorts last (we prefer strikes we can see liquidity on)."""
    two_sided = [q for q in quotes if q.is_two_sided]
    two_sided.sort(key=lambda q: (q.open_interest if q.open_interest is not None else float("inf")))
    return [q.instrument for q in two_sided[:max_books]]


@dataclass(frozen=True)
class PollResult:
    """One currency's poll outcome: the snapshot built, how many quotes parsed, how many enriched with an order
    book, and how many rows the sink appended."""

    currency: str
    snapshot: ChainSnapshot
    n_quotes: int
    n_enriched: int
    n_written: int


class DeribitOptionsLogger:
    """Polls Deribit's public options API forward and appends each capture to the sink. Inject `clock` for a
    deterministic PIT capture timestamp (tests) and a `select` to choose which instruments get order-book
    enrichment (default: the long tail). `sink` may be None for a dry smoke poll (parse-only, nothing written)."""

    def __init__(
        self,
        client: DeribitClient | None = None,
        sink: object | None = None,
        *,
        currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
        max_books_per_currency: int = DEFAULT_MAX_BOOKS,
        select: Callable[[list[OptionQuote], int], list[str]] = select_long_tail,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client or DeribitClient()
        self.sink = sink
        self.currencies = currencies
        self.max_books = max_books_per_currency
        self.select = select
        self.clock = clock or (lambda: datetime.now(UTC))

    def _latest_dvol(self, currency: str, now: datetime) -> float | None:
        """The most recent DVOL close, fetched over a small trailing window. None if unavailable."""
        end_ms = int(now.timestamp() * 1000)
        start_ms = int((now - timedelta(days=3)).timestamp() * 1000)
        rows = self.client.dvol(currency, start_ms=start_ms, end_ms=end_ms)
        if not rows:
            return None
        last = rows[-1]
        if len(last) >= 5 and isinstance(last[4], (int, float)) and last[4] > 0:
            return float(last[4])
        return None

    def poll_currency(self, currency: str) -> PollResult:
        """Poll ONE currency: index + DVOL + whole-chain book_summary, then enrich the selected subset's order
        books, build the PIT snapshot, and (if a sink is set) append it. Degrades gracefully — a missing piece
        (e.g. DVOL down) yields a snapshot with that field None, never a fabricated value."""
        now = self.clock()
        index = self.client.index_price(currency)
        dvol = self._latest_dvol(currency, now)
        quotes = parse_book_summary(self.client.book_summary(currency), currency=currency)
        targets = set(self.select(quotes, self.max_books)) if quotes else set()
        enriched: list[OptionQuote] = []
        n_enriched = 0
        for q in quotes:
            if q.instrument in targets:
                book = self.client.order_book(q.instrument, depth=5)
                if book:
                    q = enrich_with_order_book(q, book)
                    n_enriched += 1
            enriched.append(q)
        snapshot = ChainSnapshot(
            capture_ts=now, currency=currency.upper(), index_price=index, dvol=dvol, quotes=tuple(enriched),
        )
        n_written = self.sink.append(snapshot) if self.sink is not None else 0  # type: ignore[attr-defined]
        return PollResult(currency.upper(), snapshot, len(enriched), n_enriched, n_written)

    def poll_once(self) -> list[PollResult]:
        """One forward poll across all configured currencies. Returns a PollResult per currency."""
        return [self.poll_currency(c) for c in self.currencies]
