# The DATA-AGNOSTIC ingest seam (cosmu/authority/ingest.py) — the single function the LOCAL ingestion feeds,
# whatever the upstream (a pasted/JSON dump, an xAI/Grok timeline fetch, a Claude-in-Chrome scrape). Pins:
#   * three differently-shaped record schemas all normalize to the same AccountCall (field-name + direction-vocab
#     tolerance);
#   * a malformed / incomplete record is DROPPED (the batch survives) — never raises, never guesses;
#   * timestamps coerce to tz-aware UTC from ISO (incl. trailing Z) and epoch seconds/millis;
#   * conviction on a 0..100 scale folds to 0..1; assets upper-case and strip a leading '$';
#   * exact-duplicate calls collapse; output is ordered.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.authority.ingest import paginate_calls, parse_call, parse_calls


def _rec(account: str, asset: str, direction: str, day: int, call_id: str) -> dict:
    return {"account": account, "asset": asset, "direction": direction,
            "ts": f"2024-03-{day:02d}T00:00:00Z", "call_id": call_id}


def test_json_dump_shape_parses():
    """A hand/JSON dump: explicit field names, ISO timestamp."""
    dump = """
    [
      {"account": "@punk6529", "platform": "x", "asset": "BTC", "direction": "bullish",
       "ts": "2024-03-01T12:00:00Z", "conviction": 0.8, "call_id": "111", "text": "BTC up", "url": "http://x/111"},
      {"account": "@bear", "asset": "$eth", "direction": "short", "timestamp": "2024-03-02T09:30:00+00:00"}
    ]
    """
    calls = parse_calls(dump, source="json")
    assert len(calls) == 2
    btc = calls[0]
    assert btc.account == "@punk6529" and btc.asset == "BTC" and btc.direction == "up"
    assert btc.conviction == 0.8 and btc.call_id == "111" and btc.source == "json"
    assert btc.ts == datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
    eth = calls[1]
    assert eth.asset == "ETH" and eth.direction == "down" and eth.platform == "x"  # default platform
    assert eth.conviction == 0.5  # default when absent


def test_xai_grok_shape_parses():
    """An xAI/Grok-style response: nested under 'data', different field names, epoch-millis timestamp,
    confidence on a 0..100 scale."""
    payload = {
        "data": [
            {"author": "elonmusk", "ticker": "DOGE", "sentiment": "moon", "created_at": 1709294400000,
             "confidence": 90, "tweet_id": "999", "tweet": "to the moon"},
        ]
    }
    calls = parse_calls(payload, source="xai")
    assert len(calls) == 1
    c = calls[0]
    assert c.account == "elonmusk" and c.asset == "DOGE" and c.direction == "up"
    assert c.conviction == 0.9  # 90/100 folded to 0..1
    assert c.call_id == "999" and c.source == "xai"
    assert c.ts == datetime(2024, 3, 1, 12, 0, tzinfo=UTC)  # 1709294400 s == 2024-03-01T12:00:00Z


def test_chrome_scrape_shape_parses():
    """A Claude-in-Chrome scrape: 'username'/'symbol'/'stance', epoch SECONDS, permalink as url."""
    rows = [
        {"username": "cryptohandle", "symbol": "SOL", "stance": "sell", "time": 1709294400,
         "permalink": "https://x.com/cryptohandle/status/42", "status_id": "42"},
    ]
    calls = parse_calls(rows, source="chrome")
    c = calls[0]
    assert c.account == "cryptohandle" and c.asset == "SOL" and c.direction == "down"
    assert c.url.endswith("/42") and c.call_id == "42" and c.source == "chrome"
    assert c.ts == datetime(2024, 3, 1, 12, 0, tzinfo=UTC)


def test_malformed_and_incomplete_records_are_dropped_not_raised():
    """Missing any of {account, asset, direction, ts}, an unknown direction word, or a non-dict → dropped. The
    valid rows survive; nothing raises (a bad dump never aborts ingestion)."""
    payload = [
        {"account": "@ok", "asset": "BTC", "direction": "up", "ts": "2024-03-01T00:00:00Z"},  # valid
        {"account": "@nodir", "asset": "BTC", "ts": "2024-03-01T00:00:00Z"},                  # no direction
        {"account": "@badword", "asset": "BTC", "direction": "vibes", "ts": "2024-03-01T00:00:00Z"},  # unknown vocab
        {"account": "@badts", "asset": "BTC", "direction": "up", "ts": "not-a-date"},          # bad ts
        {"asset": "BTC", "direction": "up", "ts": "2024-03-01T00:00:00Z"},                     # no account
        "not-a-dict",                                                                          # junk
        42,
    ]
    calls = parse_calls(payload)
    assert len(calls) == 1 and calls[0].account == "@ok"


def test_single_record_dict_is_accepted():
    one = {"account": "@solo", "asset": "BTC", "direction": "long", "ts": "2024-03-01T00:00:00Z"}
    calls = parse_calls(one)
    assert len(calls) == 1 and calls[0].direction == "up"


def test_exact_duplicates_collapse_and_output_is_ordered():
    rec = {"account": "@a", "platform": "x", "asset": "BTC", "direction": "up",
           "ts": "2024-03-02T00:00:00Z", "call_id": "1"}
    earlier = {"account": "@a", "platform": "x", "asset": "ETH", "direction": "down",
               "ts": "2024-03-01T00:00:00Z", "call_id": "2"}
    calls = parse_calls([rec, dict(rec), earlier])  # rec twice
    assert len(calls) == 2
    # ordered by ts ascending → the 03-01 ETH call first.
    assert calls[0].asset == "ETH" and calls[1].asset == "BTC"


def test_garbage_string_payload_returns_empty():
    assert parse_calls("not json at all") == []
    assert parse_call("nope") is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- paginate_calls (the BIGGER-PULL seam)


def test_paginate_accumulates_across_pages_and_dedupes():
    """Two pages drained in order, calls deduped across the page boundary (a repeated post never double-counts),
    output ordered by ts."""
    pages = {
        None: ([_rec("@a", "BTC", "up", 1, "1"), _rec("@a", "ETH", "down", 2, "2")], "c1"),
        "c1": ([_rec("@a", "ETH", "down", 2, "2"), _rec("@a", "SOL", "up", 3, "3")], None),  # "2" repeats
    }
    seen: list = []

    def fetch(cursor):
        seen.append(cursor)
        return pages[cursor]

    calls = paginate_calls(fetch, source="xai")
    assert seen == [None, "c1"]
    assert [c.call_id for c in calls] == ["1", "2", "3"]  # deduped + ordered


def test_paginate_respects_max_posts_cap():
    """A timeline that never exhausts is capped at max_posts (cost-managed; the runner never over-pulls)."""
    def fetch(cursor):
        base = cursor or 0
        recs = [_rec("@a", "BTC", "up", (base * 5 + i) % 28 + 1, str(base * 5 + i)) for i in range(5)]
        return recs, base + 1

    assert len(paginate_calls(fetch, max_posts=7, max_pages=100)) == 7


def test_paginate_respects_max_pages_cap():
    def fetch(cursor):
        n = cursor or 0
        return [_rec("@a", "BTC", "up", n % 28 + 1, str(n))], n + 1  # one fresh call per page, never exhausts

    assert len(paginate_calls(fetch, max_posts=100, max_pages=3)) == 3


def test_paginate_stops_on_none_cursor():
    def fetch(cursor):
        return [_rec("@a", "BTC", "up", 1, "1")], None

    assert len(paginate_calls(fetch, max_pages=10)) == 1


def test_paginate_survives_a_raising_page():
    """A fetch that raises mid-pull STOPS the pull and keeps what was already collected (a flaky page never aborts
    the whole run)."""
    made: list = []

    def fetch(cursor):
        made.append(cursor)
        if cursor is None:
            return [_rec("@a", "BTC", "up", 1, "1")], "c1"
        raise RuntimeError("page boom")

    calls = paginate_calls(fetch, max_pages=10)
    assert [c.call_id for c in calls] == ["1"]
    assert made == [None, "c1"]
