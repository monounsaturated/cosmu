# intent: a CATALOG-ONLY IBKR DataAdapter stub — IBKR is wired in the venue catalog (real fees + jurisdiction)
# but we hold no IBKR account/data feed yet, so this adapter honestly returns nothing rather than faking bars;
# inputs: none (no feed); outputs: empty universe/bars/features; invariants: same core.DataAdapter contract as
# every class, point-in-time honest (empty is not look-ahead), and it NEVER fabricates a bar/feature. Equity
# research today flows through EquityDataAdapter (free Stooq bars); swap this for a real feed when an account
# exists. No execution path here — going live is a separate ExecutionAdapter, off the LLM/tool path.

from __future__ import annotations

from datetime import datetime

from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument


class IbkrDataAdapter:
    """Research-only placeholder for IBKR equities. Returns empty results until a real IBKR market-data feed
    is connected (no account yet). Satisfies the DataAdapter protocol so the venue can be referenced without
    a live feed, and so the lab shows an honest 'no data yet' instead of a fabricated series."""

    asset_class = AssetClass.EQUITY
    # IBKR's free path here lists no instruments — we have no feed, so coverage is declared empty (not hidden).
    survivorship_complete = False

    def universe(self, as_of: datetime) -> list[Instrument]:
        return []

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        return []

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        return []
