# intent: the DEEP raw-text corpus builder for the LLM-narrative axis — pull GDELT GKG (Global Knowledge Graph)
# RAW 15-min files directly from http://data.gdeltproject.org/gdeltv2/ (free, keyless, back to 2015-02), filter
# each row to a LIQUID universe (BTC/ETH + ~10 liquid US equities/ETFs) by entity/organization/theme match, and
# extract the article's own headline (PAGE_TITLE) stamped point-in-time at GDELT's index time. inputs: a date
# range + the universe map; outputs: per-asset NewsItem lists (ts == available_at == GDELT index time, PIT) ready
# for content-only LLM scoring. invariants: the ONLY text fed downstream is the headline (no body, no outcome);
# every item carries GDELT's own index timestamp as its availability (we knew the headline THEN, never before);
# universe matching is conservative (full-name / theme codes, word-boundary equity tickers) to keep the stream
# on-topic; a dead/missing 15-min file is simply skipped (GDELT has occasional gaps — never fabricate a row).
#
# WHY GKG RAW FILES (not the doc API): the free GDELT doc API only covers a rolling ~3-month window and is
# rate-limited — that depth limit blocked the first-cut narrative verdict. The GKG raw files are the SAME data
# at full depth (every 15 min since 2015), downloadable directly with no key and no quota. This is the deep
# corpus the Modal pipeline (remote/gkg_narrative.py) maps over in parallel.

from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass

from cosmu.data.altdata import NewsItem
from cosmu.data.providers._types import _ssl_context

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

_GKG_BASE = "http://data.gdeltproject.org/gdeltv2"

# GKG 2.1 tab-separated column indices (verified against a live file 2026-06-07). Only the few we read:
_COL_DATE = 1        # V2.1 DATE  — "YYYYMMDDHHMMSS", the index time = our point-in-time availability
_COL_THEMES_V1 = 7   # V1 Themes  — ";"-separated theme codes
_COL_THEMES_V2 = 8   # V2 Enhanced Themes — "CODE,offset;..."
_COL_ORGS_V1 = 11    # V1 Organizations — ";"-separated org names
_COL_ORGS_V2 = 12    # V2 Enhanced Organizations — "Name,offset;..."
_COL_ALLNAMES = 23   # V2.1 AllNames — "Name,offset;..." (proper-noun entities the article names)
_COL_EXTRAS = 26     # V2 Extras XML — contains <PAGE_TITLE>...</PAGE_TITLE>, the real headline text
_MIN_FIELDS = 27

_TITLE_RE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)


@dataclass(frozen=True)
class UniverseAsset:
    """One liquid name to track. `names` are lowercase substrings matched against GDELT AllNames/Orgs (proper
    nouns the article actually names). `themes` are GKG theme codes (matched against V1/V2 themes). An equity is
    matched by company name (tickers alone are far too noisy in news text); crypto adds theme codes."""

    symbol: str            # the tradeable symbol the daily signal is keyed under (e.g. "BTCUSDT", "NVDA")
    names: tuple[str, ...]  # lowercase full-name substrings (AllNames / Orgs)
    themes: tuple[str, ...] = ()  # GKG theme codes (exact token match, e.g. "ECON_CRYPTOCURRENCY")
    kind: str = "equity"   # "crypto" | "equity" — drives which bars provider the verdict uses


# The LIQUID first-cut universe. Crypto: the two deepest, most liquid news streams. Equities/ETFs: the most
# news-dense, most liquid US names (the ones GDELT's English corpus actually covers densely). Names are FULL
# company/asset names (word-level), never bare tickers — "apple inc"/"nvidia corp", so a ticker collision in
# unrelated text can't pollute the stream. Crypto also matches the GKG crypto theme codes for breadth.
DEFAULT_UNIVERSE: tuple[UniverseAsset, ...] = (
    UniverseAsset("BTCUSDT", ("bitcoin",), ("ECON_CRYPTOCURRENCY", "WB_2462_CRYPTOCURRENCY"), "crypto"),
    UniverseAsset("ETHUSDT", ("ethereum", "ether ethereum"), (), "crypto"),
    UniverseAsset("AAPL", ("apple inc", "apple computer"), (), "equity"),
    UniverseAsset("MSFT", ("microsoft corp", "microsoft corporation"), (), "equity"),
    UniverseAsset("NVDA", ("nvidia corp", "nvidia corporation"), (), "equity"),
    UniverseAsset("TSLA", ("tesla inc", "tesla motors", "tesla, inc"), (), "equity"),
    UniverseAsset("AMZN", ("amazon.com", "amazon com inc"), (), "equity"),
    UniverseAsset("GOOGL", ("alphabet inc", "google llc"), (), "equity"),
    UniverseAsset("META", ("meta platforms",), (), "equity"),
    # Index ETFs: match the index people NAME in text (not a broad "stock market" theme, which fires on every
    # market story and drowns the asset-specific narrative). These are the tradeable proxies for the index.
    UniverseAsset("SPY", ("s&p 500", "s&p500", "standard & poor's 500"), (), "equity"),
    UniverseAsset("QQQ", ("nasdaq composite", "nasdaq 100", "nasdaq-100"), (), "equity"),
)


def _parse_gkg_date(raw: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.strptime(raw.strip(), "%Y%m%d%H%M%S").replace(tzinfo=_dt.UTC)
    except (ValueError, AttributeError):
        return None


def _theme_tokens(row: list[str]) -> set[str]:
    """The set of bare theme codes in a row (V1 ';'-list + V2 'CODE,offset;' list)."""
    toks: set[str] = set()
    if len(row) > _COL_THEMES_V1:
        toks.update(t for t in row[_COL_THEMES_V1].split(";") if t)
    if len(row) > _COL_THEMES_V2:
        toks.update(part.split(",", 1)[0] for part in row[_COL_THEMES_V2].split(";") if part)
    return toks


def _entity_blob(row: list[str]) -> str:
    """Lowercased concatenation of the article's named entities + organizations (where company/asset names land)."""
    parts = []
    for idx in (_COL_ALLNAMES, _COL_ORGS_V1, _COL_ORGS_V2):
        if len(row) > idx and row[idx]:
            parts.append(row[idx])
    return " ".join(parts).lower()


def classify_row(row: list[str], universe: tuple[UniverseAsset, ...]) -> set[str]:
    """Return the set of universe symbols this GKG row is about. Name match is substring on the proper-noun
    entity blob; theme match is exact token. A row can map to several assets (e.g. a 'big tech earnings' piece)."""
    blob = _entity_blob(row)
    themes = _theme_tokens(row)
    hits: set[str] = set()
    for a in universe:
        if (a.names and any(n in blob for n in a.names)) or (a.themes and themes.intersection(a.themes)):
            hits.add(a.symbol)
    return hits


def _extract_title(row: list[str]) -> str:
    if len(row) <= _COL_EXTRAS:
        return ""
    m = _TITLE_RE.search(row[_COL_EXTRAS])
    return m.group(1).strip() if m else ""


def parse_gkg_bytes(raw_zip: bytes, universe: tuple[UniverseAsset, ...]) -> dict[str, list[NewsItem]]:
    """Parse ONE GKG .csv.zip (in-memory) into {symbol: [NewsItem]}. Each kept row contributes its PAGE_TITLE
    headline stamped at the GKG index time (ts == available_at, point-in-time). Rows with no title, no usable
    date, or no universe hit are dropped. Deduped within the file by (symbol, date, title)."""
    out: dict[str, list[NewsItem]] = defaultdict(list)
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_zip))
    except zipfile.BadZipFile:
        return {}
    name = next((n for n in zf.namelist() if n.endswith(".csv")), None)
    if name is None:
        return {}
    seen: set[tuple[str, str, str]] = set()
    with zf.open(name) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
        for row in csv.reader(text, delimiter="\t"):
            if len(row) < _MIN_FIELDS:
                continue
            symbols = classify_row(row, universe)
            if not symbols:
                continue
            title = _extract_title(row)
            if not title:
                continue
            ts = _parse_gkg_date(row[_COL_DATE])
            if ts is None:
                continue
            for sym in symbols:
                key = (sym, row[_COL_DATE], title)
                if key in seen:
                    continue
                seen.add(key)
                out[sym].append(NewsItem(ts=ts, available_at=ts, headline=title))
    return dict(out)


def fetch_gkg_file(url: str, *, timeout: float = 90.0, retries: int = 3) -> bytes | None:
    """Download one GKG .csv.zip. Returns raw bytes, or None on a dead/missing slice (GDELT has gaps — a missing
    15-min file is honest absence, never fabricated). certifi SSL so it works on slim images."""
    ctx = _ssl_context()
    for _attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:  # noqa: S310
                return r.read()
        except Exception:  # noqa: BLE001 — 404 (no file) / transient → retry then skip
            continue
    return None


# --------------------------------------------------------------------------- the 15-min file index for a range


def gkg_file_urls(
    start: _dt.date,
    end: _dt.date,
    *,
    per_day: int = 24,
) -> list[str]:
    """The list of GKG .csv.zip URLs to pull for [start, end]. GDELT emits 96 files/day (every 15 min); pulling
    ALL 96 is overkill for a DAILY narrative signal, so we SUBSAMPLE evenly across the day (default 24 slices/day
    ≈ hourly) — enough to capture the day's narrative while cutting download volume 4×. Slices are the 15-min
    grid times 00/15/30/45; we pick `per_day` of them evenly spaced. PIT is unaffected (each file is still stamped
    at its own index time). Deterministic and reproducible.

    GKG availability starts 2015-02-18; earlier dates yield no files (skipped)."""
    grid = [(h, m) for h in range(24) for m in (0, 15, 30, 45)]  # 96 slices
    per_day = max(1, min(per_day, 96))
    step = len(grid) / per_day
    chosen = [grid[int(i * step)] for i in range(per_day)]
    urls: list[str] = []
    d = start
    one = _dt.timedelta(days=1)
    while d <= end:
        for h, m in chosen:
            stamp = f"{d.year:04d}{d.month:02d}{d.day:02d}{h:02d}{m:02d}00"
            urls.append(f"{_GKG_BASE}/{stamp}.gkg.csv.zip")
        d += one
    return urls
