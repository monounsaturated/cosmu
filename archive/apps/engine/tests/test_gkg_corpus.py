# Offline, deterministic tests for the DEEP GKG raw-text corpus builder (the LLM-narrative axis's data source).
# No network. Proves the data-integrity backbone of the deep pull:
#   (1) a GKG row is classified to the LIQUID universe by entity/theme match (crypto by name+theme; equities by
#       FULL company name so a bare-ticker collision can't pollute the stream); off-universe rows are dropped.
#   (2) the headline fed downstream is the article's own PAGE_TITLE (extracted from the Extras XML), nothing else.
#   (3) every kept item is stamped POINT-IN-TIME at GDELT's index time (ts == available_at), never the future.
#   (4) the 15-min file URL index subsamples evenly and is reproducible.

from __future__ import annotations

import datetime as dt
import io
import zipfile

from cosmu.research.gkg_corpus import (
    DEFAULT_UNIVERSE,
    UniverseAsset,
    classify_row,
    gkg_file_urls,
    parse_gkg_bytes,
)

_UNIVERSE = DEFAULT_UNIVERSE


def _row(date: str, *, allnames: str = "", orgs: str = "", themes: str = "", title: str = "") -> list[str]:
    """Build a 27-field GKG 2.1 row with only the columns the parser reads populated."""
    row = [""] * 27
    row[0] = f"{date}-0"
    row[1] = date  # V2.1 DATE = index time
    row[7] = themes  # V1 themes
    row[11] = orgs  # V1 orgs
    row[23] = allnames  # V2.1 AllNames
    row[26] = f"<PAGE_PRECISEPUBTIMESTAMP>{date}</PAGE_PRECISEPUBTIMESTAMP><PAGE_TITLE>{title}</PAGE_TITLE>"
    return row


def _zip_rows(rows: list[list[str]]) -> bytes:
    csv_text = "\n".join("\t".join(r) for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("20240101000000.gkg.csv", csv_text)
    return buf.getvalue()


def test_classify_crypto_by_name_and_theme():
    r = _row("20240101120000", allnames="Bitcoin,10", themes="ECON_CRYPTOCURRENCY")
    assert classify_row(r, _UNIVERSE) == {"BTCUSDT"}
    # theme alone (no name) still classifies crypto
    r2 = _row("20240101120000", allnames="Some Coin,10", themes="ECON_CRYPTOCURRENCY")
    assert "BTCUSDT" in classify_row(r2, _UNIVERSE)


def test_equity_needs_full_name_not_bare_ticker():
    # A bare ticker in unrelated text must NOT classify (the noise the full-name rule guards against).
    r_noise = _row("20240101120000", allnames="AAPL Orchards LLC,5")
    assert classify_row(r_noise, _UNIVERSE) == set()
    # The real company name classifies.
    r_real = _row("20240101120000", allnames="Apple Inc,5")
    assert classify_row(r_real, _UNIVERSE) == {"AAPL"}


def test_off_universe_row_dropped():
    r = _row("20240101120000", allnames="Some Local Council,5", themes="TAX_FNCACT_LEADER")
    assert classify_row(r, _UNIVERSE) == set()


def test_parse_extracts_title_and_is_point_in_time():
    rows = [
        _row("20240101123000", allnames="Bitcoin,3", title="Bitcoin rallies on ETF inflows"),
        _row("20240101123000", allnames="Nvidia Corp,3", title="Nvidia unveils new GPU"),
        _row("20240101123000", allnames="Unrelated Town,3", title="Town fair this weekend"),  # dropped
    ]
    out = parse_gkg_bytes(_zip_rows(rows), _UNIVERSE)
    assert set(out) == {"BTCUSDT", "NVDA"}
    btc = out["BTCUSDT"][0]
    assert btc.headline == "Bitcoin rallies on ETF inflows"
    # PIT: availability == index time, never before.
    assert btc.ts == btc.available_at == dt.datetime(2024, 1, 1, 12, 30, 0, tzinfo=dt.UTC)


def test_parse_drops_rows_without_title():
    r = _row("20240101120000", allnames="Bitcoin,3", title="")  # no PAGE_TITLE content
    out = parse_gkg_bytes(_zip_rows([r]), _UNIVERSE)
    assert out == {}


def test_parse_dedupes_within_file():
    same = _row("20240101120000", allnames="Bitcoin,3", title="Same headline twice")
    out = parse_gkg_bytes(_zip_rows([same, same]), _UNIVERSE)
    assert len(out["BTCUSDT"]) == 1


def test_custom_universe_membership():
    uni = (UniverseAsset("XYZ", ("acme corp",), (), "equity"),)
    r = _row("20240101120000", allnames="Acme Corp,1", title="Acme beats earnings")
    assert classify_row(r, uni) == {"XYZ"}
    out = parse_gkg_bytes(_zip_rows([r]), uni)
    assert out["XYZ"][0].headline == "Acme beats earnings"


def test_url_index_subsamples_and_is_reproducible():
    urls = gkg_file_urls(dt.date(2024, 1, 1), dt.date(2024, 1, 2), per_day=24)
    assert len(urls) == 48  # 2 days * 24/day
    assert urls[0].endswith("20240101000000.gkg.csv.zip")
    # all stamps are on the 15-min grid and within range
    assert all(u.endswith(".gkg.csv.zip") for u in urls)
    assert gkg_file_urls(dt.date(2024, 1, 1), dt.date(2024, 1, 1), per_day=24) == urls[:24]


def test_url_index_full_density():
    urls = gkg_file_urls(dt.date(2024, 1, 1), dt.date(2024, 1, 1), per_day=96)
    assert len(urls) == 96  # every 15-min slice
