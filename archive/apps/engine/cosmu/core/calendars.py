# intent: per-asset-class trading calendars so the four classes resample to one daily baseline correctly;
# inputs: an asset class (+ optional holiday set / active window); outputs: which UTC days are sessions and which
# session a timestamp belongs to; invariants: calendars are pure/deterministic and decide the daily-bar grid every
# class shares — crypto/prediction trade 24/7, FX runs the Sun→Fri week, equities follow the exchange weekday calendar.

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol, runtime_checkable

from cosmu.core.interfaces import AssetClass


@runtime_checkable
class TradingCalendar(Protocol):
    def is_session(self, day: date) -> bool:
        """True if `day` (UTC) is a trading session that emits a daily bar."""

    def session_of(self, ts: datetime) -> date:
        """The session date a timestamp belongs to: its own date if a session, else the most recent prior session."""

    def sessions(self, start: date, end: date) -> list[date]:
        """All session dates in [start, end] inclusive — the daily resample grid."""


class _BaseCalendar:
    def session_of(self, ts: datetime) -> date:
        day = ts.astimezone(UTC).date() if ts.tzinfo else ts.date()
        # Roll back to the most recent session so a weekend/holiday print folds into the prior daily bar.
        for _ in range(8):  # 7 days back covers any weekend+holiday run we model here
            if self.is_session(day):  # type: ignore[attr-defined]
                return day
            day -= timedelta(days=1)
        return day

    def sessions(self, start: date, end: date) -> list[date]:
        out: list[date] = []
        day = start
        while day <= end:
            if self.is_session(day):  # type: ignore[attr-defined]
                out.append(day)
            day += timedelta(days=1)
        return out


class CryptoCalendar(_BaseCalendar):
    """24/7 — every UTC day is a session."""

    def is_session(self, day: date) -> bool:
        return True


class PredictionCalendar(_BaseCalendar):
    """Prediction markets trade continuously while open; resolution/expiry is enforced by the universe
    (Instrument.delisted_at), so the calendar itself is 24/7 like crypto."""

    def is_session(self, day: date) -> bool:
        return True


class FxCalendar(_BaseCalendar):
    """The FX week runs Sunday 22:00 UTC → Friday 22:00 UTC. For the daily baseline we count Monday–Friday
    as sessions (weekend prints fold back into Friday via session_of)."""

    def is_session(self, day: date) -> bool:
        return day.weekday() < 5  # Mon=0 .. Fri=4


class EquityCalendar(_BaseCalendar):
    """Exchange weekday calendar minus holidays. Holidays are injected (a full market calendar via
    pandas-market-calendars is deferred); default empty = weekdays only."""

    def __init__(self, holidays: set[date] | None = None) -> None:
        self._holidays = holidays or set()

    def is_session(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self._holidays


_DEFAULT: dict[AssetClass, TradingCalendar] = {
    AssetClass.CRYPTO: CryptoCalendar(),
    AssetClass.PREDICTION: PredictionCalendar(),
    AssetClass.FX: FxCalendar(),
    AssetClass.EQUITY: EquityCalendar(),
}


def calendar_for(asset_class: AssetClass, *, holidays: set[date] | None = None) -> TradingCalendar:
    """The trading calendar for an asset class. `holidays` only applies to equities."""
    if asset_class is AssetClass.EQUITY and holidays is not None:
        return EquityCalendar(holidays)
    return _DEFAULT[asset_class]
