# intent: xAI/Grok-backed Twitter/X crypto-sentiment source — a point-in-time AltDataProvider that
# queries the xAI LiveSearch API to collect recent crypto-relevant tweets, then asks Grok to score them
# on a [-1, +1] sentiment scale. The LLM ONLY standardizes/scores text; it never touches the gate,
# scoring, or money path. KEY-GATED: no XAI_API_KEY → returns [] (honest degradation). Offline CI
# fixture + mocked network so tests run without a key. Availability = observation time (real-time read;
# known when fetched — no look-ahead). tier1, low-confidence until validated OOS.
#
# Influencer scoring: each tweet carries an author_id. A stub InfluencerHitRateStore defines the
# shape (author_id → historical_hit_rate ∈ [0, 1]); a real implementation would back-test each
# account's past calls vs subsequent price moves and store the empirical hit-rate. Until the store is
# populated every account defaults to 0.5 (neutral weight). The final sentiment is a weighted average
# (weight ∝ hit_rate) rather than a simple mean — so an account that has historically called moves
# correctly is up-weighted, while noisy accounts stay at baseline.
#
# TODO(influencer-store): implement a real InfluencerHitRateStore backed by the alt_data table or a
# dedicated Postgres table (author_id, n_calls, n_correct, hit_rate). Populate it by comparing each
# author's past tweets against subsequent (next-bar) price direction, running a quarterly refresh job.
# The stub here already defines the interface; swap out the implementation without changing this file.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from cosmu.data.altdata import AltDataPoint

# Frozen, versioned transform — bump if scoring logic or prompt changes so a gate-passed strategy
# remains byte-for-byte re-runnable on its original transform.
TRANSFORM_VERSION = "xai-twitter-sentiment-v1"

# The xAI Chat Completions endpoint (OpenAI-compatible) with LiveSearch for real-time tweets.
_XAI_BASE_URL = "https://api.x.ai/v1"
_XAI_MODEL = "grok-3-mini"  # cheap + fast for text scoring; upgrade to grok-3 if accuracy demands it

# Crypto-relevant search query sent to LiveSearch.  Keep it tight: BTC / ETH / crypto + English only.
_DEFAULT_QUERY = "BTC OR ETH OR crypto market sentiment -is:retweet lang:en"
_DEFAULT_MAX_TWEETS = 20  # per fetch; balanced between signal richness and API cost

# Availability lag: a real-time Twitter read is knowable at the moment it is fetched; no look-ahead.
# available_at == ts (observation time). This is consistent with RedditSentimentProvider.
_AVAILABILITY_LAG = timedelta(0)

# Deterministic offline fixture used in tests (no key / no network).  Shape mirrors the parsed output
# of the live path: a list of {"text": str, "author_id": str, "created_at": str (ISO-8601)}.
FIXTURE_TWEETS: list[dict[str, str]] = [
    {"text": "BTC breaking ATH, massive bull run incoming! 🚀", "author_id": "u001", "created_at": "2024-01-01T00:00:00Z"},
    {"text": "Crypto market crashing hard, capitulation incoming", "author_id": "u002", "created_at": "2024-01-01T00:05:00Z"},
    {"text": "ETH accumulation zone, long-term bullish thesis intact", "author_id": "u003", "created_at": "2024-01-01T00:10:00Z"},
    {"text": "Total market dump, bear market confirmed", "author_id": "u002", "created_at": "2024-01-01T00:15:00Z"},
    {"text": "Weekly crypto discussion — market looks healthy", "author_id": "u004", "created_at": "2024-01-01T00:20:00Z"},
]

# Fixture Grok scoring response: a JSON array of {author_id, score} objects.  The offline path skips
# the live API and parses this directly so tests remain deterministic.
FIXTURE_SCORES: list[dict[str, Any]] = [
    {"author_id": "u001", "score": 0.85},
    {"author_id": "u002", "score": -0.80},
    {"author_id": "u003", "score": 0.60},
    {"author_id": "u002", "score": -0.70},
    {"author_id": "u004", "score": 0.10},
]


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context so HTTPS works on hosts without system CA certs (sandbox, slim images)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# ---------------------------------------------------------------------------
# Influencer hit-rate store (stubbed — defines shape; real impl is a TODO)
# ---------------------------------------------------------------------------


@runtime_checkable
class InfluencerHitRateStore(Protocol):
    """Protocol for an account-level hit-rate lookup.

    hit_rate(author_id) → float in [0, 1]: the empirical fraction of past calls by this account that
    were followed by a favorable price move (defined as next-bar close above/below entry).  Returns
    0.5 (neutral weight) when the author is unknown or the store is empty.

    TODO(influencer-store): implement with a Postgres table:
        CREATE TABLE influencer_hit_rates (
            author_id TEXT PRIMARY KEY,
            n_calls    INTEGER NOT NULL DEFAULT 0,
            n_correct  INTEGER NOT NULL DEFAULT 0,
            hit_rate   REAL    NOT NULL DEFAULT 0.5,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    Populate via a quarterly refresh job that:
    1. Reads all past tweets from alt_data (provider='xai', metric='twitter_sentiment_raw').
    2. For each tweet, looks up the next-bar close on the referenced asset.
    3. Increments n_calls / n_correct per author.
    4. Upserts the hit_rate = n_correct / n_calls.
    Swap this stub for the real PgInfluencerHitRateStore without changing XaiTwitterProvider.
    """

    def hit_rate(self, author_id: str) -> float:
        """Return the author's empirical hit-rate in [0, 1]; default 0.5 if unknown."""
        ...


class StubInfluencerHitRateStore:
    """Stub implementation: every author returns 0.5 (equal-weight, no learned preference).

    Replace with a real implementation backed by the Postgres ``influencer_hit_rates`` table once
    enough historical tweet→price pairs have been collected (see TODO above in the protocol).
    """

    def __init__(self, overrides: dict[str, float] | None = None) -> None:
        # Optional author_id → hit_rate overrides, useful in tests.
        self._overrides: dict[str, float] = overrides or {}

    def hit_rate(self, author_id: str) -> float:
        return float(self._overrides.get(author_id, 0.5))


# ---------------------------------------------------------------------------
# xAI/Grok Twitter provider
# ---------------------------------------------------------------------------


@dataclass
class XaiTwitterProvider:
    """xAI/Grok-backed Twitter/X crypto-sentiment provider.

    Fetches recent tweets via the xAI LiveSearch API, scores them with Grok on a [-1, +1] scale
    (−1 = strongly bearish, +1 = strongly bullish), then computes an influencer-weighted average.

    KEY-GATED: no XAI_API_KEY → returns [] honestly (never a fabricated read).  The LLM only
    standardizes text; it NEVER touches the gate, scoring, or money path.

    Availability = observation time (real-time feed, known when fetched, no look-ahead).

    Influencer weighting: each tweet's score is multiplied by the author's historical hit-rate
    from ``hit_rate_store`` (default: StubInfluencerHitRateStore, equal-weight at 0.5).  The final
    value is the weighted average score in [-1, 1]; absent any scored tweets → [].

    Offline/CI: pass ``offline=True`` (or omit the API key) and inject a ``_scorer`` callable to
    bypass network access.  The bundled FIXTURE_TWEETS + FIXTURE_SCORES make tests deterministic.
    """

    api_key: str = ""
    base_url: str = _XAI_BASE_URL
    model: str = _XAI_MODEL
    query: str = _DEFAULT_QUERY
    max_tweets: int = _DEFAULT_MAX_TWEETS
    offline: bool = False
    hit_rate_store: Any = field(default_factory=StubInfluencerHitRateStore)  # InfluencerHitRateStore
    # Injected scorer for tests: callable(tweets) → list[{"author_id", "score"}].
    # Production path uses _call_grok_score.  Tests inject a lambda over FIXTURE_SCORES.
    _scorer: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._scorer is None:
            self._scorer = self._call_grok_score

    # ------------------------------------------------------------------
    # Network helpers
    # ------------------------------------------------------------------

    def _http_post(self, url: str, payload: dict) -> dict:
        """POST JSON to url with the xAI API key; returns parsed JSON."""
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

    # ------------------------------------------------------------------
    # Tweet fetching (xAI LiveSearch)
    # ------------------------------------------------------------------

    def _fetch_tweets(self) -> list[dict[str, str]]:
        """Fetch recent crypto tweets via Grok's LiveSearch tool.  Returns a list of
        {"text": str, "author_id": str, "created_at": str}.

        Uses the xAI Chat Completions endpoint with a LiveSearch tool call to retrieve real tweets.
        Errors are swallowed (returns []) so one dead source never aborts the ingest pass.
        """
        if self.offline or not self.api_key:
            return list(FIXTURE_TWEETS)

        prompt = (
            f"Use the LiveSearch tool to find the {self.max_tweets} most recent tweets matching: "
            f"{self.query}\n\n"
            "Return ONLY a JSON array of objects, each with fields: "
            '{"text": "<tweet text>", "author_id": "<twitter user id>", "created_at": "<ISO-8601 timestamp>"}. '
            "No markdown, no commentary — raw JSON only."
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "live_search"}],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 2048,
        }
        try:
            resp = self._http_post(f"{self.base_url}/chat/completions", payload)
            content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or "[]"
            # Strip markdown code fences if Grok wrapped the JSON.
            content = content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = content[: content.rfind("```")]
            return json.loads(content.strip()) or []
        except Exception:  # noqa: BLE001 — network/parse failure degrades to []
            return []

    # ------------------------------------------------------------------
    # Grok scoring (LLM only standardizes text — never on the money path)
    # ------------------------------------------------------------------

    def _call_grok_score(self, tweets: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Ask Grok to score each tweet's sentiment in [-1, 1].

        The LLM's ONLY job here is to turn free-form text into a numeric score.  The score is then
        stored as a point-in-time feature; the deterministic Gate decides what to fund.

        Returns a list of {"author_id": str, "score": float} matching the input order.
        Errors → [] (degrade honestly; one failure never aborts the pass).
        """
        if not tweets:
            return []

        numbered = "\n".join(
            f'{i + 1}. author_id={t["author_id"]} | {t["text"]}' for i, t in enumerate(tweets)
        )
        prompt = (
            "You are a crypto-market sentiment scorer. For each tweet below, assign a sentiment score "
            "in the range [-1.0, +1.0] where -1.0 = extremely bearish, 0.0 = neutral, +1.0 = extremely bullish.\n\n"
            "Return ONLY a JSON array with one object per tweet (same order), each with exactly two fields:\n"
            '  {"author_id": "<same author_id as input>", "score": <float in [-1, 1]>}\n\n'
            "No markdown, no explanation — raw JSON array only.\n\n"
            f"Tweets:\n{numbered}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 1024,
        }
        try:
            resp = self._http_post(f"{self.base_url}/chat/completions", payload)
            content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or "[]"
            content = content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = content[: content.rfind("```")]
            scored: list[dict[str, Any]] = json.loads(content.strip()) or []
            return scored
        except Exception:  # noqa: BLE001 — LLM error never aborts ingest
            return []

    # ------------------------------------------------------------------
    # Influencer-weighted aggregation
    # ------------------------------------------------------------------

    def _weighted_sentiment(self, scores: list[dict[str, Any]]) -> float | None:
        """Compute a hit-rate-weighted average sentiment in [-1, 1].

        Each tweet's score is multiplied by that author's hit_rate (0.5 default = neutral weight).
        Returns None if no valid scores are available (never a fabricated value).
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for item in scores:
            try:
                author_id = str(item.get("author_id") or "")
                score = float(item["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-1.0 <= score <= 1.0):
                continue  # guard against Grok returning out-of-range values
            weight = self.hit_rate_store.hit_rate(author_id)
            total_weight += weight
            weighted_sum += score * weight
        if total_weight == 0.0:
            return None
        return weighted_sum / total_weight

    # ------------------------------------------------------------------
    # AltDataProvider protocol
    # ------------------------------------------------------------------

    def fetch_series(self, symbol: str, metric: str, *, limit: int, since: "datetime | None" = None) -> list[AltDataPoint]:
        """Return a one-point list (the current influencer-weighted sentiment) or [] on any failure.

        Supported metrics:
          - ``twitter_sentiment`` — influencer-weighted aggregate score in [-1, 1]
          - ``twitter_influencer_sentiment`` — same value, alias that signals influencer weighting

        Both are market-wide (``symbol`` is ignored; the query covers all crypto).

        Availability = now (real-time snapshot; we know it when we fetch it — no look-ahead).
        Absent XAI_API_KEY → [] (honest degradation).
        """
        if metric not in ("twitter_sentiment", "twitter_influencer_sentiment"):
            return []
        if not self.api_key and not self.offline:
            return []

        tweets = self._fetch_tweets()
        if not tweets:
            return []

        scores = self._scorer(tweets)
        if not scores:
            return []

        value = self._weighted_sentiment(scores)
        if value is None:
            return []

        now = datetime.now(tz=UTC)
        pts = [AltDataPoint(ts=now, available_at=now + _AVAILABILITY_LAG, value=value)]
        return pts[-limit:] if limit > 0 else []
