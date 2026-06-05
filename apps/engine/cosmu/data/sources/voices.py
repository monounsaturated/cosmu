# intent: PHASE 0 of "PageRank for credibility" — the raw INGEST seam for a single voice's timeline across
# X (xAI/Grok LiveSearch), Reddit (public JSON API), and RSS/Atom (Substack/newsletters/news). It pulls a
# handle's recent posts as point-in-time-stamped raw TEXT (VoicePost), nothing more: no claim extraction
# (Phase 1, LLM), no outcome resolution (Phase 2, deterministic), no authority ranking (Phase 3). Keeping
# Phase 0 to "fetch + stamp + store, append-only" means the credibility pipeline is fed by one honest,
# replayable source of raw timelines.
#
# Invariants (mirror the altdata.py house style):
#   * KEY-GATED / honest degradation: no key or a dead fetch yields [] — never a fabricated post.
#   * Point-in-time: `ts` is the post's creation time (for Phase-3 primacy / who-said-it-first); `available_at`
#     is when WE would have known it — the scrape/read time. We never back-date availability to the post's own
#     timestamp (that manufactures look-ahead); a backfill of old posts is honestly "available now".
#   * Append-only store, deduped by (platform, handle, post_id) so re-running ingest never double-counts.
#   * Offline-testable: every live provider takes an injected `_fetcher` (or `offline=True` fixtures), so the
#     whole module runs in CI with no key and no network.
#
# The LLM (xAI/Grok) is used ONLY to RETRIEVE X posts here (X has no free timeline API); it does not score,
# rank, or touch the money path. Structured claim extraction is deliberately deferred to Phase 1.

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

# Bump if the VoicePost schema or any provider's extraction convention changes, so a downstream
# (Phase 1+) artifact built on these timelines stays reproducible (mirrors xai_twitter's TRANSFORM_VERSION).
VOICES_TRANSFORM_VERSION = "voices-ingest-v1"

# Default lookback for a first-run Phase-0 historical backfill. Long enough to seed the authority
# ranker with ≥1 claim-resolution cycle before the Gate evaluates the strategy OOS.
VOICES_BACKFILL_DAYS = 365

_XAI_BASE_URL = "https://api.x.ai/v1"
_XAI_MODEL = "grok-3-mini"  # cheap LiveSearch retrieval; the LLM only fetches text, never scores


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context so HTTPS works on hosts without system CA certs (sandbox, slim images)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _now(now: datetime | None) -> datetime:
    """Resolve the read-time used for `available_at`. Injectable so tests are deterministic."""
    return now if now is not None else datetime.now(tz=UTC)


def _stable_id(platform: str, handle: str, text: str, ts: datetime) -> str:
    """Deterministic fallback post id when the source gives none — a content hash so the same post
    dedups to the same row across re-runs (never collides a handle's two distinct posts at the same ts)."""
    digest = hashlib.sha1(f"{platform}|{handle}|{ts.isoformat()}|{text}".encode()).hexdigest()
    return f"{platform[:2]}_{digest[:16]}"


@dataclass(frozen=True)
class VoicePost:
    """One raw post from one voice's timeline — the atom Phase 1 extracts claims from.

    `ts` is the post's creation time (drives Phase-3 primacy). `available_at` is when we'd have known it
    (the read/scrape time) — the point-in-time stamp that bounds look-ahead. `post_id` is unique within a
    (platform, handle); `url` is provenance for the audit trail."""

    platform: str  # "x" | "reddit" | "rss"
    handle: str  # the voice (e.g. "@someone", "u/someone", a feed slug)
    post_id: str
    text: str
    ts: datetime
    available_at: datetime
    url: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "handle": self.handle,
            "post_id": self.post_id,
            "text": self.text,
            "ts": self.ts.isoformat(),
            "available_at": self.available_at.isoformat(),
            "url": self.url,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> VoicePost:
        return cls(
            platform=row["platform"],
            handle=row["handle"],
            post_id=str(row["post_id"]),
            text=row.get("text", "") or "",
            ts=datetime.fromisoformat(row["ts"]),
            available_at=datetime.fromisoformat(row["available_at"]),
            url=row.get("url", "") or "",
        )


class VoiceTimelineProvider(Protocol):
    """The Phase-0 seam: pull one voice's recent posts as raw, point-in-time-stamped text."""

    platform: str

    def fetch_timeline(self, handle: str, *, limit: int) -> list[VoicePost]:
        """Return ascending-by-ts VoicePosts for `handle`, or [] (honest degradation) on no key / dead fetch."""


# ---------------------------------------------------------------------------
# Append-only, point-in-time store (mirrors AltDataStore: one JSONL per platform/handle)
# ---------------------------------------------------------------------------


class VoiceTimelineStore:
    """Append-only, point-in-time timeline store. One JSONL file per (platform, handle); each append is an
    immutable line. Dedups by `post_id` on read (a re-ingest of the same post is a no-op downstream — the
    LATEST appended copy wins, so an edited post's newer text supersedes the old). `read_asof` filters to
    `available_at <= as_of` so a post scraped later can never appear in an earlier point-in-time view."""

    def __init__(self, root: Path | str = ".cosmu/voices") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, platform: str, handle: str) -> Path:
        safe = f"{platform}_{handle}".replace("/", "_").replace("@", "").replace("\\", "_").replace(" ", "_")
        return self.root / f"{safe}.jsonl"

    def append(self, posts: list[VoicePost]) -> int:
        """Append posts grouped by their (platform, handle). Returns the number of rows written."""
        if not posts:
            return 0
        by_file: dict[Path, list[VoicePost]] = {}
        for p in posts:
            by_file.setdefault(self._path(p.platform, p.handle), []).append(p)
        written = 0
        for path, group in by_file.items():
            with path.open("a") as fh:
                for p in group:
                    fh.write(json.dumps(p.to_row()) + "\n")
                    written += 1
        return written

    def _read_rows(self, platform: str, handle: str) -> list[dict[str, Any]]:
        path = self._path(platform, handle)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:  # one malformed row never aborts the read
                continue
        return rows

    def read_all(self, platform: str, handle: str) -> list[VoicePost]:
        """Every distinct post (deduped by post_id, latest append wins), ascending by ts."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self._read_rows(platform, handle):
            latest[str(row["post_id"])] = row
        return sorted((VoicePost.from_row(r) for r in latest.values()), key=lambda p: p.ts)

    def read_asof(self, platform: str, handle: str, as_of: datetime) -> list[VoicePost]:
        """Posts whose `available_at <= as_of` (deduped by post_id among those visible by then), ascending by ts.
        This is the point-in-time view Phase 1+ consumes so a later scrape never leaks into a past window."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self._read_rows(platform, handle):
            if datetime.fromisoformat(row["available_at"]) > as_of:
                continue
            latest[str(row["post_id"])] = row
        return sorted((VoicePost.from_row(r) for r in latest.values()), key=lambda p: p.ts)


# ---------------------------------------------------------------------------
# X / Twitter via xAI Grok LiveSearch (key-gated; LLM retrieves text only)
# ---------------------------------------------------------------------------


@dataclass
class XaiVoiceProvider:
    """Pull one X handle's recent posts via xAI/Grok LiveSearch. X has no free timeline API, so the LLM is
    used purely to RETRIEVE the posts as JSON; it does NOT score or rank (that is Phase 1+). KEY-GATED:
    no `api_key` and not `offline` → [] (honest degradation). Offline/CI: pass `offline=True` and/or inject
    `_fetcher(handle, limit) -> list[dict]` returning raw post dicts; `FIXTURE_X_POSTS` makes tests
    deterministic. `available_at` = read time (we learned of the post when we queried — no look-ahead)."""

    platform: str = "x"
    api_key: str = ""
    base_url: str = _XAI_BASE_URL
    model: str = _XAI_MODEL
    offline: bool = False
    # Injected raw-post fetcher for tests: callable(handle, limit) -> list[{"id","text","created_at","url"}].
    _fetcher: Callable[[str, int], list[dict[str, Any]]] | None = field(default=None, repr=False)

    def _http_post(self, url: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "cosmu-engine/0.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _live_fetch(self, handle: str, limit: int) -> list[dict[str, Any]]:
        """Ask Grok's LiveSearch for the handle's most recent posts as raw JSON. Errors → [] (never aborts)."""
        user = handle.lstrip("@")
        prompt = (
            f"Use the LiveSearch tool to find the {limit} most recent posts by the X/Twitter user @{user}.\n\n"
            "Return ONLY a JSON array of objects, each with fields: "
            '{"id": "<post id>", "text": "<post text>", "created_at": "<ISO-8601 timestamp>", "url": "<permalink>"}. '
            "No markdown, no commentary — raw JSON only."
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "live_search"}],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 4096,
        }
        try:
            resp = self._http_post(f"{self.base_url}/chat/completions", payload)
            content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or "[]"
            content = content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = content[: content.rfind("```")]
            parsed = json.loads(content.strip())
            return parsed if isinstance(parsed, list) else []
        except Exception:  # noqa: BLE001 — network/parse failure degrades to []
            return []

    def fetch_timeline(self, handle: str, *, limit: int, now: datetime | None = None) -> list[VoicePost]:
        if limit <= 0:
            return []
        if self._fetcher is None and not self.offline and not self.api_key:
            return []  # honest degradation — no key, no read
        raw = self._fetcher(handle, limit) if self._fetcher is not None else (
            list(FIXTURE_X_POSTS) if (self.offline or not self.api_key) else self._live_fetch(handle, limit)
        )
        read_at = _now(now)
        out: list[VoicePost] = []
        for row in raw or []:
            text = (row.get("text") or "").strip()
            ts = _parse_ts(row.get("created_at"))
            if not text or ts is None:
                continue
            pid = str(row.get("id") or "").strip() or _stable_id("x", handle, text, ts)
            out.append(VoicePost("x", handle, pid, text, ts, read_at, url=row.get("url", "") or ""))
        out.sort(key=lambda p: p.ts)
        return out[-limit:] if limit and len(out) > limit else out

    def _live_fetch_since(self, handle: str, *, since: datetime, limit: int) -> list[dict[str, Any]]:
        """Prompt Grok LiveSearch for posts by handle on or after `since`. Coverage of past dates
        is best-effort — LiveSearch indexes are not a guaranteed historical archive."""
        user = handle.lstrip("@")
        since_str = since.strftime("%Y-%m-%d")
        prompt = (
            f"Use the LiveSearch tool to find up to {limit} posts by X/Twitter user @{user} "
            f"posted on or after {since_str}. "
            "Return ONLY a JSON array of objects, each with fields: "
            '{"id": "<post id>", "text": "<post text>", "created_at": "<ISO-8601 timestamp>", "url": "<permalink>"}. '
            "No markdown, no commentary — raw JSON only."
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "live_search"}],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 8192,
        }
        try:
            resp = self._http_post(f"{self.base_url}/chat/completions", payload)
            content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or "[]"
            content = content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = content[: content.rfind("```")]
            parsed = json.loads(content.strip())
            return parsed if isinstance(parsed, list) else []
        except Exception:  # noqa: BLE001
            return []

    def fetch_timeline_history(
        self, handle: str, *, since: datetime, limit: int = 200, now: datetime | None = None
    ) -> list[VoicePost]:
        """Search for handle's posts from `since` using Grok LiveSearch. KEY-GATED: no api_key → [].
        available_at == ts (retrospective PIT). Coverage is best-effort — LiveSearch is not a deep archive."""
        if self._fetcher is None and not self.offline and not self.api_key:
            return []
        if self._fetcher is not None:
            raw = self._fetcher(handle, limit)
        elif self.offline:
            raw = list(FIXTURE_X_POSTS)
        else:
            raw = self._live_fetch_since(handle, since=since, limit=limit)
        out: list[VoicePost] = []
        for row in raw or []:
            text = (row.get("text") or "").strip()
            ts = _parse_ts(row.get("created_at"))
            if not text or ts is None or ts < since:
                continue
            pid = str(row.get("id") or "").strip() or _stable_id("x", handle, text, ts)
            out.append(VoicePost("x", handle, pid, text, ts, ts, url=row.get("url", "") or ""))
        out.sort(key=lambda p: p.ts)
        return out


# ---------------------------------------------------------------------------
# Reddit (public user JSON API: submissions + comments, no auth needed)
# ---------------------------------------------------------------------------


class RedditVoiceProvider:
    """Pull one Reddit user's recent submissions AND comments from the public `user/<name>/{submitted,comments}.json`
    endpoints (no auth, free). Submissions carry the title + selftext; comments carry the body. A real-time public
    read → `available_at` = read time. Reddit blocks bare bot UAs, so we send a descriptive agent. Offline-testable
    via an injected `_fetcher(url) -> dict`. One dead listing is swallowed (never aborts the other)."""

    _UA = "python:cosmu-engine:0.1 (by /u/cosmu-bot)"
    platform = "reddit"

    def __init__(self, *, post_limit: int = 50, _fetcher: Callable[[str], dict] | None = None) -> None:
        self.post_limit = post_limit
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": self._UA})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _listing(self, handle: str, kind: str, limit: int) -> list[dict[str, Any]]:
        user = handle.lstrip("@").removeprefix("u/").removeprefix("/u/")
        query = urllib.parse.urlencode({"limit": min(limit, self.post_limit)})
        url = f"https://www.reddit.com/user/{user}/{kind}.json?{query}"
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001 — one dead listing never aborts the other
            return []
        return [(c.get("data") or {}) for c in ((payload.get("data", {}) or {}).get("children", []) or [])]

    def _listing_paged(
        self, handle: str, kind: str, *, limit: int = 100, after_id: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One paginated page, newest-first. Returns (post-data dicts, next-page cursor or None).
        The cursor is Reddit's `data.after` fullname (e.g. 't3_abc123') used as the `after` query param
        on the next call. None cursor signals the listing is exhausted."""
        user = handle.lstrip("@").removeprefix("u/").removeprefix("/u/")
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after_id:
            params["after"] = after_id
        url = f"https://www.reddit.com/user/{user}/{kind}.json?{urllib.parse.urlencode(params)}"
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001
            return [], None
        data = payload.get("data") or {}
        children = [(c.get("data") or {}) for c in (data.get("children") or [])]
        return children, data.get("after") or None

    def fetch_timeline(self, handle: str, *, limit: int, now: datetime | None = None) -> list[VoicePost]:
        if limit <= 0:
            return []
        read_at = _now(now)
        out: list[VoicePost] = []
        # Submissions: title + selftext is the post's substance.
        for d in self._listing(handle, "submitted", limit):
            title = (d.get("title") or "").strip()
            body = (d.get("selftext") or "").strip()
            text = f"{title}\n\n{body}".strip() if body else title
            out.append(self._post(handle, d, text, read_at))
        # Comments: the body IS the post.
        for d in self._listing(handle, "comments", limit):
            text = (d.get("body") or "").strip()
            out.append(self._post(handle, d, text, read_at))
        out = [p for p in out if p is not None and p.text]
        out.sort(key=lambda p: p.ts)
        return out[-limit:] if limit and len(out) > limit else out

    def _post(self, handle: str, d: dict[str, Any], text: str, read_at: datetime) -> VoicePost | None:
        if not text:
            return None
        created = d.get("created_utc")
        if created is None:
            return None
        ts = datetime.fromtimestamp(float(created), tz=UTC)
        pid = str(d.get("id") or "").strip() or _stable_id("reddit", handle, text, ts)
        permalink = d.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink else ""
        return VoicePost("reddit", handle, pid, text, ts, read_at, url=url)

    def _post_pit(self, handle: str, d: dict[str, Any], text: str) -> VoicePost | None:
        """Build a VoicePost with available_at == ts (retrospective PIT).
        A Reddit post is publicly visible the moment it is posted, so for historical simulation
        we can treat it as known at publication — available_at = ts is the honest backfill stamp."""
        if not text:
            return None
        created = d.get("created_utc")
        if created is None:
            return None
        ts = datetime.fromtimestamp(float(created), tz=UTC)
        pid = str(d.get("id") or "").strip() or _stable_id("reddit", handle, text, ts)
        permalink = d.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink else ""
        return VoicePost("reddit", handle, pid, text, ts, ts, url=url)

    def fetch_timeline_history(self, handle: str, *, since: datetime) -> list[VoicePost]:
        """Paginate back through the user's submitted + comments until posts pre-date `since`.
        available_at == ts so signal_history() can replay the authority series from the backfill
        window start. Reddit caps listings at ~1 000 items per user, newest-first."""
        out: list[VoicePost] = []
        for kind in ("submitted", "comments"):
            cursor: str | None = None
            exhausted = False
            while not exhausted:
                children, cursor = self._listing_paged(handle, kind, after_id=cursor)
                if not children:
                    break
                for d in children:
                    created = d.get("created_utc")
                    if created is None:
                        continue
                    ts = datetime.fromtimestamp(float(created), tz=UTC)
                    if ts < since:
                        exhausted = True
                        break
                    if kind == "comments":
                        text = (d.get("body") or "").strip()
                    else:
                        title = (d.get("title") or "").strip()
                        body = (d.get("selftext") or "").strip()
                        text = f"{title}\n\n{body}".strip() if body else title
                    p = self._post_pit(handle, d, text)
                    if p:
                        out.append(p)
                if cursor is None:
                    break
        seen: dict[str, VoicePost] = {}
        for p in out:
            seen[p.post_id] = p
        return sorted(seen.values(), key=lambda p: p.ts)


# ---------------------------------------------------------------------------
# RSS / Atom (Substack, newsletters, news feeds — stdlib XML, no extra dep)
# ---------------------------------------------------------------------------


class RssVoiceProvider:
    """Pull a newsletter/blog/news voice's recent entries from its RSS 2.0 or Atom feed (free, no key — the
    canonical Substack/newsletter path). Parses with the stdlib XML parser (no feedparser dep). The handle IS
    the feed URL (or a slug mapped to one via `feeds`). `ts` = the entry's published/updated date; `available_at`
    = read time (we learned of it when we fetched the feed — no look-ahead, even for old entries). Offline-testable
    via an injected `_fetcher(url) -> str` returning the raw feed XML. A dead/malformed feed → [] (honest)."""

    platform = "rss"

    def __init__(self, feeds: dict[str, str] | None = None, *, _fetcher: Callable[[str], str] | None = None) -> None:
        self.feeds = dict(feeds or {})  # optional slug -> feed-url map; otherwise the handle is the URL
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; cosmu-engine/0.1; +https://cosmu.local)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def fetch_timeline(self, handle: str, *, limit: int, now: datetime | None = None) -> list[VoicePost]:
        if limit <= 0:
            return []
        feed_url = self.feeds.get(handle, handle)
        try:
            xml_text = self._fetcher(feed_url)
        except Exception:  # noqa: BLE001 — a dead feed never aborts the run
            return []
        posts = _parse_feed(xml_text, handle, _now(now))
        posts.sort(key=lambda p: p.ts)
        return posts[-limit:] if limit and len(posts) > limit else posts

    def fetch_timeline_history(self, handle: str, *, since: datetime) -> list[VoicePost]:
        """Return all feed items with ts >= since. available_at == ts (retrospective PIT mode).
        RSS feeds contain only the items the publisher exposes; typical depth is 30-100 entries."""
        feed_url = self.feeds.get(handle, handle)
        try:
            xml_text = self._fetcher(feed_url)
        except Exception:  # noqa: BLE001
            return []
        posts = _parse_feed(xml_text, handle, None)  # None → available_at = ts
        return sorted((p for p in posts if p.ts >= since), key=lambda p: p.ts)


def _strip_ns(tag: str) -> str:
    """`{http://www.w3.org/2005/Atom}entry` -> `entry` (namespace-agnostic element matching)."""
    return tag.rsplit("}", 1)[-1].lower()


def _find_child(el: ET.Element, name: str) -> ET.Element | None:
    for child in el:
        if _strip_ns(child.tag) == name:
            return child
    return None


def _find_children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _strip_ns(c.tag) == name]


def _text_of(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_feed(xml_text: str, handle: str, read_at: datetime | None) -> list[VoicePost]:
    """Parse RSS 2.0 (<item>) or Atom (<entry>) into VoicePosts. Title + summary/content is the text; the
    entry's published/updated date is `ts`. Unparseable XML or undated entries are skipped (never fabricated).
    `read_at=None` sets available_at == ts (retrospective PIT mode for historical backfill)."""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return []
    # RSS: <rss><channel><item>… ; Atom: <feed><entry>…
    items: list[ET.Element] = []
    channel = _find_child(root, "channel")
    if channel is not None:
        items = _find_children(channel, "item")
    if not items:
        items = _find_children(root, "entry")  # Atom

    out: list[VoicePost] = []
    for it in items:
        title = _text_of(_find_child(it, "title"))
        body = _text_of(_find_child(it, "description")) or _text_of(_find_child(it, "summary")) or _text_of(_find_child(it, "content"))
        text = f"{title}\n\n{body}".strip() if body else title
        if not text:
            continue
        ts = _entry_date(it)
        if ts is None:
            continue
        url = _entry_link(it)
        guid = _text_of(_find_child(it, "guid")) or _text_of(_find_child(it, "id")) or url
        pid = guid or _stable_id("rss", handle, text, ts)
        out.append(VoicePost("rss", handle, pid, text, ts, read_at if read_at is not None else ts, url=url))
    return out


def _entry_date(it: ET.Element) -> datetime | None:
    """RSS `pubDate` (RFC 822) or Atom `published`/`updated` (ISO-8601). None if absent/unparseable."""
    raw = _text_of(_find_child(it, "pubdate")) or _text_of(_find_child(it, "published")) or _text_of(_find_child(it, "updated"))
    if not raw:
        return None
    return _parse_ts(raw)


def _entry_link(it: ET.Element) -> str:
    """RSS `<link>text</link>` or Atom `<link href="…"/>` (prefer rel=alternate)."""
    link = _find_child(it, "link")
    if link is None:
        return ""
    if link.get("href"):  # Atom
        for cand in _find_children(it, "link"):
            if (cand.get("rel") or "alternate") == "alternate" and cand.get("href"):
                return cand.get("href", "")
        return link.get("href", "")
    return _text_of(link)  # RSS


def _parse_ts(raw: Any) -> datetime | None:
    """Parse an ISO-8601 or RFC-822 timestamp into a UTC-aware datetime; None if unparseable. Naive
    timestamps are assumed UTC (the feeds/APIs we read publish in UTC or with an explicit offset)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # ISO-8601 (handle a trailing Z which fromisoformat historically rejected on older pythons).
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    # RFC-822 (RSS pubDate, e.g. "Mon, 01 Jan 2024 00:00:00 GMT").
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Fixture provider + offline fixtures (deterministic CI, no key/network)
# ---------------------------------------------------------------------------


class FixtureVoiceProvider:
    """Deterministic offline timelines so Phase 1+ and tests run with no key/network."""

    def __init__(self, timelines: dict[str, list[VoicePost]], *, platform: str = "fixture") -> None:
        self.platform = platform
        self.timelines = timelines
        self.calls: list[tuple[str, int]] = []

    def fetch_timeline(self, handle: str, *, limit: int, now: datetime | None = None) -> list[VoicePost]:
        self.calls.append((handle, limit))
        posts = sorted(self.timelines.get(handle, []), key=lambda p: p.ts)
        return posts[-limit:] if limit and len(posts) > limit else posts


# Canned X posts (shape mirrors the live LiveSearch parse) for deterministic offline tests.
FIXTURE_X_POSTS: list[dict[str, Any]] = [
    {"id": "x1", "text": "BTC reclaims 70k — this leg targets 80k by month end.", "created_at": "2024-01-01T00:00:00Z", "url": "https://x.com/v/status/x1"},
    {"id": "x2", "text": "ETH/BTC bottoming; rotation into ETH starts here.", "created_at": "2024-01-02T00:00:00Z", "url": "https://x.com/v/status/x2"},
    {"id": "x3", "text": "Closing my long. Macro risk into CPI is not worth it.", "created_at": "2024-01-03T00:00:00Z", "url": "https://x.com/v/status/x3"},
]


# ---------------------------------------------------------------------------
# Backfill runner — Phase-0 historical ingest (available_at == ts for PIT replay)
# ---------------------------------------------------------------------------


@dataclass
class VoiceBackfillRunner:
    """Orchestrates a Phase-0 historical backfill: fetch timelines for a set of handles going back
    `days_back` days and append to the VoiceTimelineStore. Every post gets available_at == ts so
    signal_history() (Phase 3) can replay the authority series from the start of the backfill window.
    Downstream Phase 1 (LLM claim extraction) + Phase 3 must run separately after the store is seeded."""

    store: VoiceTimelineStore
    reddit: RedditVoiceProvider | None = None
    rss: RssVoiceProvider | None = None
    xai: XaiVoiceProvider | None = None

    def run(
        self,
        *,
        reddit_handles: list[str] | None = None,
        rss_handles: list[str] | None = None,
        xai_handles: list[str] | None = None,
        days_back: int = VOICES_BACKFILL_DAYS,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Backfill each configured handle. Returns {platform/handle: posts_appended}.
        `since` overrides `days_back` when an explicit start datetime is needed."""
        since = since if since is not None else datetime.now(tz=UTC) - timedelta(days=days_back)
        results: dict[str, int] = {}
        if self.reddit and reddit_handles:
            for handle in reddit_handles:
                posts = self.reddit.fetch_timeline_history(handle, since=since)
                results[f"reddit/{handle}"] = self.store.append(posts)
        if self.rss and rss_handles:
            for handle in rss_handles:
                posts = self.rss.fetch_timeline_history(handle, since=since)
                results[f"rss/{handle}"] = self.store.append(posts)
        if self.xai and xai_handles:
            for handle in xai_handles:
                posts = self.xai.fetch_timeline_history(handle, since=since)
                results[f"x/{handle}"] = self.store.append(posts)
        return results


__all__ = [
    "VOICES_TRANSFORM_VERSION",
    "VOICES_BACKFILL_DAYS",
    "VoicePost",
    "VoiceTimelineProvider",
    "VoiceTimelineStore",
    "XaiVoiceProvider",
    "RedditVoiceProvider",
    "RssVoiceProvider",
    "FixtureVoiceProvider",
    "VoiceBackfillRunner",
    "FIXTURE_X_POSTS",
]
