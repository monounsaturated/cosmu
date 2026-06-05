from __future__ import annotations

from ._types import AltDataPoint, NewsItem


class FixtureAltDataProvider:
    """Deterministic synthetic provider so the gate builds and tests run with no key/network."""

    def __init__(self, series: dict[tuple[str, str], list[AltDataPoint]]) -> None:
        self.series = series
        self.calls: list[tuple[str, str, int]] = []

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        self.calls.append((symbol, metric, limit))
        return self.series.get((symbol, metric), [])[-limit:]


class FixtureNewsProvider:
    """Deterministic offline headlines so the gate + tests run with no key/network."""

    def __init__(self, news: dict[str, list[NewsItem]]) -> None:
        self.news = news
        self.calls: list[tuple[str, int]] = []

    def fetch_news(self, symbol: str, *, limit: int) -> list[NewsItem]:
        self.calls.append((symbol, limit))
        return self.news.get(symbol, [])[-limit:]
