# intent: the BELIEF-INTENSITY loader — daily Wikipedia pageviews from the Wikimedia REST "pageviews" API as a
# clean, point-in-time, NON-revised proxy for retail astrology attention. This is the ONE genuinely new data
# instrument the astro-belief experiment needs (Mercury-retrograde dummy comes free from `ephem`; prices come
# from real_panel). Why this source:
#
#   * NO KEY, free, public — same $0/PIT-honest posture as the alternative.me Fear&Greed loader.
#   * NON-REVISED + LATE-BOUND: the count for UTC day t is finalized ~1 day later and then frozen forever. We
#     therefore treat a pageview value as available_at = t + PUBLISH_LAG_DAYS (default 1), so the backtest can
#     only act on belief intensity it could ACTUALLY have observed. A future revision cannot reach a past bar
#     because there are no revisions (unlike Google-Trends SVI, which renormalizes the whole history — the
#     classic look-ahead trap the plan calls out).
#   * Daily granularity from 2015-07-01 (the API's start). ~11 years where data allows.
#
# The Wikimedia API auto-resolves redirects to the canonical article, so a belief TOPIC maps to whatever real
# article carries that attention (e.g. the "Mercury retrograde" page redirects to "Apparent retrograde motion").
# We record the resolved article alongside the topic so the provenance is explicit.
#
# PERSISTENCE: every fetched series is written to R2 (cosmu-lake/astro_lab/belief/) AND a local parquet mirror
# via LabStore, and re-reads come from there — a heavy fetch is never wasted or repeated (the plan's rule).

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE_ROOT / "scripts" / "research" / "astro_strategy_lab"))

_REST = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
_UA = "cosmu-research/0.1 (github.com/monounsaturated/cosmu)"
PUBLISH_LAG_DAYS = 1  # a day-t count is observable only at t+1 (the API finalizes ~24h late) → PIT-honest

# The belief TOPICS the plan names. Value is the article the Wikimedia API actually serves (after redirect
# resolution). "Mercury retrograde" is not a standalone article — it redirects to Apparent_retrograde_motion,
# which is the page that demonstrably spikes during each Mercury-retrograde window (verified live).
BELIEF_TOPICS: dict[str, str] = {
    "Mercury_retrograde": "Apparent_retrograde_motion",
    "Astrology": "Astrology",
    "Full_moon": "Full_moon",
}


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _store():
    from lab_store import LabStore

    return LabStore(prefix="astro_lab/belief", local_dir=".cosmu/astro_lab/belief")


def _fetch_article_daily(article: str, start: str, end: str) -> pd.Series:
    """RAW daily pageviews for one resolved article over [start,end] (YYYYMMDD). tz-naive UTC DatetimeIndex
    of the OBSERVATION day t (the day traffic happened); float views. Missing days are simply absent (honest —
    the API omits zero-traffic / pre-existence days). 404 = no data → empty series, never fabricated."""
    q = urllib.parse.quote(article, safe="")
    url = (
        f"{_REST}/en.wikipedia/all-access/all-agents/{q}/daily/{start}/{end}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=45, context=_ssl_ctx()) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: PERF203
        if e.code == 404:
            return pd.Series(dtype=float, name=article)
        raise
    rows = []
    for it in raw.get("items", []):
        ts = datetime.strptime(it["timestamp"][:8], "%Y%m%d").replace(tzinfo=UTC).replace(tzinfo=None)
        rows.append((pd.Timestamp(ts).normalize(), float(it["views"])))
    if not rows:
        return pd.Series(dtype=float, name=article)
    s = pd.Series({t: v for t, v in rows}).sort_index()
    s.index.name = "ts"
    s.name = article
    return s


def load_belief_pageviews(
    topics: dict[str, str] | None = None,
    start: str = "20150701",
    end: str | None = None,
    *,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Daily pageviews for each belief TOPIC, as a DataFrame indexed by the OBSERVATION day (tz-naive UTC),
    one float column per topic key (NOT the article — so callers reference the stable topic name). Persisted to
    R2 + local parquet; a cached pull is reused so the fetch is one-and-done.

    NOTE on PIT: this returns counts keyed by the day they were GENERATED. The study shifts each series
    by PUBLISH_LAG_DAYS before using it so it only ever acts on observable belief (see belief_study.py)."""
    topics = topics or BELIEF_TOPICS
    end = end or datetime.now(tz=UTC).strftime("%Y%m%d")
    store = _store()
    batch_id = f"pageviews_{start}_{end}"

    if use_cache:
        local = store.local / f"{batch_id}.parquet"
        try:
            if store.r2_ready:
                con = store._conn()
                df = con.execute(
                    f"SELECT * FROM read_parquet('{store.r2_uri(batch_id)}')"
                ).df()
                con.close()
            elif local.exists():
                df = pd.read_parquet(local)
            else:
                df = None
            if df is not None and not df.empty:
                df = df.set_index(pd.to_datetime(df["ts"])).drop(columns=["ts"])
                df.index.name = "ts"
                # only reuse if every requested topic is present
                if all(t in df.columns for t in topics):
                    return df[list(topics)]
        except Exception:  # noqa: BLE001 — no cache yet / R2 miss → fetch fresh
            pass

    cols: dict[str, pd.Series] = {}
    resolved: dict[str, str] = {}
    for topic, article in topics.items():
        s = _fetch_article_daily(article, start, end)
        cols[topic] = s.rename(topic)
        resolved[topic] = article
        n = int(s.notna().sum())
        span = f"{s.index.min().date()}..{s.index.max().date()}" if n else "EMPTY"
        print(f"  belief[{topic:20s}] article={article:28s} {n:>5} days {span}", flush=True)
        time.sleep(0.4)  # be polite to the public API

    df = pd.concat(cols.values(), axis=1).sort_index()
    df.index.name = "ts"

    # persist (R2 + local) — flatten the index into a column for parquet round-trip
    out = df.reset_index()
    paths = store.save_batch(out, batch_id)
    print(f"  persisted pageviews → {paths}", flush=True)
    # also drop a tiny provenance sidecar so the topic→article mapping is never ambiguous later
    try:
        prov = pd.DataFrame(
            [{"topic": t, "article": a, "start": start, "end": end} for t, a in resolved.items()]
        )
        store.save_batch(prov, f"provenance_{start}_{end}")
    except Exception:  # noqa: BLE001
        pass
    return df


if __name__ == "__main__":
    print("=" * 80)
    print("Wikipedia belief-pageviews loader — fetch + persist (R2 + local)")
    print("=" * 80)
    df = load_belief_pageviews()
    print(f"\nshape: {df.shape}  index {df.index.min().date()}..{df.index.max().date()}")
    print(df.describe().T[["count", "mean", "std", "min", "max"]].to_string())
