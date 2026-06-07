# intent: the LLM-NARRATIVE feature factory — turn RAW unstructured news TEXT (GDELT headlines, free + keyless
# + point-in-time) into ONE typed daily numeric signal (net narrative pressure ∈ [-1,1]) by scoring EACH
# headline with our own OpenRouter LLM, CONTENT-ONLY, as-of its publish timestamp; inputs: a symbol + a GDELT
# raw-headline pull; outputs: a PIT daily AltDataPoint series (available_at = day close + 1 day) the existing
# backtest reads under the feature name `news_event_score`; invariants: the LLM scores ONLY the headline text
# (never the outcome, never "what happened after"), each item is stamped with its OWN publish_time (PIT), the
# scoring is deterministic (temperature 0) + disk-cached by content hash (so the LLM bill is paid ONCE and
# reruns are free), and the LLM is NEVER on the gate/scoring/money path — it only standardizes text at ingest,
# exactly like the deterministic lexicon it can fall back to.
#
# THE LOOK-AHEAD TRAP: an LLM has read the future. The ONLY defense is to forbid it from reasoning about the
# outcome and to feed it ONLY the headline content. The prompt is content-only; the disconfirmer that
# time-shuffles these scores (in llm_narrative_cohort.py) is the empirical check that no leakage survived.
#
# Transport note: this module uses a certifi-backed SSL context directly (NOT cosmu.lab.llm.openrouter_chat,
# which omits the SSL context and so silently returns None on macOS — see the spawned fix-task). The scoring
# contract (typed sign/magnitude/confidence, extra="forbid", retry-on-invalid) is reused from llm_formatter.

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from cosmu.data.altdata import AltDataPoint, NewsItem
from cosmu.ingest.llm_formatter import ALLOWED_CATEGORIES, TypedFeature

# Cheap tier — formatting one headline into a tiny JSON object needs no frontier model. ~$2.5e-06/call observed.
DEFAULT_MODEL = "openai/gpt-4o-mini"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Frozen prompt+schema version pinned into the cached score, so a survivor stays reproducible and a prompt
# change invalidates the cache (a new version key) rather than silently reusing stale scores.
NARRATIVE_TRANSFORM_VERSION = "llm-narrative-v1"

# The feature name the backtest/specs read. Reusing the existing `news_event_score` name means the LLM-narrative
# series flows through the SAME alt-join + gate path as any other typed event signal.
NARRATIVE_FEATURE = "news_event_score"

_DEFAULT_CACHE = Path(".cosmu/llm_narrative")


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# --------------------------------------------------------------------------- content-only PIT scoring prompt


def _score_prompt(headline: str) -> str:
    """Content-ONLY market-narrative scoring prompt. It deliberately gives the model NO date, NO ticker context,
    NO price, and FORBIDS it from reasoning about what happened next — the only honest defense against an LLM
    that has read the future. It judges the TEXT's own bullish/bearish narrative pressure, nothing else."""
    return (
        "You are a market-narrative formatter. You are shown ONE news headline and NOTHING else — no date, no "
        "price, no outcome. Judge ONLY the bullish/bearish narrative pressure expressed by the TEXT ITSELF.\n"
        "STRICT RULES:\n"
        "  - Do NOT reason about what happened after this headline. You do not know the outcome.\n"
        "  - Do NOT use any knowledge of subsequent price moves, events, or dates.\n"
        "  - Score ONLY the sentiment/narrative the words convey, as a reader would the moment it was published.\n"
        "Reply with ONLY a JSON object, no prose, matching EXACTLY these four fields:\n"
        '{"sign": <-1|0|1>, "magnitude": <float 0..1>, '
        '"category": "<one of: ' + "|".join(ALLOWED_CATEGORIES) + '>", '
        '"confidence": <float 0..1>}\n'
        "sign: +1 bullish / 0 neutral / -1 bearish. magnitude: narrative strength (0 weak, 1 maximum). "
        "Add NO other fields.\n\n"
        f"Headline:\n{headline.strip()}"
    )


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start : end + 1])


class CachedNarrativeScorer:
    """Score a headline into a TypedFeature with a real OpenRouter call (certifi SSL), content-hash disk-cached.

    KEY-GATED: with no key the call returns None (the caller falls back to the deterministic lexicon — honest
    degradation). Deterministic (temperature 0) + `extra="forbid"` validation + retry-on-invalid. The cache key
    is (transform_version, model, sha256(headline)) so a prompt/model change never silently reuses stale scores
    and a repeated headline costs nothing — the LLM bill is paid ONCE."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        cache_dir: Path | str = _DEFAULT_CACHE,
        max_retries: int = 2,
        timeout: float = 40.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0  # live LLM calls made this run (cache hits don't count) — bounds the bill
        self.cost_usd = 0.0

    def _cache_path(self, headline: str) -> Path:
        h = hashlib.sha256(f"{NARRATIVE_TRANSFORM_VERSION}|{self.model}|{headline}".encode()).hexdigest()
        return self.cache_dir / f"{h}.json"

    def _chat(self, prompt: str) -> str | None:
        if not self.api_key:
            return None
        body = json.dumps(
            {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        ).encode("utf-8")
        req = urllib.request.Request(
            _OPENROUTER_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "Cosmu LLM-Narrative",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_ctx()) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        usage = payload.get("usage") or {}
        self.cost_usd += float(usage.get("cost") or 0.0)
        choices = payload.get("choices") or []
        return choices[0].get("message", {}).get("content") if choices else None

    def __call__(self, headline: str) -> TypedFeature | None:
        cp = self._cache_path(headline)
        if cp.exists():
            try:
                return TypedFeature.model_validate(json.loads(cp.read_text()))
            except Exception:  # noqa: BLE001 — corrupt cache entry → rescore
                pass
        if not self.api_key:
            return None
        last_err = ""
        for _ in range(max(1, self.max_retries) + 1):
            prompt = _score_prompt(headline)
            if last_err:
                prompt += f"\n\nYour previous reply was invalid ({last_err}). Reply with corrected JSON only."
            try:
                raw = self._chat(prompt)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                return None  # transport failure → deterministic fallback (never a fabricated feature)
            self.calls += 1
            if raw is None:
                return None
            try:
                tf = TypedFeature.model_validate(_extract_json(raw))
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)[:160]
                continue
            cp.write_text(tf.model_dump_json())
            return tf
        return None


# --------------------------------------------------------------------------- GDELT raw-headline pull (PIT)


@dataclass(frozen=True)
class GdeltPullStats:
    symbol: str
    query: str
    articles: int
    days: int
    earliest: str
    latest: str


_GDELT_NAMES = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "DOGE": "dogecoin"}


def _gdelt_query(symbol: str) -> str:
    coin = symbol[:-4] if symbol.upper().endswith("USDT") else symbol
    return _GDELT_NAMES.get(coin.upper(), f"{coin} crypto")


def _parse_gdelt_date(raw: str) -> _dt.datetime | None:
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return _dt.datetime.strptime(raw, fmt).replace(tzinfo=_dt.UTC)
        except ValueError:
            continue
    return None


def fetch_gdelt_headlines(
    symbol: str,
    *,
    days_back: int = 90,
    slice_days: int = 3,
    max_per_slice: int = 250,
    polite_sleep: float = 3.0,
    max_retries: int = 4,
    cache_dir: Path | str = _DEFAULT_CACHE,
) -> list[NewsItem]:
    """Crawl the GDELT 2.0 doc API (free, keyless) for raw headlines about `symbol` over the last `days_back`
    days, in `slice_days`-day windows (each capped at `max_per_slice`). Each NewsItem is stamped point-in-time:
    `ts == available_at == seendate` (GDELT's index time — we knew the headline then, never before). Polite
    pacing + backoff respect GDELT's rate limit. The full pull is cached to disk so the (slow) crawl runs ONCE.

    GDELT's free doc API only covers a rolling ~3-month window — that depth limit is the binding constraint on
    this first cut (reported honestly upstream); it is NOT a look-ahead issue."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"gdelt_{symbol}_{days_back}d.jsonl"
    if cache_file.exists():
        items = []
        for line in cache_file.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            ts = _dt.datetime.fromisoformat(d["ts"])
            items.append(NewsItem(ts=ts, available_at=ts, headline=d["headline"]))
        return sorted(items, key=lambda n: n.ts)

    ctx = _ssl_ctx()
    query = _gdelt_query(symbol)
    end = _dt.datetime.now(_dt.UTC)
    start = end - _dt.timedelta(days=days_back)
    seen: dict[str, NewsItem] = {}  # dedupe by (seendate|title)
    cur = start
    while cur < end:
        s, e = cur, min(cur + _dt.timedelta(days=slice_days), end)
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": max_per_slice,
            "startdatetime": s.strftime("%Y%m%d%H%M%S"),
            "enddatetime": e.strftime("%Y%m%d%H%M%S"),
            "sort": "DateAsc",
        }
        url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)
        payload = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
                with urllib.request.urlopen(req, timeout=40, context=ctx) as r:  # noqa: S310
                    payload = json.loads(r.read().decode("utf-8"))
                break
            except Exception:  # noqa: BLE001 — 429/transient → backoff; a dead slice is just skipped
                time.sleep(polite_sleep * (attempt + 2))
        if payload:
            for art in payload.get("articles", []) or []:
                title = (art.get("title") or "").strip()
                sd = art.get("seendate")
                if not title or not sd:
                    continue
                ts = _parse_gdelt_date(sd)
                if ts is None:
                    continue
                key = f"{sd}|{title}"
                if key not in seen:
                    seen[key] = NewsItem(ts=ts, available_at=ts, headline=title)
        cur = e
        time.sleep(polite_sleep)

    items = sorted(seen.values(), key=lambda n: n.ts)
    with cache_file.open("w") as fh:
        for it in items:
            fh.write(json.dumps({"ts": it.ts.isoformat(), "headline": it.headline}) + "\n")
    return items


# --------------------------------------------------------------------------- headlines → daily PIT signal


def _day_key(ts: _dt.datetime) -> _dt.date:
    return ts.astimezone(_dt.UTC).date()


def score_headlines_to_daily(
    items: list[NewsItem],
    scorer: CachedNarrativeScorer,
    *,
    min_items_per_day: int = 1,
) -> list[AltDataPoint]:
    """Score EACH headline content-only/PIT, then aggregate to ONE daily 'net narrative pressure' point.

    For each calendar day D, the value is the confidence-weighted mean of that day's headline scores
    (sign*magnitude, weighted by confidence) ∈ [-1,1]. `available_at = end-of-day D + 1 day` — a day's news is
    closed only once the day ends; the next-day floor means a bar at day t reads only narrative from days <= t-1
    (strictly point-in-time, no look-ahead). A day with no usable score simply produces no point (honest absence).
    Headlines with a None score (no key / invalid) are dropped, never zero-filled."""
    by_day: dict[_dt.date, list[tuple[float, float]]] = defaultdict(list)  # day -> [(score, confidence)]
    for it in items:
        tf = scorer(it.headline)
        if tf is None:
            continue
        by_day[_day_key(it.ts)].append((tf.score, tf.confidence))

    points: list[AltDataPoint] = []
    for day in sorted(by_day):
        rows = by_day[day]
        if len(rows) < min_items_per_day:
            continue
        wsum = sum(c for _, c in rows)
        if wsum <= 0:
            value = sum(s for s, _ in rows) / len(rows)  # no confidence signal → plain mean
        else:
            value = sum(s * c for s, c in rows) / wsum
        # observation time = end of day D (UTC midnight of D); availability = next day (PIT floor).
        ts = _dt.datetime(day.year, day.month, day.day, tzinfo=_dt.UTC)
        points.append(AltDataPoint(ts=ts, available_at=ts + _dt.timedelta(days=1), value=round(value, 6)))
    return points
