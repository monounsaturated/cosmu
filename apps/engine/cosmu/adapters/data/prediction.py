# intent: the prediction-market DataAdapter — Polymarket public CLOB odds behind core.DataAdapter; inputs: a set of
# markets (token ids) + injected odds reader; outputs: core Instruments/Bars/Features where the "price" is the
# implied probability in [0,1]; invariants: odds-as-data ONLY (no execution in this pass), point-in-time
# (a quote known at its own time, no lag), and resolution/expiry lives in delisted_at so a RESOLVED market is
# absent from universe(as_of) afterwards (the prediction-market analogue of survivorship/look-ahead safety).

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from cosmu.adapters.data.crypto import AltReader
from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument

_VENUE = "polymarket"
_PROVIDER = "polymarket"


@dataclass(frozen=True)
class Market:
    """One prediction market. `token` is the CLOB token id whose odds series we read; `listed_at`/`resolves_at`
    bound when it is tradable — after resolution it leaves the universe (no resolved-market look-ahead)."""

    symbol: str
    token: str
    listed_at: datetime | None = None
    resolves_at: datetime | None = None


def instrument_id(symbol: str) -> str:
    return f"prediction:{_VENUE}:{symbol}"


class PredictionDataAdapter:
    """Polymarket odds (long the YES side; a 'down' view is the opposite token, so direction stays in {-1,0,+1}
    per core.Signal). The tradable level is the probability itself, so each daily Bar's OHLC carries the odds."""

    asset_class = AssetClass.PREDICTION

    def __init__(self, markets: list[Market], *, alt_reader: AltReader | None = None, metric: str = "odds") -> None:
        self._markets = {m.symbol: m for m in markets}
        self._alt = alt_reader
        self._metric = metric

    def universe(self, as_of: datetime) -> list[Instrument]:
        out: list[Instrument] = []
        for m in self._markets.values():
            if m.listed_at is not None and as_of < m.listed_at:
                continue
            if m.resolves_at is not None and as_of >= m.resolves_at:  # resolved → gone (expiry safety)
                continue
            out.append(
                Instrument(
                    id=instrument_id(m.symbol), symbol=m.symbol, asset_class=AssetClass.PREDICTION, venue=_VENUE,
                    tick_size=Decimal("0.001"), lot_size=Decimal("1"), min_notional=Decimal("1"),
                    quote_ccy="USDC", listed_at=m.listed_at, delisted_at=m.resolves_at,
                )
            )
        return out

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        if self._alt is None:
            return []
        symbol = instrument_id.rsplit(":", 1)[-1]
        market = self._markets.get(symbol)
        if market is None:
            return []
        out: list[Bar] = []
        for p in self._alt.read_asof(_PROVIDER, market.token, self._metric, end):
            if not (start <= p.ts <= end):
                continue
            odds = Decimal(str(p.value))  # the share price IS the probability in [0,1]
            out.append(
                Bar(
                    instrument_id=instrument_id, ts=p.ts, interval=interval,
                    open=odds, high=odds, low=odds, close=odds, volume=Decimal("0"),
                    available_at=p.available_at,  # CLOB quotes are known at quote time (no lag)
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        if self._alt is None:
            return []
        symbol = instrument_id.rsplit(":", 1)[-1]
        market = self._markets.get(symbol)
        if market is None:
            return []
        out: list[Feature] = []
        for p in self._alt.read_asof(_PROVIDER, market.token, self._metric, as_of):
            out.append(
                Feature(
                    name="odds", instrument_id=instrument_id, ts=p.ts, available_at=p.available_at,
                    value=float(p.value), transform_version="pm-riskon-v1",
                )
            )
        return out


__all__ = ["Market", "PredictionDataAdapter", "instrument_id"]
