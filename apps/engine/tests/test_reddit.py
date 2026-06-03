"""RedditSentimentProvider — offline tests with a canned hot.json fixture (no network)."""

from __future__ import annotations

from datetime import UTC

from cosmu.data.altdata import AltDataStore, RedditSentimentProvider


def _hot(titles: list[str]) -> dict:
    """Shape a Reddit `hot.json` payload from a list of post titles."""
    return {"data": {"children": [{"data": {"title": t}} for t in titles]}}


def _provider(by_sub: dict[str, list[str]]) -> RedditSentimentProvider:
    subs = tuple(by_sub.keys())

    def fetcher(url: str) -> dict:
        for sub in subs:
            if f"/r/{sub}/" in url:
                return _hot(by_sub[sub])
        return _hot([])

    return RedditSentimentProvider(subs, _fetcher=fetcher)


def test_score_is_normalized_and_signed() -> None:
    # 3 bullish, 1 bearish, 1 neutral across 5 posts → (3 - 1) / 5 = +0.4
    p = _provider({"cryptocurrency": ["BTC to the moon", "buy the rally", "bullish breakout", "market crash incoming", "weekly discussion"]})
    series = p.fetch_series("MARKET", "reddit_sentiment", limit=10)
    assert len(series) == 1
    assert series[0].value == 0.4
    assert -1.0 <= series[0].value <= 1.0


def test_point_in_time_is_observation_time() -> None:
    """Real-time public read → available_at == ts (we know it when we read it; no look-ahead)."""
    p = _provider({"bitcoin": ["bullish", "bearish"]})
    pt = p.fetch_series("MARKET", "reddit_sentiment", limit=10)[0]
    assert pt.available_at == pt.ts
    assert pt.ts.tzinfo == UTC


def test_wrong_metric_returns_empty() -> None:
    p = _provider({"bitcoin": ["bullish"]})
    assert p.fetch_series("MARKET", "fear_greed", limit=10) == []


def test_no_scored_posts_returns_empty_not_fabricated_zero() -> None:
    p = _provider({"bitcoin": []})
    assert p.fetch_series("MARKET", "reddit_sentiment", limit=10) == []


def test_one_dead_subreddit_never_aborts_the_read() -> None:
    def fetcher(url: str) -> dict:
        if "/r/bitcoin/" in url:
            raise RuntimeError("reddit 503")
        return _hot(["bullish pump", "bullish moon"])

    p = RedditSentimentProvider(("bitcoin", "cryptocurrency"), _fetcher=fetcher)
    series = p.fetch_series("MARKET", "reddit_sentiment", limit=10)
    assert len(series) == 1 and series[0].value == 1.0  # both surviving posts bullish


def test_ingest_reddit_market_wide(tmp_path) -> None:
    from cosmu.ingest.pipeline import ingest_market_wide_numeric

    store = AltDataStore(tmp_path / "alt")
    p = _provider({"cryptocurrency": ["bullish", "bearish", "moon"]})
    count = ingest_market_wide_numeric(
        store, p, source_metric="reddit_sentiment", stored_metric="reddit_sentiment", provider_name="reddit"
    )
    assert count == 1
    stored = store.read_all("reddit", "MARKET", "reddit_sentiment")
    assert len(stored) == 1
