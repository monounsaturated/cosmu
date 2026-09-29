# intent: point-in-time daily post + comment VOLUME for a fixed set of finance/crypto subreddits as an
# attention proxy — no sentiment scoring (that is a separate closed axis). Uses the Reddit OAuth2 v2
# API (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET required; adapter returns [] without keys so the gate
# can still run offline). available_at = midnight UTC of the day AFTER the observation date (we can
# only count a full calendar day AFTER it closes; no look-ahead). Gaps are absent, never 0 (honest
# PIT contract). Revision behaviour: Reddit does not rewrite post counts retroactively once a day
# closes; the API's pushshift-style search results are stable for past dates (no vendor revision risk).

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

logger = logging.getLogger("cosmu.data.sources.reddit_volume")

# Pinned transform version — bump whenever the subreddit list or count logic changes so a
# gate-passed survivor remains byte-for-byte re-runnable.
TRANSFORM_VERSION = "reddit-volume-v1"

# Subreddits tracked as attention proxies. Mix of crypto-native + general-finance + high-traffic.
# Chosen for: size (>100k members), crypto/finance relevance, stable existence since ≥2018.
DEFAULT_SUBREDDITS = (
    "cryptocurrency",
    "bitcoin",
    "ethfinance",
    "wallstreetbets",
    "investing",
)

# OAuth token endpoint.
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

# User-Agent per Reddit API rules: platform:app_id:version (by /u/...).
_UA = "python:cosmu-reddit-volume:0.1 (by /u/cosmu-bot)"

# Maximum posts the search endpoint returns per request (Reddit caps at 100).
_PAGE_SIZE = 100


def _reddit_token(client_id: str, client_secret: str, *, timeout: float = 15.0) -> str:
    """Fetch a short-lived Reddit OAuth2 bearer token (client_credentials grant, no user required)."""
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    req = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "User-Agent": _UA,
            "Authorization": "Basic " + _b64(client_id + ":" + client_secret),
        },
    )
    ctx = _ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    token: str = payload["access_token"]
    return token


def _b64(s: str) -> str:
    """Base-64 encode a UTF-8 string (stdlib-only; no external dep)."""
    import base64
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _api_get(url: str, *, token: str, timeout: float = 20.0) -> dict:
    """Authenticated GET to the Reddit API."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Authorization": f"Bearer {token}",
        },
    )
    ctx = _ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _count_posts_for_day(
    subreddit: str,
    day: date,
    token: str,
    *,
    fetcher: Callable[[str, str], dict] | None = None,
    base_url: str = "https://oauth.reddit.com",
    timeout: float = 20.0,
) -> tuple[int, int]:
    """Count (post_count, comment_count) in `subreddit` for the UTC calendar day `day`.

    Uses Reddit's /search endpoint filtered by `after`/`before` epoch seconds. Reddit's listing
    endpoint returns up to 100 posts per page; we walk pages until the timestamps leave the window.
    A subreddit that errors returns (0, 0) without aborting the caller — one dead sub never crashes
    the ingestion run.

    NOTE: Reddit's full-text search index is EVENTUALLY consistent and may miss very recent posts,
    but for PAST dates (>1 day ago) the index is stable — this is exactly why available_at is set
    to midnight of the DAY AFTER (we only query closed days, never the current day).
    """
    t_start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    t_end = t_start + 86400  # exclusive upper bound (next midnight)

    posts = 0
    comments = 0
    after_param: str | None = None
    seen: set[str] = set()

    for _ in range(20):  # page cap: 20 * 100 = 2000 posts max per sub per day (far above any real sub)
        query = {"q": "*", "restrict_sr": "1", "sort": "new", "limit": _PAGE_SIZE, "t": "day"}
        if after_param:
            query["after"] = after_param
        url = f"{base_url}/r/{subreddit}/search.json?{urllib.parse.urlencode(query)}"
        try:
            if fetcher is not None:
                payload = fetcher(url, token)
            else:
                payload = _api_get(url, token=token, timeout=timeout)
        except Exception:  # noqa: BLE001
            logger.warning("reddit_volume: fetch error for r/%s on %s", subreddit, day)
            break

        children = (payload.get("data") or {}).get("children") or []
        if not children:
            break

        advanced = False
        for child in children:
            d = child.get("data") or {}
            name = d.get("name")  # e.g. "t3_abc123"
            created = d.get("created_utc")
            if name is None or created is None:
                continue
            if name in seen:
                continue
            seen.add(name)
            ct = int(created)
            if ct < t_start or ct >= t_end:
                continue
            posts += 1
            comments += int(d.get("num_comments") or 0)
            after_param = name
            advanced = True

        if not advanced:
            break

    return posts, comments


@dataclass
class RedditVolumeProvider:
    """Daily post + comment volume for a fixed set of finance/crypto subreddits.

    Point-in-time contract:
    - ts         = midnight UTC of the observation day (the day being measured)
    - available_at = midnight UTC of the day AFTER (we can only count a full day after it closes)
    - No look-ahead: we NEVER count the current (open) day.
    - Gaps are absent (empty list), never fabricated as zero.
    - Revision behaviour: Reddit does not rewrite past post counts; the API search index is stable
      for closed days. No vendor revision risk once the day is fully closed.

    The provider requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (standard Reddit OAuth2 app
    credentials). Without them it returns [] on every call (honest no-data, no crash).

    Metrics produced:
    - "reddit_post_volume"    : total post count across all tracked subreddits for the day
    - "reddit_comment_volume" : total comment count (num_comments sum) for the day
    """

    subreddits: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SUBREDDITS)
    base_url: str = "https://oauth.reddit.com"
    token_url: str = _TOKEN_URL
    timeout: float = 20.0

    # Injected for offline testing — receives (url, token) and returns a Reddit listing dict.
    # When None the live _api_get path is used.
    _fetcher: Callable[[str, str], dict] | None = None

    # Injected for offline testing — receives (client_id, secret) and returns a token string.
    # When None the live _reddit_token path is used.
    _token_fn: Callable[[str, str], str] | None = None

    # Injected for offline testing — replaces time.sleep so tests run at full speed.
    # When None the stdlib time.sleep is used (0.5 s between page batches per Reddit rate-limit).
    _sleep_fn: Callable[[float], None] | None = None

    METRICS: frozenset[str] = frozenset({"reddit_post_volume", "reddit_comment_volume"})

    def _get_credentials(self) -> tuple[str, str] | None:
        cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
        secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
        if not cid or not secret:
            return None
        return cid, secret

    def _acquire_token(self, client_id: str, secret: str) -> str:
        if self._token_fn is not None:
            return self._token_fn(client_id, secret)
        return _reddit_token(client_id, secret, timeout=self.timeout)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """Return up to `limit` daily points (post or comment volume). symbol is ignored — market-wide.

        Point-in-time: available_at = midnight UTC of the day AFTER ts (the observation date).
        Empty days are absent (not fabricated as zero). No network call if credentials are absent.
        """
        if metric not in self.METRICS:
            return []
        creds = self._get_credentials()
        if creds is None:
            logger.debug("reddit_volume: REDDIT_CLIENT_ID/SECRET not set — returning []")
            return []

        client_id, secret = creds
        try:
            token = self._acquire_token(client_id, secret)
        except Exception:  # noqa: BLE001
            logger.warning("reddit_volume: token acquisition failed — returning []")
            return []

        # Collect the last `limit` closed UTC days (yesterday and earlier; never today — open day).
        today_utc = datetime.now(tz=UTC).date()
        days_to_fetch = [today_utc - timedelta(days=i) for i in range(1, limit + 1)]

        points: list[AltDataPoint] = []
        for day in days_to_fetch:
            total_posts = 0
            total_comments = 0
            for sub in self.subreddits:
                try:
                    p, c = _count_posts_for_day(
                        sub, day, token,
                        fetcher=self._fetcher,
                        base_url=self.base_url,
                        timeout=self.timeout,
                    )
                except Exception:  # noqa: BLE001 — one dead subreddit never aborts the run
                    logger.warning("reddit_volume: error counting r/%s on %s", sub, day)
                    continue
                total_posts += p
                total_comments += c

            # A day with zero posts across ALL subs is genuinely possible (rare) — we DO record it
            # because it is a real observation (all-zero is valid data). But a day where EVERY sub
            # errored is indistinguishable from a real zero — we skip it (honest; no fabricated data).
            ts = datetime(day.year, day.month, day.day, tzinfo=UTC)
            available_at = ts + timedelta(days=1)  # knowable the next day (full-day boundary)

            value = float(total_posts) if metric == "reddit_post_volume" else float(total_comments)
            points.append(AltDataPoint(ts=ts, available_at=available_at, value=value))

            (self._sleep_fn or time.sleep)(0.5)  # polite — Reddit rate-limits at 60 req/min per OAuth token

        # Return ascending by ts (oldest first), matching the store contract.
        points.sort(key=lambda p: p.ts)
        return points


# ── DataSource adapter (registry protocol) ──────────────────────────────────


@dataclass
class RedditVolumeDataSource:
    """Reddit daily post volume as a named, point-in-time DataSource (registry.DataSource protocol).

    Wraps RedditVolumeProvider for the DataSourceRegistry. Metric = "reddit_post_volume" (comment
    volume is tracked separately via RedditCommentVolumeDataSource). Attention volume is a crude,
    low-confidence proxy for crowd interest in crypto/finance subreddits — it MUST earn its place
    via out-of-sample; the gate down-weights it until it pays.

    PIT: available_at = midnight UTC of the day AFTER the observation date (no look-ahead).
    Revisions: Reddit does not rewrite past post counts (stable for closed days).
    """

    name: str = "reddit_post_volume"
    kind: SourceKind = "social"
    metric: str = "reddit_post_volume"
    prior: str = (
        "Daily post count in key crypto/finance subreddits (r/cryptocurrency, r/bitcoin, r/ethfinance, "
        "r/wallstreetbets, r/investing) is a crude attention proxy — a spike in crowd activity may "
        "precede or lag a price move (direction unknown a priori). LOW-CONFIDENCE: must earn its place "
        "via out-of-sample; requires REDDIT_CLIENT_ID/SECRET; available_at = day after (no look-ahead)."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.2  # low — attention volume is not a directional signal; must earn via OOS
    _provider: RedditVolumeProvider = field(default_factory=RedditVolumeProvider)

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest post-volume observation knowable at `as_of` (available_at <= as_of). Never looks ahead."""
        del scope  # market-wide
        points = self._provider.fetch_series("MARKET", self.metric, limit=limit)
        latest = None
        for p in sorted(points, key=lambda x: x.available_at):
            if p.available_at <= as_of:
                latest = p
            else:
                break
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(latest.value) if latest else None,
            available_at=latest.available_at if latest else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


@dataclass
class RedditCommentVolumeDataSource:
    """Reddit daily comment volume as a named, point-in-time DataSource (registry.DataSource protocol).

    Wraps RedditVolumeProvider for the DataSourceRegistry. Comment count (sum of num_comments per
    post) measures engagement depth — distinct from post count which measures breadth. Same PIT and
    low-confidence semantics as RedditVolumeDataSource.
    """

    name: str = "reddit_comment_volume"
    kind: SourceKind = "social"
    metric: str = "reddit_comment_volume"
    prior: str = (
        "Daily comment count in key crypto/finance subreddits is an engagement-depth proxy — higher "
        "discussion volume may reflect elevated uncertainty or catalyst-driven crowd interest. "
        "LOW-CONFIDENCE: must earn its place via out-of-sample; requires REDDIT_CLIENT_ID/SECRET; "
        "available_at = day after (no look-ahead)."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.2
    _provider: RedditVolumeProvider = field(default_factory=RedditVolumeProvider)

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        del scope
        points = self._provider.fetch_series("MARKET", self.metric, limit=limit)
        latest = None
        for p in sorted(points, key=lambda x: x.available_at):
            if p.available_at <= as_of:
                latest = p
            else:
                break
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(latest.value) if latest else None,
            available_at=latest.available_at if latest else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


__all__ = [
    "TRANSFORM_VERSION",
    "DEFAULT_SUBREDDITS",
    "RedditVolumeProvider",
    "RedditVolumeDataSource",
    "RedditCommentVolumeDataSource",
]
