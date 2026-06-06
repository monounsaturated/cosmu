#!/usr/bin/env python3
# intent: one-time, quota-maximising LunarCrush history grab across MULTIPLE asset types (coins, stocks,
# topics, categories) before the plan is cancelled. Robustness-first: every API call is rate-limited,
# counted toward the 2,000/day cap, and recorded in a manifest so the script is fully resumable across
# interruptions or the daily quota reset.  It NEVER spends a call it already made.
#
# Run locally (background):
#   PYTHONPATH=apps/engine python3 scripts/lunarcrush_max_extract.py --dry-run
#   PYTHONPATH=apps/engine python3 scripts/lunarcrush_max_extract.py
#   PYTHONPATH=apps/engine python3 scripts/lunarcrush_max_extract.py --coins 900 --stocks 500 --topics 400 --categories 200
#
# Run on Modal (after `pnpm modal:secret`):
#   modal run scripts/lunarcrush_max_extract.py
#   modal run scripts/lunarcrush_max_extract.py --dry-run
#
# Safety: --dry-run lists every entity + call count, SPENDING ZERO API CALLS.
# The manifest file (.cosmu/lunarcrush_manifest.json) tracks what has been fetched so resuming after a
# daily-quota pause never re-spends a call already made.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — allow `python3 scripts/lunarcrush_max_extract.py`
# without an explicit PYTHONPATH.
# ---------------------------------------------------------------------------
_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.data.providers._types import AltDataPoint, _ssl_context  # noqa: E402
from cosmu.data.providers.store import AltDataStore  # noqa: E402
from cosmu.ingest.pipeline import append_dedup  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROVIDER = "lunarcrush"
BASE_URL = "https://lunarcrush.com/api4/public"

# LunarCrush v4 field names → semantic metric stored in the alt-data store.
# One API call to the time-series endpoint returns ALL of these in a single response.
_COIN_FIELDS: dict[str, str] = {
    "interactions": "social_volume",
    "sentiment": "social_sentiment",
    "galaxy_score": "galaxy_score",
    "alt_rank": "alt_rank",
    "market_cap": "market_cap_usd",
    "volume_24h": "volume_24h_usd",
    "price": "price_usd",
}
_STOCK_FIELDS: dict[str, str] = {
    "interactions": "social_volume",
    "sentiment": "social_sentiment",
    "galaxy_score": "galaxy_score",
    "volume_24h": "volume_24h_usd",
    "price": "price_usd",
}
_TOPIC_FIELDS: dict[str, str] = {
    "interactions": "social_volume",
    "sentiment": "social_sentiment",
    "posts_created": "posts_created",
}
_CATEGORY_FIELDS: dict[str, str] = {
    "interactions": "social_volume",
    "sentiment": "social_sentiment",
}

# Rate-limit: ≤10 req/min → 7 s between calls (leaves safety margin)
SLEEP_BETWEEN_CALLS: float = 7.0
DAILY_QUOTA: int = 2_000
# Exponential backoff config for 429 responses
BACKOFF_INITIAL: float = 60.0
BACKOFF_MAX: float = 600.0
BACKOFF_FACTOR: float = 2.0

# Numerai Crypto live universe (as of 2026; the tokens the model trains/predicts on).
# These get highest priority within the coin bucket so they land first on any interruption.
NUMERAI_CRYPTO_UNIVERSE: tuple[str, ...] = (
    "BTC", "ETH", "BNB", "SOL", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TRX", "LTC", "BCH", "NEAR", "UNI",
    "ATOM", "APT", "ARB", "OP", "FIL",
    "INJ", "SUI", "SEI", "TIA", "AAVE",
    "ETC", "XLM", "ICP", "RUNE", "GALA",
    # Broader Numerai live universe additions
    "MATIC", "FTM", "CRV", "LDO", "PEPE",
    "FLOKI", "SHIB", "WLD", "PYTH", "JTO",
    "RNDR", "FET", "GRT", "SNX", "COMP",
    "MKR", "YFI", "SUSHI", "1INCH", "BAL",
    "ENS", "SAND", "MANA", "AXS", "IMX",
    "FLOW", "THETA", "CHZ", "ENJ", "OMG",
    "ZIL", "QTUM", "IOTA", "ZEC", "DASH",
    "XMR", "EOS", "WAVES", "ALGO", "VET",
    "ONE", "CELO", "ANKR", "RVN", "SC",
    "ZRX", "BAT", "STORJ", "SKL", "OXT",
    "KNC", "BAND", "OCEAN", "IOST", "KAVA",
    "ROSE", "RSR", "HBAR", "HNT", "JASMY",
    "GMT", "SXP", "LUNC", "LUNA", "CFXUSDT",
)

# Cosmu PERP_UNIVERSE (in coin form, no USDT suffix)
PERP_COINS: tuple[str, ...] = (
    "BTC", "ETH", "BNB", "SOL", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TRX", "LTC", "BCH", "NEAR", "UNI",
    "ATOM", "APT", "ARB", "OP", "FIL",
    "INJ", "SUI", "SEI", "TIA", "AAVE",
    "ETC", "XLM", "ICP", "RUNE", "GALA",
)

# ---------------------------------------------------------------------------
# Env loading
# ---------------------------------------------------------------------------

def _load_env_local() -> None:
    """Load .env.local from the repo root so the key is available without dotenv installed."""
    env_path = Path(__file__).resolve().parents[1] / ".env.local"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if v[:1] in ('"', "'"):
            q = v[0]
            end = v.find(q, 1)
            v = v[1:end] if end != -1 else v[1:]
        else:
            pos = v.find(" #")
            if pos != -1:
                v = v[:pos]
            v = v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Manifest — tracks per-entity completion so the script is resumable
# ---------------------------------------------------------------------------

class Manifest:
    """Persist a set of completed entity keys so re-runs skip already-fetched entities.

    Schema: {"done": ["coin:BTC", "stock:AAPL", ...], "calls_today": N, "day": "YYYY-MM-DD"}
    The `calls_today` counter resets each calendar day (UTC), so the daily cap is per-day."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self._load()

    def _today(self) -> str:
        return datetime.now(tz=UTC).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        # Reset daily counter on a new UTC day
        if self._data.get("day") != self._today():
            self._data["calls_today"] = 0
            self._data["day"] = self._today()
        self._data.setdefault("done", [])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))

    def is_done(self, key: str) -> bool:
        return key in self._data["done"]

    def mark_done(self, key: str) -> None:
        if key not in self._data["done"]:
            self._data["done"].append(key)
        self._save()

    @property
    def calls_today(self) -> int:
        return int(self._data.get("calls_today", 0))

    def increment_calls(self, n: int = 1) -> None:
        self._data["calls_today"] = self.calls_today + n
        self._save()

    def done_count(self) -> int:
        return len(self._data["done"])


# ---------------------------------------------------------------------------
# Low-level HTTP with rate-limit / backoff
# ---------------------------------------------------------------------------

_call_count_session: int = 0  # calls this invocation (for logging)


def _http_get(url: str, api_key: str) -> dict:
    """Fetch one URL with Authorization header. Retries on 429 with exponential backoff."""
    backoff = BACKOFF_INITIAL
    while True:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "cosmu-engine/lunarcrush-max-extract",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                print(f"  429 rate-limit hit — sleeping {backoff:.0f}s then retrying …", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * BACKOFF_FACTOR, BACKOFF_MAX)
            else:
                raise
        except Exception:
            raise


# ---------------------------------------------------------------------------
# Entity-list fetchers (these discover WHAT to fetch, not the time-series)
# ---------------------------------------------------------------------------

def _list_coins(api_key: str, limit: int = 900) -> list[dict]:
    """GET /coins/list/v2 — top coins by LunarCrush score, up to `limit`."""
    url = f"{BASE_URL}/coins/list/v2?{urllib.parse.urlencode({'sort': 'galaxy_score', 'limit': min(limit, 4000)})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])[:limit]


def _list_stocks(api_key: str, limit: int = 500) -> list[dict]:
    """GET /stocks/list/v2 — top stocks by social volume."""
    url = f"{BASE_URL}/stocks/list/v2?{urllib.parse.urlencode({'sort': 'galaxy_score', 'limit': min(limit, 4000)})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])[:limit]


def _list_topics(api_key: str, limit: int = 400) -> list[dict]:
    """GET /topics/list/v1 — top narrative topics."""
    url = f"{BASE_URL}/topics/list/v1?{urllib.parse.urlencode({'sort': 'interactions', 'limit': min(limit, 2000)})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])[:limit]


def _list_categories(api_key: str, limit: int = 200) -> list[dict]:
    """GET /categories/list/v1 — all categories (usually <200)."""
    url = f"{BASE_URL}/categories/list/v1?{urllib.parse.urlencode({'sort': 'interactions', 'limit': min(limit, 1000)})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])[:limit]


# ---------------------------------------------------------------------------
# Time-series fetchers (these spend the precious quota — 1 call each)
# ---------------------------------------------------------------------------

def _rows_to_points(rows: list[dict], fields: dict[str, str], now: datetime) -> dict[str, list[AltDataPoint]]:
    """Convert raw API time-series rows → {metric: [AltDataPoint, …]}. available_at = ts + 1 day (PIT)."""
    out: dict[str, list[AltDataPoint]] = {m: [] for m in fields.values()}
    for row in rows:
        ts_raw = row.get("time")
        if ts_raw is None:
            continue
        ts = datetime.fromtimestamp(int(ts_raw), tz=UTC)
        available = ts + timedelta(days=1)
        for native, metric in fields.items():
            val = row.get(native)
            if val is None:
                continue
            try:
                out[metric].append(AltDataPoint(ts=ts, available_at=available, value=float(val)))
            except (TypeError, ValueError):
                pass
    return out


def _fetch_coin_series(api_key: str, coin: str) -> list[dict]:
    url = f"{BASE_URL}/coins/{urllib.parse.quote(coin)}/time-series/v2?{urllib.parse.urlencode({'bucket': 'day'})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])


def _fetch_stock_series(api_key: str, ticker: str) -> list[dict]:
    url = f"{BASE_URL}/stocks/{urllib.parse.quote(ticker)}/time-series/v1?{urllib.parse.urlencode({'bucket': 'day'})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])


def _fetch_topic_series(api_key: str, topic: str) -> list[dict]:
    url = f"{BASE_URL}/topics/{urllib.parse.quote(topic)}/time-series/v1?{urllib.parse.urlencode({'bucket': 'day'})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])


def _fetch_category_series(api_key: str, category: str) -> list[dict]:
    url = f"{BASE_URL}/categories/{urllib.parse.quote(category)}/time-series/v1?{urllib.parse.urlencode({'bucket': 'day'})}"
    payload = _http_get(url, api_key)
    return payload.get("data", [])


# ---------------------------------------------------------------------------
# Core extraction loop
# ---------------------------------------------------------------------------

class Extractor:
    def __init__(
        self,
        api_key: str,
        store: AltDataStore,
        manifest: Manifest,
        daily_quota: int = DAILY_QUOTA,
        sleep_between: float = SLEEP_BETWEEN_CALLS,
        dry_run: bool = False,
    ) -> None:
        self.api_key = api_key
        self.store = store
        self.manifest = manifest
        self.daily_quota = daily_quota
        self.sleep_between = sleep_between
        self.dry_run = dry_run
        self._now = datetime.now(tz=UTC)
        self._last_gated = False  # True when a fetch fails because the endpoint isn't on this plan (auth/plan)
        self._last_dead = False   # True when a single entity 404s (untracked) — skip it, don't abort the bucket

    def _calls_remaining(self) -> int:
        return self.daily_quota - self.manifest.calls_today

    def _spend(self, key: str, entity_type: str, entity_id: str, fields: dict[str, str], fetch_fn: Any) -> bool:
        """Fetch one entity's full time-series, store it, mark the manifest, sleep.
        Returns True if a real API call was made, False if skipped."""
        if self.manifest.is_done(key):
            return False
        if self._calls_remaining() <= 0:
            print(f"  QUOTA EXHAUSTED ({self.manifest.calls_today}/{self.daily_quota} today) — stopping. Resume tomorrow.", flush=True)
            return False  # caller should stop too

        if self.dry_run:
            print(f"  [DRY-RUN] would fetch {entity_type}:{entity_id} ({len(fields)} metrics)", flush=True)
            return True  # counts toward the preview count but hits no API

        self._last_gated = False
        self._last_dead = False
        try:
            rows = fetch_fn(self.api_key, entity_id)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 402, 403):
                # Auth/plan gate: the WHOLE endpoint is unavailable on this plan. Do NOT mark done or burn
                # quota — signal the caller to skip the bucket so a higher-tier re-run can still fetch it.
                print(f"  GATED ({exc.code}) {entity_type}:{entity_id} — endpoint not on this plan", flush=True)
                self._last_gated = True
                return False
            # 404 / other: a SINGLE dead-or-untracked entity (e.g. a coin LunarCrush doesn't cover, or a
            # Binance ticker with no LunarCrush series). Mark done so a resume won't retry it, then keep going
            # — one missing entity must never abort the whole bucket.
            print(f"  ERROR fetching {entity_type}:{entity_id}: {exc}", flush=True)
            self.manifest.mark_done(key)
            self.manifest.increment_calls()
            self._last_dead = True
            return True
        except Exception as exc:  # noqa: BLE001 — one dead entity never aborts the pass
            print(f"  ERROR fetching {entity_type}:{entity_id}: {exc}", flush=True)
            self.manifest.mark_done(key)
            self.manifest.increment_calls()
            self._last_dead = True
            return True

        by_metric = _rows_to_points(rows, fields, self._now)
        total_new = 0
        for metric, points in by_metric.items():
            if points:
                n = append_dedup(self.store, PROVIDER, entity_id, metric, points)
                total_new += n
        self.manifest.mark_done(key)
        self.manifest.increment_calls()
        return True

    def _run_bucket(
        self,
        label: str,
        entities: list[tuple[str, str]],  # [(key, entity_id), ...]
        fields: dict[str, str],
        fetch_fn: Any,
        total_planned: int,
        running_idx: int,
    ) -> tuple[int, int]:
        """Process one bucket (coins/stocks/topics/categories). Returns (calls_spent, new_running_idx)."""
        calls_spent = 0
        consec_dead = 0  # consecutive 404s with zero successes → the endpoint isn't on this plan
        for key, entity_id in entities:
            if not self.dry_run and self._calls_remaining() <= 0:
                print(f"\nQUOTA EXHAUSTED. Resume tomorrow — {self.manifest.done_count()} entities complete.", flush=True)
                break

            running_idx += 1
            already_done = self.manifest.is_done(key) and not self.dry_run
            status = "SKIP" if already_done else ("DRY-RUN" if self.dry_run else "fetch")
            pct = f"{running_idx}/{total_planned}"
            remaining = self._calls_remaining() if not self.dry_run else (self.daily_quota - calls_spent)
            print(f"[{pct}] {label}:{entity_id}  status={status}  quota_left={remaining}", end="" if status == "fetch" else "\n", flush=True)

            if already_done:
                continue

            made_call = self._spend(key, label, entity_id, fields, fetch_fn)
            if self._last_gated:
                if calls_spent == 0:
                    print(f"  → '{label}' endpoints are not on this plan — skipping the whole {label} bucket "
                          f"(no quota burned). Upgrade to Builder to fetch these.", flush=True)
                    break
                self.manifest.mark_done(key)  # gated after a success is odd; skip this one and keep going
                continue
            if made_call:
                if self._last_dead:
                    consec_dead += 1
                    # A bucket that only ever 404s (never a single hit) isn't on this plan → bail it cheaply.
                    if calls_spent == 0 and consec_dead >= 8:
                        print(f"  → '{label}' returned only 404s ({consec_dead} in a row, 0 hits) — endpoint "
                              f"not on this plan; skipping bucket.", flush=True)
                        break
                else:
                    calls_spent += 1
                    consec_dead = 0
                if not self.dry_run:
                    print(f"  rows_fetched=done  calls_today={self.manifest.calls_today}", flush=True)
                    if running_idx < total_planned:
                        time.sleep(self.sleep_between)
        return calls_spent, running_idx


def _prioritise_coins(all_coin_ids: list[str]) -> list[str]:
    """Return coins in priority order: Numerai Crypto + PERP first, then the rest."""
    priority_set = set(NUMERAI_CRYPTO_UNIVERSE) | set(PERP_COINS)
    # Preserve original rank for the rest
    priority = [c for c in all_coin_ids if c.upper() in priority_set]
    rest = [c for c in all_coin_ids if c.upper() not in priority_set]
    seen: set[str] = set()
    out: list[str] = []
    for c in priority + rest:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def run_extract(
    api_key: str,
    store: AltDataStore,
    manifest: Manifest,
    n_coins: int = 900,
    n_stocks: int = 500,
    n_topics: int = 400,
    n_categories: int = 200,
    coins_extra: list[str] | None = None,  # explicit coin symbols (e.g. full Binance universe) — skips discovery
    dry_run: bool = False,
    daily_quota: int = DAILY_QUOTA,
    sleep_between: float = SLEEP_BETWEEN_CALLS,
) -> dict[str, int]:
    """Top-level extraction. Returns {bucket: calls_made}."""
    extractor = Extractor(api_key, store, manifest, daily_quota=daily_quota, sleep_between=sleep_between, dry_run=dry_run)

    # ------------------------------------------------------------------ #
    # Phase 0: discover entity lists (these burn ~4 discovery calls)       #
    # ------------------------------------------------------------------ #
    total_budget = n_coins + n_stocks + n_topics + n_categories
    print(f"\nLunarCrush MAX extract — {'DRY-RUN' if dry_run else 'LIVE'}  budget={total_budget} calls  quota_remaining={extractor._calls_remaining()}", flush=True)
    print(f"Manifest: {manifest.path}  done_so_far={manifest.done_count()}  calls_today={manifest.calls_today}", flush=True)
    print()

    # ---- COINS ----
    coins_calls = 0
    if n_coins > 0 and (dry_run or extractor._calls_remaining() > 0):
        if coins_extra:
            # Explicit universe (e.g. every Binance USDT-spot base asset) ∪ the curated Numerai+PERP set.
            # Skips the discovery call entirely (it's 402-gated on Individual anyway). Untracked coins 404
            # and are skipped one-by-one (see _run_bucket), so over-supplying symbols is safe.
            merged = list(dict.fromkeys([*NUMERAI_CRYPTO_UNIVERSE, *coins_extra]))
            coin_ids = _prioritise_coins(merged)
            print(f"--- Using injected coin universe: {len(coin_ids)} unique coins (discovery skipped)", flush=True)
        else:
            print(f"--- Discovering top {n_coins} coins (1 discovery call) …", flush=True)
            if not dry_run:
                try:
                    raw_coins = _list_coins(api_key, n_coins)
                    extractor.manifest.increment_calls()  # the list call itself
                    coin_ids = _prioritise_coins([c.get("symbol", "") for c in raw_coins if c.get("symbol")])
                except Exception as e:  # noqa: BLE001 — discovery endpoint gated on the Individual plan (HTTP 402)
                    print(f"  [coins/list gated on this plan: {e}] → curated Numerai+PERP universe", flush=True)
                    coin_ids = _prioritise_coins(list(NUMERAI_CRYPTO_UNIVERSE))
            else:
                # In dry-run, synthesise a representative preview list
                coin_ids = list(NUMERAI_CRYPTO_UNIVERSE[:n_coins])
        coin_entities = [(f"coin:{cid}", cid) for cid in coin_ids[:n_coins]]
        coins_calls, idx = extractor._run_bucket("coin", coin_entities, _COIN_FIELDS, _fetch_coin_series, total_budget, 0)
    else:
        idx = 0

    # ---- STOCKS ----
    stocks_calls = 0
    if n_stocks > 0 and (dry_run or extractor._calls_remaining() > 0):
        print(f"\n--- Discovering top {n_stocks} stocks (1 discovery call) …", flush=True)
        _curated_stocks = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "JPM", "BRK.B", "V",
                           "AMD", "INTC", "NFLX", "DIS", "BA", "COIN", "MSTR", "PYPL", "SQ", "HOOD",
                           "GME", "AMC", "PLTR", "SOFI", "RIVN", "F", "GM", "UBER", "ABNB", "SHOP"]
        if not dry_run:
            try:
                raw_stocks = _list_stocks(api_key, n_stocks)
                extractor.manifest.increment_calls()
                stock_ids = [s.get("symbol", "") for s in raw_stocks if s.get("symbol")]
            except Exception as e:  # noqa: BLE001 — discovery gated (HTTP 402) on Individual
                print(f"  [stocks/list gated: {e}] → curated top stocks", flush=True)
                stock_ids = _curated_stocks[:n_stocks]
        else:
            stock_ids = _curated_stocks[:n_stocks]
        stock_entities = [(f"stock:{sid}", sid) for sid in stock_ids[:n_stocks]]
        stocks_calls, idx = extractor._run_bucket("stock", stock_entities, _STOCK_FIELDS, _fetch_stock_series, total_budget, idx)

    # ---- TOPICS ----
    topics_calls = 0
    if n_topics > 0 and (dry_run or extractor._calls_remaining() > 0):
        print(f"\n--- Discovering top {n_topics} topics (1 discovery call) …", flush=True)
        _curated_topics = ["bitcoin", "ethereum", "solana", "artificial-intelligence", "defi", "nft",
                           "web3", "metaverse", "memecoins", "stablecoins", "layer-2", "rwa", "depin",
                           "gaming", "ai-agents", "etf", "federal-reserve", "inflation", "stocks", "tesla"]
        if not dry_run:
            try:
                raw_topics = _list_topics(api_key, n_topics)
                extractor.manifest.increment_calls()
                topic_ids = [t.get("topic", t.get("id", "")) for t in raw_topics if t.get("topic") or t.get("id")]
            except Exception as e:  # noqa: BLE001 — discovery gated (HTTP 402) on Individual
                print(f"  [topics/list gated: {e}] → curated top topics", flush=True)
                topic_ids = _curated_topics[:n_topics]
        else:
            topic_ids = _curated_topics[:n_topics]
        topic_entities = [(f"topic:{tid}", tid) for tid in topic_ids[:n_topics]]
        topics_calls, idx = extractor._run_bucket("topic", topic_entities, _TOPIC_FIELDS, _fetch_topic_series, total_budget, idx)

    # ---- CATEGORIES ----
    categories_calls = 0
    if n_categories > 0 and (dry_run or extractor._calls_remaining() > 0):
        print(f"\n--- Discovering top {n_categories} categories (1 discovery call) …", flush=True)
        _curated_cats = ["layer-1", "defi", "layer-2", "meme", "ai-tokens", "gaming", "rwa", "depin",
                         "stablecoins", "exchange-tokens", "liquid-staking", "oracle"]
        if not dry_run:
            try:
                raw_categories = _list_categories(api_key, n_categories)
                extractor.manifest.increment_calls()
                category_ids = [c.get("category", c.get("id", "")) for c in raw_categories if c.get("category") or c.get("id")]
            except Exception as e:  # noqa: BLE001 — discovery gated (HTTP 402) on Individual
                print(f"  [categories/list gated: {e}] → curated categories", flush=True)
                category_ids = _curated_cats[:n_categories]
        else:
            category_ids = _curated_cats[:n_categories]
        cat_entities = [(f"category:{cid}", cid) for cid in category_ids[:n_categories]]
        categories_calls, idx = extractor._run_bucket("category", cat_entities, _CATEGORY_FIELDS, _fetch_category_series, total_budget, idx)

    summary = {
        "coins": coins_calls,
        "stocks": stocks_calls,
        "topics": topics_calls,
        "categories": categories_calls,
    }
    total = sum(summary.values())
    print(f"\n{'='*60}", flush=True)
    print(f"DONE  total_calls_this_run={total}  calls_today={manifest.calls_today}/{daily_quota}", flush=True)
    for k, v in summary.items():
        print(f"  {k:<12}: {v} calls", flush=True)
    print(f"  manifest: {manifest.path}", flush=True)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "LunarCrush MAX extract — one-time, quota-sensitive, resumable grab of full social-intelligence "
            "history for coins, stocks, topics, and categories.  Use --dry-run first to preview."
        )
    )
    p.add_argument("--coins",      type=int, default=900, help="max coin entities to fetch (default 900)")
    p.add_argument("--coins-file", default=None, help="newline-separated coin symbols to fetch (e.g. full Binance USDT-spot universe); unioned with the curated set, skips discovery")
    # Stocks/topics/categories are Builder-plan-only (they 404 on Individual). Default OFF so a bare run is
    # coins-only; pass explicit counts for a one-day Builder mega-grab. A gated bucket also self-aborts (below).
    p.add_argument("--stocks",     type=int, default=0, help="max stock entities (Builder plan only; default 0)")
    p.add_argument("--topics",     type=int, default=0, help="max topic entities (Builder plan only; default 0)")
    p.add_argument("--categories", type=int, default=0, help="max category entities (Builder plan only; default 0)")
    p.add_argument("--quota",      type=int, default=DAILY_QUOTA, help=f"daily API call cap (default {DAILY_QUOTA})")
    p.add_argument("--sleep",      type=float, default=SLEEP_BETWEEN_CALLS, help=f"seconds between calls (default {SLEEP_BETWEEN_CALLS})")
    p.add_argument("--store",      default=".cosmu/altdata", help="alt-data store root directory")
    p.add_argument("--manifest",   default=".cosmu/lunarcrush_manifest.json", help="progress manifest path")
    p.add_argument("--dry-run",    action="store_true", help="preview only — ZERO API calls, shows what would be fetched")
    p.add_argument("--local",      action="store_true", help="force local JSONL store even if DATABASE_URL is set (default: Postgres/Supabase when DATABASE_URL present)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _load_env_local()

    args = _parse_args(argv)

    api_key = os.environ.get("LUNARCRUSH_API_KEY", "")
    if not api_key:
        print("ERROR: LUNARCRUSH_API_KEY is not set. Export it or add it to .env.local.", file=sys.stderr)
        if not args.dry_run:
            return 1
        print("(continuing in dry-run mode without a key — API shapes assumed correct)", file=sys.stderr)

    # Route to Postgres/Supabase (the prod DB the engine/backtest/Numerai read) when DATABASE_URL is
    # set — local JSONL is Mac-only and the deployed machine can't see it. --local forces JSONL.
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url and not args.local and not args.dry_run:
        from cosmu.knowledge.store import Store  # noqa: E402
        from cosmu.config.settings import get_settings  # noqa: E402
        from cosmu.data.providers.store import PgAltDataStore  # noqa: E402
        store = PgAltDataStore(Store(get_settings()))
        print("→ store: Postgres/Supabase (DATABASE_URL set)", flush=True)
    else:
        store = AltDataStore(args.store)
        print(f"→ store: local JSONL ({args.store})", flush=True)
    manifest = Manifest(Path(args.manifest))

    coins_extra: list[str] | None = None
    if args.coins_file:
        with open(args.coins_file) as fh:
            coins_extra = [ln.strip().upper() for ln in fh if ln.strip() and not ln.startswith("#")]
        print(f"→ coins-file: {len(coins_extra)} symbols from {args.coins_file}", flush=True)

    run_extract(
        api_key=api_key,
        store=store,
        manifest=manifest,
        n_coins=args.coins,
        n_stocks=args.stocks,
        n_topics=args.topics,
        n_categories=args.categories,
        coins_extra=coins_extra,
        dry_run=args.dry_run,
        daily_quota=args.quota,
        sleep_between=args.sleep,
    )
    return 0


# ---------------------------------------------------------------------------
# Modal entrypoint (thin wrapper — same code, bigger compute)
# ---------------------------------------------------------------------------

try:
    import modal as _modal  # noqa: E402

    _app = _modal.App("cosmu-lunarcrush-extract")

    _ENGINE_DIR = Path(__file__).resolve().parents[1] / "apps" / "engine"
    _image = (
        _modal.Image.debian_slim(python_version="3.12")
        .add_local_dir(
            str(_ENGINE_DIR),
            remote_path="/root/engine",
            copy=True,
            ignore=["**/__pycache__", "**/*.pyc", "tests/**", "remote/**"],
        )
        .add_local_file(__file__, remote_path="/root/lunarcrush_max_extract.py")
        .run_commands("pip install /root/engine")
    )
    _secret = _modal.Secret.from_name("cosmu-engine")
    _VOLUME = _modal.Volume.from_name("cosmu-altdata", create_if_missing=True)
    _STORE_PATH = "/mnt/altdata"
    _MANIFEST_PATH = "/mnt/altdata/lunarcrush_manifest.json"

    @_app.function(
        image=_image,
        secrets=[_secret],
        volumes={_STORE_PATH: _VOLUME},
        timeout=60 * 60 * 6,  # 6 h max (the full run)
        cpu=1.0,
        memory=512,
    )
    def extract_remote(
        coins: int = 900,
        stocks: int = 500,
        topics: int = 400,
        categories: int = 200,
        dry_run: bool = False,
        quota: int = DAILY_QUOTA,
    ) -> dict[str, int]:
        import os as _os
        import sys as _sys
        _sys.path.insert(0, "/root/engine")

        # Re-import inside the remote container
        from cosmu.data.providers.store import AltDataStore as _ADS  # type: ignore[import]
        from cosmu.ingest.pipeline import append_dedup as _adup  # type: ignore[import]  # noqa: F401

        api_key = _os.environ.get("LUNARCRUSH_API_KEY", "")
        if not api_key and not dry_run:
            print("ERROR: LUNARCRUSH_API_KEY missing in Modal secret", flush=True)
            return {}

        _store = _ADS(_STORE_PATH)
        _manifest = Manifest(Path(_MANIFEST_PATH))
        return run_extract(
            api_key=api_key,
            store=_store,
            manifest=_manifest,
            n_coins=coins,
            n_stocks=stocks,
            n_topics=topics,
            n_categories=categories,
            dry_run=dry_run,
            daily_quota=quota,
        )

    @_app.local_entrypoint()
    def modal_main(
        coins: int = 900,
        stocks: int = 500,
        topics: int = 400,
        categories: int = 200,
        dry_run: bool = False,
        quota: int = DAILY_QUOTA,
    ) -> None:
        """modal run scripts/lunarcrush_max_extract.py [--dry-run] [--coins N …]"""
        result = extract_remote.remote(
            coins=coins, stocks=stocks, topics=topics,
            categories=categories, dry_run=dry_run, quota=quota,
        )
        print(f"[modal] done: {result}")

except ImportError:
    pass  # Modal not installed — local-only mode, no-op


if __name__ == "__main__":
    raise SystemExit(main())
