# intent: a point-in-time RSS headline COUNT source — free, stdlib+feedparser-optional, no LLM, no scoring.
# For each topic/ticker watched, counts how many headlines from a curated set of public RSS feeds were
# PUBLISHED within a trailing window ending at `as_of`.  PIT: every item's available_at == item.published
# (the feed's own publication timestamp — when it was KNOWABLE).  A gap is absent (value=None), not a zero.
# No revision risk: we only read append-only feed items; the count aggregates what exists at fetch time.
# Offline/CI: parses the bundled XML fixture (no network).  LLM-free: counts only.

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Callable

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Frozen transform version — bump if the count window or topic-match logic changes.
TRANSFORM_VERSION = "rss-news-count-v1"

# --- Default feed catalogue (public RSS, no key) ---
# Scope → list of feed URLs fetched for that scope.  "MARKET" feeds cover broad crypto/finance.
# Per-ticker scopes fall back to topic-search in titles from the MARKET feeds.
_DEFAULT_FEEDS: dict[str, list[str]] = {
    "MARKET": [
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
        "https://feeds.feedburner.com/CoinDesk",
    ],
    "BTC": [
        "https://news.bitcoin.com/feed/",
    ],
}

# Default trailing window for headline counting (in seconds).
_DEFAULT_WINDOW_SECONDS = 86_400  # 24 h

# Topic keywords for MARKET-scope counting.  A headline matches a topic if ANY keyword appears
# (case-insensitive).  The count per topic is the number of matching headlines.
_DEFAULT_TOPICS: dict[str, list[str]] = {
    "crypto_market": ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain"],
    "regulation": ["sec", "regulation", "ban", "law", "enforcement", "compliance"],
    "macro_risk": ["inflation", "recession", "fed", "rate", "tariff", "geopolitical"],
}

# A minimal deterministic offline fixture: two RSS <channel> feeds in standard RSS 2.0 format,
# covering two feeds/topics.  Tests parse THIS instead of hitting the network.  `pubDate` uses
# RFC 2822 format (same as real RSS).
_FIXTURE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CoinTelegraph</title>
    <item>
      <title>Bitcoin rallies as SEC issues new crypto ruling</title>
      <pubDate>Sat, 01 Jun 2024 10:00:00 +0000</pubDate>
      <link>https://cointelegraph.com/news/btc-rally</link>
    </item>
    <item>
      <title>Ethereum ETF approval boosts market sentiment</title>
      <pubDate>Sat, 01 Jun 2024 11:30:00 +0000</pubDate>
      <link>https://cointelegraph.com/news/eth-etf</link>
    </item>
    <item>
      <title>Fed holds rates steady; crypto unaffected</title>
      <pubDate>Sat, 01 Jun 2024 14:00:00 +0000</pubDate>
      <link>https://cointelegraph.com/news/fed-rates</link>
    </item>
    <item>
      <title>Old news article outside the window</title>
      <pubDate>Mon, 27 May 2024 06:00:00 +0000</pubDate>
      <link>https://cointelegraph.com/news/old</link>
    </item>
  </channel>
</rss>
"""

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_pubdate(raw: str) -> datetime | None:
    """Parse an RSS pubDate (RFC 2822) to a UTC-aware datetime.  Returns None if unparseable.
    The publication timestamp is the PIT marker — it is when the item was KNOWABLE."""
    try:
        return parsedate_to_datetime(raw).astimezone(UTC)
    except Exception:  # noqa: BLE001
        return None


def _parse_rss_items(xml_text: str) -> list[datetime]:
    """Return the publication times of all <item> elements in an RSS 2.0 XML string.
    Items without a parseable <pubDate> are silently skipped (gap, not zero)."""
    times: list[datetime] = []
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 — local / fixture XML, not user input
    except ET.ParseError:
        return times
    for item in root.iter("item"):
        pub = item.findtext("pubDate") or item.findtext("published") or ""
        ts = _parse_pubdate(pub.strip())
        if ts is not None:
            times.append(ts)
    return times


def _count_items_in_window(
    pub_times: list[datetime],
    as_of: datetime,
    window_seconds: int,
) -> int:
    """Count items published in (as_of - window, as_of].
    PIT: only items whose pubDate <= as_of are considered — no look-ahead.
    A gap (no items in window) → 0, which the caller converts to None for absence."""
    earliest = as_of - timedelta(seconds=window_seconds)
    return sum(1 for t in pub_times if earliest < t <= as_of)


def _topic_counts(
    pub_times_with_titles: list[tuple[datetime, str]],
    topics: dict[str, list[str]],
    as_of: datetime,
    window_seconds: int,
) -> dict[str, int]:
    """Per-topic headline counts within the window.  A headline matches a topic if ANY keyword
    appears (case-insensitive) in the title.  PIT: only items with pubDate <= as_of are counted."""
    earliest = as_of - timedelta(seconds=window_seconds)
    in_window = [(t, title) for t, title in pub_times_with_titles if earliest < t <= as_of]
    result: dict[str, int] = {}
    for topic, keywords in topics.items():
        pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
        result[topic] = sum(1 for _, title in in_window if pattern.search(title))
    return result


def _parse_rss_items_with_titles(xml_text: str) -> list[tuple[datetime, str]]:
    """Parse (pubDate, title) pairs from RSS 2.0 XML.  Items without parseable pubDate skipped."""
    pairs: list[tuple[datetime, str]] = []
    try:
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError:
        return pairs
    for item in root.iter("item"):
        pub = item.findtext("pubDate") or item.findtext("published") or ""
        ts = _parse_pubdate(pub.strip())
        title = (item.findtext("title") or "").strip()
        if ts is not None and title:
            pairs.append((ts, title))
    return pairs


# ---------------------------------------------------------------------------
# HTTP helper (stdlib-only; feedparser optional)
# ---------------------------------------------------------------------------


def _fetch_url(url: str, timeout: float = 15.0) -> str:
    """Fetch a URL and return the body as a string.  Uses stdlib only (no feedparser required).
    Any error returns "" — the caller treats this as a gap (no items), not a crash."""
    import ssl
    import urllib.request

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="replace")
    except Exception:  # noqa: BLE001 — RSS is best-effort; a feed failure → gap, not crash
        return ""


# ---------------------------------------------------------------------------
# Data source class
# ---------------------------------------------------------------------------


@dataclass
class RssNewsCountSource:
    """Public RSS feeds → daily headline COUNT per topic/ticker, point-in-time.

    PIT contract:
    - available_at == each item's RSS pubDate (when it was KNOWABLE — the feed's own publication time).
    - We count items published in (as_of - window, as_of] — no look-ahead.
    - A gap (no fetchable items in window) → value=None.  NEVER synthesizes a zero to fill a gap.
    - Revision behaviour: RSS feeds are append-only by convention; we do NOT rewrite history.

    The source is LLM-free and produces raw counts only (no scoring, no sentiment).  Low-confidence
    (tier1) — must earn its place via out-of-sample; the gate down-weights until it pays.

    Offline/CI: when `offline=True` or the fetcher is injected, the bundled XML fixture is parsed
    so no network call is made.  CI always passes `offline=True`.
    """

    name: str = "rss_news_count"
    kind: SourceKind = "sentiment"
    metric: str = "rss_news_count"
    prior: str = (
        "Daily headline count from public RSS feeds (CoinTelegraph, Decrypt, CoinDesk, news.bitcoin.com). "
        "A surge in raw headline volume may precede or coincide with major price moves — LOW-CONFIDENCE "
        "(counts ≠ sentiment); must earn its place via out-of-sample.  LLM-free: counts only."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.20  # deliberately low — raw headline count is noisy
    feeds: dict[str, list[str]] = field(default_factory=lambda: dict(_DEFAULT_FEEDS))
    topics: dict[str, list[str]] = field(default_factory=lambda: dict(_DEFAULT_TOPICS))
    window_seconds: int = _DEFAULT_WINDOW_SECONDS
    offline: bool = False
    # Injected fetcher for tests: (url: str) -> xml_str.  None → real HTTP fetch.
    _fetcher: Callable[[str], str] | None = field(default=None, repr=False)

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _get_xml(self, url: str) -> str:
        """Fetch one feed URL.  Offline → return the fixture; live → real HTTP."""
        if self.offline:
            return _FIXTURE_XML
        if self._fetcher is not None:
            return self._fetcher(url)
        return _fetch_url(url)

    def _fetch_pairs(self, scope: str) -> list[tuple[datetime, str]]:
        """Aggregate (pubDate, title) pairs from all feeds applicable to `scope`.
        Deduplicated by (ts, title) to avoid double-counting across overlapping feeds."""
        feed_urls = self.feeds.get(scope) or self.feeds.get("MARKET") or []
        seen: set[tuple[datetime, str]] = set()
        pairs: list[tuple[datetime, str]] = []
        for url in feed_urls:
            xml_text = self._get_xml(url)
            for ts, title in _parse_rss_items_with_titles(xml_text):
                key = (ts, title)
                if key not in seen:
                    seen.add(key)
                    pairs.append((ts, title))
        return pairs

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Count headlines from RSS feeds knowable at `as_of`.

        Returns the TOTAL count of unique headlines published in (as_of - window, as_of] across all
        configured feeds for `scope`.  If no items exist in that window, value=None (gap, not zero).
        available_at == as_of (the count is knowable as soon as the feed is fetched — no lag added).

        `limit` is part of the DataSource protocol; not meaningful for a count aggregation.
        """
        del limit  # not used for an aggregated count
        pairs = self._fetch_pairs(scope)
        total = _count_items_in_window([t for t, _ in pairs], as_of, self.window_seconds)
        value: float | None = float(total) if total > 0 else None
        return SourceFeature(
            name=self.name,
            scope=scope,
            as_of=as_of,
            value=value,
            available_at=as_of if value is not None else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    def query_topics(
        self,
        scope: str,
        as_of: datetime,
    ) -> dict[str, SourceFeature]:
        """Per-topic headline counts for the same window.  Returns one SourceFeature per topic.
        Topics with zero matching headlines → value=None (gap).  Useful for finer-grained features."""
        pairs = self._fetch_pairs(scope)
        counts = _topic_counts(pairs, self.topics, as_of, self.window_seconds)
        result: dict[str, SourceFeature] = {}
        for topic, count in counts.items():
            result[topic] = SourceFeature(
                name=f"{self.name}_{topic}",
                scope=scope,
                as_of=as_of,
                value=float(count) if count > 0 else None,
                available_at=as_of if count > 0 else None,
                confidence=self.confidence,
                transform_version=self.transform_version,
                prior=f"[{topic}] " + self.prior,
                low_confidence=self.low_confidence,
            )
        return result
