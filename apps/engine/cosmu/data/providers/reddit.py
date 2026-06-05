from __future__ import annotations

import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from ._types import AltDataPoint, _ssl_context


class RedditSentimentProvider:
    """Reddit crowd sentiment from public `hot.json` listings (no auth, free). Market-wide proxy: scans a few
    crypto/markets subreddits, scores each post title with a small bull/bear lexicon, and reduces to ONE value
    in [-1, 1] = (bull - bear) / total. A real-time public feed → available_at == observation time (we know it
    when we read it; no look-ahead). Offline-testable via an injected `_fetcher`. One dead subreddit is swallowed
    (never aborts the read); zero scored posts → [] (honest, never a fabricated 0)."""

    SUBREDDITS = ("cryptocurrency", "bitcoin", "wallstreetbets")
    _BULL = frozenset({
        "moon", "bull", "bullish", "pump", "buy", "buying", "long", "rally", "breakout", "ath",
        "surge", "green", "rip", "hodl", "accumulate", "undervalued", "rocket", "up",
    })
    _BEAR = frozenset({
        "bear", "bearish", "dump", "crash", "sell", "selling", "short", "rug", "rekt", "red",
        "capitulation", "fear", "drop", "overvalued", "scam", "bubble", "down", "puts",
    })

    def __init__(self, subreddits: tuple[str, ...] | None = None, *, post_limit: int = 50, _fetcher: Callable[[str], dict] | None = None) -> None:
        self.subreddits = tuple(subreddits) if subreddits else self.SUBREDDITS
        self.post_limit = post_limit
        self._fetcher = _fetcher or self._fetch

    # Reddit throttles/blocks bare bot UAs (429/empty); its API rules want a descriptive
    # `platform:appid:version (by /u/...)` agent — without this the live read silently yielded nothing.
    _UA = "python:cosmu-engine:0.1 (by /u/cosmu-bot)"

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": self._UA})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            import json
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "reddit_sentiment":
            return []
        bull = bear = total = 0
        for sub in self.subreddits:
            url = f"https://www.reddit.com/r/{sub}/hot.json?{urllib.parse.urlencode({'limit': self.post_limit})}"
            try:
                payload = self._fetcher(url)
            except Exception:  # noqa: BLE001 — one dead subreddit never aborts the read
                continue
            for child in (payload.get("data", {}) or {}).get("children", []) or []:
                title = ((child.get("data", {}) or {}).get("title") or "")
                tokens = set(re.findall(r"[a-z']+", title.lower()))
                if not tokens:
                    continue
                total += 1
                if tokens & self._BULL:
                    bull += 1
                elif tokens & self._BEAR:
                    bear += 1
        if total == 0:
            return []
        score = (bull - bear) / total  # naturally in [-1, 1] since bull, bear <= total
        now = datetime.now(tz=UTC)
        return [AltDataPoint(ts=now, available_at=now, value=score)]
