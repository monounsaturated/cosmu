# intent: the typed, immutable option-chain model + parsers that turn Deribit's raw public JSON into PIT-stamped
# quotes the scanner reasons over. ONE OptionQuote per listed instrument; ONE ChainSnapshot per poll (carrying the
# capture timestamp WE stamp, the underlying index, and DVOL). Two layers of fidelity, matching the client:
#   - parse_book_summary(): the cheap whole-chain layer — top-of-book bid/ask PRICE (coin), mark_iv, OI. No SIZES,
#       no greeks (book_summary does not publish them). Enough for the price-only static-no-arb campers.
#   - enrich_with_order_book(): the focused layer — splices best bid/ask SIZE, full L2 ladders, and greeks from a
#       per-instrument get_order_book onto a quote. Needed for the FILLABILITY check (you can't size a fill
#       without the resting size at the touch).
# invariants: prices are COIN-denominated exactly as Deribit publishes them (× index_price → USD); a contract is 1
# unit of the underlying coin, so `size` is in contracts == coin units. Nothing is fabricated — a missing/None
# field stays None (the camper/fillability layer treats None as 'unknown', never 0). All dataclasses frozen.

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

# DDMMMYY month tokens Deribit uses in instrument names (BTC-25DEC26-58000-C).
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_instrument(name: str) -> tuple[str, date, float, bool] | None:
    """Parse a Deribit option instrument name `CCY-DDMMMYY-STRIKE-{C|P}` → (currency, expiry, strike, is_call).
    Returns None for a non-option name (perp/future) or any malformed token — the caller skips it (never guesses)."""
    parts = name.split("-")
    if len(parts) != 4:
        return None
    ccy, expiry_s, strike_s, kind = parts
    if kind not in ("C", "P"):
        return None
    mon = _MONTHS.get(expiry_s[-5:-2].upper()) if len(expiry_s) >= 5 else None
    if mon is None:
        return None
    try:
        day = int(expiry_s[: len(expiry_s) - 5])
        year = 2000 + int(expiry_s[-2:])
        strike = float(strike_s)
    except ValueError:
        return None
    try:
        expiry = date(year, mon, day)
    except ValueError:
        return None
    return ccy.upper(), expiry, strike, kind == "C"


@dataclass(frozen=True)
class OptionQuote:
    """One instrument's quote at capture. PRICES are COIN-denominated (Deribit's native unit); multiply by the
    snapshot's `index_price` for USD. `bid_size`/`ask_size` are the resting size AT the touch in contracts (==
    coin units), None until enriched from an order book. `greeks` is None until enriched. `l2_bids`/`l2_asks` are
    ascending-priority (price, size) ladders, empty until enriched."""

    instrument: str
    currency: str
    expiry: date
    strike: float
    is_call: bool
    bid_price: float | None
    ask_price: float | None
    mark_price: float | None
    mark_iv: float | None  # percent, e.g. 45.23
    open_interest: float | None
    volume: float | None
    underlying_price: float | None  # the per-expiry forward Deribit reports for this instrument (USD)
    # enriched (order book) — None/empty until enrich_with_order_book:
    bid_size: float | None = None
    ask_size: float | None = None
    greeks: dict[str, float] | None = None
    l2_bids: tuple[tuple[float, float], ...] = ()
    l2_asks: tuple[tuple[float, float], ...] = ()

    @property
    def mid_price(self) -> float | None:
        """Two-sided mid in COIN, or None if either side is unquoted (a one-sided book has no honest mid)."""
        if self.bid_price is None or self.ask_price is None:
            return None
        return (self.bid_price + self.ask_price) / 2.0

    @property
    def spread(self) -> float | None:
        """Absolute bid-ask spread in COIN, or None if one-sided."""
        if self.bid_price is None or self.ask_price is None:
            return None
        return self.ask_price - self.bid_price

    @property
    def is_two_sided(self) -> bool:
        return self.bid_price is not None and self.ask_price is not None


def _f(value: object) -> float | None:
    """Coerce a JSON number to float, or None for null/non-numeric/zero-bid placeholders (Deribit sends 0.0 for an
    EMPTY side; we keep 0.0 only where it is a real price — callers treat None as 'no quote')."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parse_book_summary(
    rows: list[dict],
    *,
    currency: str,
) -> list[OptionQuote]:
    """Turn a get_book_summary_by_currency(kind=option) result into OptionQuotes (top-of-book PRICE layer only —
    no sizes/greeks). Non-option / malformed names are skipped. A side priced 0.0/None is recorded as None (an
    unquoted side), so mid/spread stay honest. Ascending by (expiry, strike, is_call)."""
    out: list[OptionQuote] = []
    for r in rows:
        name = r.get("instrument_name")
        if not isinstance(name, str):
            continue
        parsed = parse_instrument(name)
        if parsed is None or parsed[0] != currency.upper():
            continue
        _, expiry, strike, is_call = parsed
        bid = _f(r.get("bid_price"))
        ask = _f(r.get("ask_price"))
        out.append(
            OptionQuote(
                instrument=name,
                currency=currency.upper(),
                expiry=expiry,
                strike=strike,
                is_call=is_call,
                bid_price=bid if (bid is None or bid > 0) else None,
                ask_price=ask if (ask is None or ask > 0) else None,
                mark_price=_f(r.get("mark_price")),
                mark_iv=_f(r.get("mark_iv")),
                open_interest=_f(r.get("open_interest")),
                volume=_f(r.get("volume")),
                underlying_price=_f(r.get("underlying_price")),
            )
        )
    out.sort(key=lambda q: (q.expiry, q.strike, q.is_call))
    return out


def _ladder(rows: object) -> tuple[tuple[float, float], ...]:
    """Coerce a get_order_book bids/asks payload ([[price, size], ...]) into a tuple of (price, size) floats."""
    if not isinstance(rows, list):
        return ()
    out: list[tuple[float, float]] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            px, sz = _f(row[0]), _f(row[1])
            if px is not None and sz is not None:
                out.append((px, sz))
    return tuple(out)


def enrich_with_order_book(quote: OptionQuote, book: dict) -> OptionQuote:
    """Return a copy of `quote` with best bid/ask SIZE, L2 ladders, greeks, and (fresher) top-of-book prices
    spliced from a get_order_book result. The order book is the authoritative top-of-book at capture; when it
    carries a best price we prefer it over the (possibly staler) book_summary price. Pure (no network)."""
    if not book:
        return quote
    bids = _ladder(book.get("bids"))
    asks = _ladder(book.get("asks"))
    greeks_raw = book.get("greeks")
    greeks = {k: float(v) for k, v in greeks_raw.items() if isinstance(v, (int, float))} \
        if isinstance(greeks_raw, dict) else None
    best_bid = _f(book.get("best_bid_price"))
    best_ask = _f(book.get("best_ask_price"))
    return replace(
        quote,
        bid_price=best_bid if (best_bid is not None and best_bid > 0) else quote.bid_price,
        ask_price=best_ask if (best_ask is not None and best_ask > 0) else quote.ask_price,
        bid_size=_f(book.get("best_bid_amount")),
        ask_size=_f(book.get("best_ask_amount")),
        greeks=greeks,
        l2_bids=bids,
        l2_asks=asks,
    )


@dataclass(frozen=True)
class ChainSnapshot:
    """One poll of one currency's option chain. `capture_ts` is the PIT instant WE observed it (stamped by the
    logger, NOT a Deribit field) — the only honest time for forward research. `index_price` is the underlying USD
    index at capture; `dvol` is the 30d implied-vol index value (None if unavailable). `quotes` are ascending by
    (expiry, strike, is_call). This object is the sole input to the scanner."""

    capture_ts: datetime
    currency: str
    index_price: float | None
    dvol: float | None
    quotes: tuple[OptionQuote, ...] = field(default_factory=tuple)

    def two_sided(self) -> list[OptionQuote]:
        """Quotes with BOTH a bid and an ask (the only ones with an honest mid/spread)."""
        return [q for q in self.quotes if q.is_two_sided]

    def by_instrument(self) -> dict[str, OptionQuote]:
        return {q.instrument: q for q in self.quotes}

    @property
    def asof_iso(self) -> str:
        ts = self.capture_ts if self.capture_ts.tzinfo else self.capture_ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC).isoformat()
