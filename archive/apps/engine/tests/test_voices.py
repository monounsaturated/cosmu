"""Phase-0 voice-timeline ingest — offline tests (no key, no network).

Covers all three providers (X via xAI/Grok, Reddit, RSS/Atom) plus the append-only point-in-time store.
Every test injects a fixture fetcher or uses `offline=True`, so CI runs fully deterministically.
Invariants under test: honest degradation (no key / dead fetch → []), point-in-time stamping
(`available_at` = read time, never back-dated), dedup by post_id, ascending-by-ts ordering, and
retrospective PIT stamping (available_at == ts) for the backfill history path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.sources.voices import (
    FIXTURE_X_POSTS,
    FixtureVoiceProvider,
    RedditVoiceProvider,
    RssVoiceProvider,
    VoiceBackfillRunner,
    VoicePost,
    VoiceTimelineStore,
    XaiVoiceProvider,
)

_READ_AT = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# X / xAI Grok provider
# ---------------------------------------------------------------------------


def test_xai_no_key_returns_empty_not_fabricated() -> None:
    """No XAI_API_KEY and not offline → [] (honest degradation, never a fabricated post)."""
    p = XaiVoiceProvider(api_key="", offline=False)
    assert p.fetch_timeline("@someone", limit=10) == []


def test_xai_offline_uses_fixture_posts() -> None:
    p = XaiVoiceProvider(api_key="", offline=True)
    posts = p.fetch_timeline("@trader", limit=10, now=_READ_AT)
    assert len(posts) == len(FIXTURE_X_POSTS)
    assert all(isinstance(x, VoicePost) and x.platform == "x" and x.handle == "@trader" for x in posts)
    # Ascending by creation time, with the read time as the point-in-time stamp.
    assert [x.ts for x in posts] == sorted(x.ts for x in posts)
    assert all(x.available_at == _READ_AT for x in posts)
    assert all(x.ts.tzinfo == UTC for x in posts)


def test_xai_injected_fetcher_and_id_fallback() -> None:
    """Posts with no id get a deterministic content-hash id (so re-runs dedup), and limit is respected."""
    raw = [
        {"text": "first call", "created_at": "2024-01-01T00:00:00Z"},  # no id → hashed
        {"text": "second call", "created_at": "2024-01-02T00:00:00Z", "id": "abc"},
        {"text": "", "created_at": "2024-01-03T00:00:00Z"},  # empty text → dropped
    ]
    p = XaiVoiceProvider(_fetcher=lambda h, lim: raw)
    posts = p.fetch_timeline("@v", limit=10, now=_READ_AT)
    assert [x.text for x in posts] == ["first call", "second call"]
    assert posts[0].post_id.startswith("x_")  # hashed fallback
    assert posts[1].post_id == "abc"
    # Stable hash: same content → same id across calls.
    again = p.fetch_timeline("@v", limit=10, now=_READ_AT)
    assert again[0].post_id == posts[0].post_id


def test_xai_limit_trims_to_most_recent() -> None:
    p = XaiVoiceProvider(api_key="", offline=True)
    full = p.fetch_timeline("@trader", limit=10, now=_READ_AT)
    posts = p.fetch_timeline("@trader", limit=2, now=_READ_AT)
    assert len(posts) == 2
    assert posts[-1].ts == max(x.ts for x in full)  # keeps the most-recent by ts
    assert p.fetch_timeline("@trader", limit=0) == []


# ---------------------------------------------------------------------------
# Reddit provider
# ---------------------------------------------------------------------------


def _reddit_listing(kind: str, rows: list[dict]) -> dict:
    return {"data": {"children": [{"data": d} for d in rows]}}


def test_reddit_merges_submissions_and_comments() -> None:
    submitted = [{"id": "s1", "title": "BTC thesis", "selftext": "long and strong", "created_utc": 1704067200, "permalink": "/r/x/s1"}]
    comments = [{"id": "c1", "body": "agreed, accumulation here", "created_utc": 1704153600, "permalink": "/r/x/c1"}]

    def fetcher(url: str) -> dict:
        if "/submitted.json" in url:
            return _reddit_listing("submitted", submitted)
        if "/comments.json" in url:
            return _reddit_listing("comments", comments)
        return {"data": {"children": []}}

    p = RedditVoiceProvider(_fetcher=fetcher)
    posts = p.fetch_timeline("u/someone", limit=10, now=_READ_AT)
    assert {x.post_id for x in posts} == {"s1", "c1"}
    sub = next(x for x in posts if x.post_id == "s1")
    assert "BTC thesis" in sub.text and "long and strong" in sub.text  # title + selftext joined
    assert all(x.platform == "reddit" and x.available_at == _READ_AT for x in posts)
    assert posts[0].ts < posts[1].ts  # ascending
    assert posts[0].url.startswith("https://www.reddit.com/")


def test_reddit_one_dead_listing_never_aborts() -> None:
    comments = [{"id": "c1", "body": "still here", "created_utc": 1704153600}]

    def fetcher(url: str) -> dict:
        if "/submitted.json" in url:
            raise RuntimeError("reddit 503")
        return _reddit_listing("comments", comments)

    p = RedditVoiceProvider(_fetcher=fetcher)
    posts = p.fetch_timeline("u/someone", limit=10, now=_READ_AT)
    assert [x.post_id for x in posts] == ["c1"]


def test_reddit_empty_user_returns_empty() -> None:
    p = RedditVoiceProvider(_fetcher=lambda url: {"data": {"children": []}})
    assert p.fetch_timeline("u/ghost", limit=10) == []


def test_reddit_subreddit_handle_fetches_subreddit_listing_not_user() -> None:
    # An 'r/<sub>' handle must hit the SUBREDDIT listing (r/<sub>/hot.json), NOT the user endpoint — otherwise a
    # subreddit voice 404s. Submissions (title + selftext) are the crowd's posts; there is no comments timeline.
    seen: dict[str, str] = {}
    subs = [{"id": "x1", "title": "BTC strong", "selftext": "accumulate", "created_utc": 1704067200,
             "permalink": "/r/Bitcoin/comments/x1"}]

    def fetcher(url: str) -> dict:
        seen["url"] = url
        return _reddit_listing("hot", subs)

    p = RedditVoiceProvider(_fetcher=fetcher)
    posts = p.fetch_timeline("r/Bitcoin", limit=10, now=_READ_AT)
    assert "/r/Bitcoin/hot.json" in seen["url"] and "/user/" not in seen["url"]
    assert [x.post_id for x in posts] == ["x1"]
    assert "BTC strong" in posts[0].text and "accumulate" in posts[0].text
    assert posts[0].platform == "reddit" and posts[0].available_at == _READ_AT


def test_reddit_subreddit_history_paginates_new_and_respects_since() -> None:
    # A subreddit backfill paginates `new.json` and stops at `since` (available_at == ts, retrospective PIT).
    _MAR = 1709251200  # 2024-03-01
    _DEC_2023 = 1701388800  # 2023-12-01
    rows = [
        {"id": "new", "title": "March post", "selftext": "", "created_utc": _MAR, "permalink": "/r/Bitcoin/new"},
        {"id": "old", "title": "Dec post", "selftext": "", "created_utc": _DEC_2023, "permalink": "/r/Bitcoin/old"},
    ]
    seen: dict[str, str] = {}

    def fetcher(url: str) -> dict:
        seen["url"] = url
        return _reddit_listing("new", rows)

    p = RedditVoiceProvider(_fetcher=fetcher)
    posts = p.fetch_timeline_history("r/Bitcoin", since=datetime(2024, 1, 1, tzinfo=UTC))
    assert "/r/Bitcoin/new.json" in seen["url"]
    assert [x.post_id for x in posts] == ["new"]  # the Dec post pre-dates `since` → excluded
    assert posts[0].available_at == posts[0].ts  # retrospective PIT stamp


# ---------------------------------------------------------------------------
# RSS / Atom provider
# ---------------------------------------------------------------------------


_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>A Newsletter</title>
  <item>
    <title>Why I am long ETH</title>
    <description>The rotation thesis in full.</description>
    <link>https://sub.stack/p/eth</link>
    <guid>https://sub.stack/p/eth</guid>
    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Macro caution</title>
    <description>Trimming risk into CPI.</description>
    <link>https://sub.stack/p/macro</link>
    <guid>https://sub.stack/p/macro</guid>
    <pubDate>Wed, 03 Jan 2024 00:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Voice</title>
  <entry>
    <title>First post</title>
    <summary>Bullish setup.</summary>
    <id>tag:atom,2024:1</id>
    <link rel="alternate" href="https://atom.example/1"/>
    <published>2024-02-01T00:00:00Z</published>
  </entry>
</feed>"""


def test_rss_parses_items() -> None:
    p = RssVoiceProvider(_fetcher=lambda url: _RSS)
    posts = p.fetch_timeline("https://sub.stack/feed", limit=10, now=_READ_AT)
    assert len(posts) == 2
    assert posts[0].platform == "rss"
    assert "Why I am long ETH" in posts[0].text and "rotation thesis" in posts[0].text
    assert posts[0].ts == datetime(2024, 1, 1, tzinfo=UTC)
    assert posts[1].ts == datetime(2024, 1, 3, tzinfo=UTC)  # ascending
    assert posts[0].post_id == "https://sub.stack/p/eth"  # guid
    assert all(x.available_at == _READ_AT for x in posts)  # read time, not pubDate (no look-ahead games)


def test_rss_slug_maps_to_feed_url() -> None:
    seen: list[str] = []

    def fetcher(url: str) -> str:
        seen.append(url)
        return _RSS

    p = RssVoiceProvider(feeds={"someone": "https://sub.stack/feed"}, _fetcher=fetcher)
    p.fetch_timeline("someone", limit=10)
    assert seen == ["https://sub.stack/feed"]


def test_atom_feed_parses_entries() -> None:
    p = RssVoiceProvider(_fetcher=lambda url: _ATOM)
    posts = p.fetch_timeline("https://atom.example/feed", limit=10, now=_READ_AT)
    assert len(posts) == 1
    assert posts[0].text.startswith("First post")
    assert posts[0].ts == datetime(2024, 2, 1, tzinfo=UTC)
    assert posts[0].url == "https://atom.example/1"
    assert posts[0].post_id == "tag:atom,2024:1"


def test_rss_dead_or_malformed_feed_returns_empty() -> None:
    assert RssVoiceProvider(_fetcher=lambda url: "not xml at all").fetch_timeline("u", limit=5) == []

    def boom(url: str) -> str:
        raise RuntimeError("dns fail")

    assert RssVoiceProvider(_fetcher=boom).fetch_timeline("u", limit=5) == []


# ---------------------------------------------------------------------------
# Store: append-only, dedup, point-in-time
# ---------------------------------------------------------------------------


def _post(handle: str, pid: str, day: int, text: str, available_day: int) -> VoicePost:
    return VoicePost(
        platform="x",
        handle=handle,
        post_id=pid,
        text=text,
        ts=datetime(2024, 1, day, tzinfo=UTC),
        available_at=datetime(2024, 1, available_day, tzinfo=UTC),
    )


def test_store_append_read_all_dedups_latest_wins(tmp_path) -> None:
    store = VoiceTimelineStore(tmp_path / "v")
    store.append([_post("@v", "p1", 1, "original", 1), _post("@v", "p2", 2, "second", 2)])
    # Re-ingest p1 with edited text — latest append wins, count stays 2.
    store.append([_post("@v", "p1", 1, "edited", 5)])
    posts = store.read_all("x", "@v")
    assert [p.post_id for p in posts] == ["p1", "p2"]  # ascending by ts, deduped
    assert next(p for p in posts if p.post_id == "p1").text == "edited"


def test_store_read_asof_is_point_in_time(tmp_path) -> None:
    store = VoiceTimelineStore(tmp_path / "v")
    store.append([_post("@v", "p1", 1, "early", 1), _post("@v", "p2", 10, "late", 20)])
    as_of = datetime(2024, 1, 15, tzinfo=UTC)
    visible = store.read_asof("x", "@v", as_of)
    assert [p.post_id for p in visible] == ["p1"]  # p2 not yet available at as_of
    assert store.read_asof("x", "@v", datetime(2024, 1, 25, tzinfo=UTC))  # later → both
    assert len(store.read_asof("x", "@v", datetime(2024, 1, 25, tzinfo=UTC))) == 2


def test_store_separates_platforms_and_handles(tmp_path) -> None:
    store = VoiceTimelineStore(tmp_path / "v")
    store.append([
        VoicePost("x", "@a", "1", "x-a", datetime(2024, 1, 1, tzinfo=UTC), _READ_AT),
        VoicePost("reddit", "u/a", "1", "r-a", datetime(2024, 1, 1, tzinfo=UTC), _READ_AT),
    ])
    assert [p.text for p in store.read_all("x", "@a")] == ["x-a"]
    assert [p.text for p in store.read_all("reddit", "u/a")] == ["r-a"]
    assert store.read_all("x", "@nobody") == []


def test_store_round_trips_provider_output(tmp_path) -> None:
    """End-to-end: an offline provider's posts persist and read back identically."""
    store = VoiceTimelineStore(tmp_path / "v")
    provider = XaiVoiceProvider(api_key="", offline=True)
    posts = provider.fetch_timeline("@trader", limit=10, now=_READ_AT)
    assert store.append(posts) == len(posts)
    back = store.read_all("x", "@trader")
    assert [p.post_id for p in back] == [p.post_id for p in posts]
    assert [p.text for p in back] == [p.text for p in posts]


# ---------------------------------------------------------------------------
# Fixture provider
# ---------------------------------------------------------------------------


def test_fixture_provider_returns_canned_timeline_ascending() -> None:
    posts = [_post("@v", "p2", 2, "b", 2), _post("@v", "p1", 1, "a", 1)]
    prov = FixtureVoiceProvider({"@v": posts})
    got = prov.fetch_timeline("@v", limit=10)
    assert [p.post_id for p in got] == ["p1", "p2"]  # sorted ascending by ts
    assert prov.fetch_timeline("@unknown", limit=10) == []
    assert prov.calls == [("@v", 10), ("@unknown", 10)]


# ---------------------------------------------------------------------------
# Backfill history: PIT invariant (available_at == ts), pagination, since cutoff
# ---------------------------------------------------------------------------

# Epoch seconds for month-spaced anchors (2024 Q1).
_JAN = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp())
_FEB = int(datetime(2024, 2, 1, tzinfo=UTC).timestamp())
_MAR = int(datetime(2024, 3, 1, tzinfo=UTC).timestamp())
_DEC_2023 = int(datetime(2023, 12, 1, tzinfo=UTC).timestamp())


def _r_listing(rows: list[dict], after: str | None = None) -> dict:
    return {"data": {"children": [{"data": d} for d in rows], "after": after}}


def test_reddit_history_available_at_equals_ts() -> None:
    """The retrospective PIT invariant: every backfill post has available_at == ts."""
    rows = [
        {"id": "a", "title": "March call", "selftext": "", "created_utc": _MAR, "permalink": "/r/x/a"},
        {"id": "b", "title": "Jan call", "selftext": "", "created_utc": _JAN, "permalink": "/r/x/b"},
    ]
    p = RedditVoiceProvider(_fetcher=lambda url: _r_listing(rows))
    posts = p.fetch_timeline_history("u/trader", since=datetime(2024, 1, 1, tzinfo=UTC))
    assert all(post.available_at == post.ts for post in posts), "backfill must stamp available_at = ts"


def test_reddit_history_respects_since_cutoff() -> None:
    """Posts older than `since` are excluded even when returned by the API."""
    rows = [
        {"id": "new", "title": "New post", "selftext": "", "created_utc": _MAR, "permalink": "/r/x/new"},
        {"id": "old", "title": "Old post", "selftext": "", "created_utc": _DEC_2023, "permalink": "/r/x/old"},
    ]
    p = RedditVoiceProvider(_fetcher=lambda url: _r_listing(rows))
    since = datetime(2024, 1, 1, tzinfo=UTC)
    posts = p.fetch_timeline_history("u/trader", since=since)
    assert all(post.ts >= since for post in posts)
    assert not any(post.post_id == "old" for post in posts)


def test_reddit_history_paginates_across_pages() -> None:
    """Two API pages are fetched and merged when the cursor is non-null after page 1."""
    page1 = [{"id": "p3", "title": "March", "selftext": "", "created_utc": _MAR, "permalink": "/r/x/p3"}]
    page2 = [{"id": "p2", "title": "Feb", "selftext": "", "created_utc": _FEB, "permalink": "/r/x/p2"}]
    page3: list = []

    calls: list[str] = []

    def fetcher(url: str) -> dict:
        calls.append(url)
        if "after" not in url:
            return _r_listing(page1, after="t3_p3")
        if "after=t3_p3" in url:
            return _r_listing(page2, after=None)
        return _r_listing(page3)

    p = RedditVoiceProvider(_fetcher=fetcher)
    posts = p.fetch_timeline_history("u/trader", since=datetime(2024, 1, 15, tzinfo=UTC))
    post_ids = {post.post_id for post in posts}
    assert "p3" in post_ids
    assert "p2" in post_ids  # second page was fetched
    assert len([c for c in calls if "submitted" in c]) == 2  # two submitted pages


def test_reddit_history_stops_at_since_without_over_fetching() -> None:
    """Pagination stops as soon as a post older than `since` is encountered."""
    rows = [
        {"id": "new", "title": "Recent", "selftext": "", "created_utc": _MAR, "permalink": "/r/x/new"},
        {"id": "old", "title": "Old", "selftext": "", "created_utc": _DEC_2023, "permalink": "/r/x/old"},
    ]
    calls: list[str] = []

    def fetcher(url: str) -> dict:
        calls.append(url)
        return _r_listing(rows, after="t3_would_continue")  # cursor always non-null

    p = RedditVoiceProvider(_fetcher=fetcher)
    posts = p.fetch_timeline_history("u/trader", since=datetime(2024, 1, 1, tzinfo=UTC))
    # Pagination stops after the cutoff hit — we should NOT have fetched a second page.
    submitted_calls = [c for c in calls if "submitted" in c]
    assert len(submitted_calls) == 1, "should stop paginating once cutoff hit"
    assert all(post.ts >= datetime(2024, 1, 1, tzinfo=UTC) for post in posts)


def test_reddit_history_deduplicates_by_post_id() -> None:
    """Same post_id appearing twice (e.g. from overlapping pages) produces one VoicePost."""
    rows = [
        {"id": "dup", "title": "Dupe", "selftext": "", "created_utc": _FEB, "permalink": "/r/x/dup"},
        {"id": "dup", "title": "Dupe again", "selftext": "", "created_utc": _FEB, "permalink": "/r/x/dup"},
    ]
    p = RedditVoiceProvider(_fetcher=lambda url: _r_listing(rows))
    posts = p.fetch_timeline_history("u/trader", since=datetime(2024, 1, 1, tzinfo=UTC))
    dup_ids = [post.post_id for post in posts if post.post_id == "dup"]
    assert len(dup_ids) == 1


def test_rss_history_available_at_equals_ts() -> None:
    """RSS backfill sets available_at == ts (retrospective PIT)."""
    p = RssVoiceProvider(_fetcher=lambda url: _RSS)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    posts = p.fetch_timeline_history("https://sub.stack/feed", since=since)
    assert len(posts) == 2
    assert all(post.available_at == post.ts for post in posts)


def test_rss_history_filters_by_since() -> None:
    """Items with ts < since are excluded."""
    p = RssVoiceProvider(_fetcher=lambda url: _RSS)
    since = datetime(2024, 1, 2, tzinfo=UTC)
    posts = p.fetch_timeline_history("https://sub.stack/feed", since=since)
    assert all(post.ts >= since for post in posts)
    assert len(posts) == 1  # only Jan 3 entry survives


def test_xai_history_available_at_equals_ts() -> None:
    """XAI backfill stamps available_at == ts for returned posts."""
    p = XaiVoiceProvider(api_key="", offline=True)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    posts = p.fetch_timeline_history("@trader", since=since)
    assert all(post.available_at == post.ts for post in posts)


def test_xai_history_filters_posts_before_since() -> None:
    """Posts older than `since` are excluded even if the provider returned them."""
    raw = [
        {"id": "x1", "text": "Recent", "created_at": "2024-03-01T00:00:00Z"},
        {"id": "x2", "text": "Old", "created_at": "2023-11-01T00:00:00Z"},
    ]
    p = XaiVoiceProvider(_fetcher=lambda h, lim: raw)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    posts = p.fetch_timeline_history("@trader", since=since)
    assert all(post.ts >= since for post in posts)
    assert not any(post.post_id == "x2" for post in posts)


def test_xai_history_no_key_returns_empty() -> None:
    p = XaiVoiceProvider(api_key="", offline=False)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    assert p.fetch_timeline_history("@trader", since=since) == []


def test_voice_backfill_runner_integrates_providers_and_store(tmp_path) -> None:
    """VoiceBackfillRunner feeds each provider's history into the store and returns per-handle counts."""
    store = VoiceTimelineStore(tmp_path / "voices")

    reddit_rows = [{"id": "r1", "title": "BTC up", "selftext": "", "created_utc": _FEB, "permalink": "/r/x/r1"}]
    reddit = RedditVoiceProvider(_fetcher=lambda url: _r_listing(reddit_rows))
    rss = RssVoiceProvider(_fetcher=lambda url: _RSS)

    runner = VoiceBackfillRunner(store=store, reddit=reddit, rss=rss)
    results = runner.run(
        reddit_handles=["u/trader"],
        rss_handles=["https://sub.stack/feed"],
        since=datetime(2023, 12, 1, tzinfo=UTC),  # explicit since so fixture dates (2024 Q1) are in range
    )

    assert results["reddit/u/trader"] >= 1
    assert results["rss/https://sub.stack/feed"] >= 1
    # All stored posts must satisfy available_at == ts (retrospective PIT).
    for platform, handle in [("reddit", "u/trader"), ("rss", "https://sub.stack/feed")]:
        for post in store.read_all(platform, handle):
            assert post.available_at == post.ts, f"{platform}/{handle}: available_at != ts"


def test_voice_backfill_runner_empty_handles_skips_gracefully(tmp_path) -> None:
    store = VoiceTimelineStore(tmp_path / "voices")
    runner = VoiceBackfillRunner(store=store)
    results = runner.run(reddit_handles=None, rss_handles=None, xai_handles=None)
    assert results == {}
