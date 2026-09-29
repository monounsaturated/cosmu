# The strategies/inbox scanner: scan *.{md,pine,json} → translate (reuse pine + author) → typed StrategySpec →
# Lab via the deterministic FarmLoop. Idempotent (unchanged files skipped via content-hash). Offline-safe.

from __future__ import annotations

import json
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_momentum_spec
from cosmu.knowledge.store import Store
from cosmu.lab.inbox import list_queued, queue_idea, scan_inbox
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.pine_samples import PINE_SAMPLES


class _FixtureBars:
    # Small, fast offline market: 2 catalog symbols x ~280 edge-bearing bars (enough for the screen's 80-bar
    # floor + holdout split) so finder grids stay quick in CI.
    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/inbox.sqlite3", openrouter_api_key=None))


def _seed_inbox(tmp_path) -> Path:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "rsi.pine").write_text(PINE_SAMPLES["RSI oversold reversion"])
    (inbox / "brief.md").write_text("Trend-confirmed momentum on crypto with ADX confirmation, swing horizon.")
    (inbox / "spec.json").write_text(json.dumps(seed_momentum_spec().model_dump(mode="json")))
    return inbox


def test_inbox_imports_all_three_kinds(tmp_path):
    store = _store(tmp_path)
    inbox = _seed_inbox(tmp_path)
    report = scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    assert report.scanned == 3
    kinds = {f.kind for f in report.imported}
    assert kinds == {"pine", "brief", "json"}
    # each import recorded as an idempotency event
    events = store.rows("SELECT COUNT(*) AS n FROM events WHERE kind = 'inbox_imported'")[0]["n"]
    assert events == 3
    # the deterministic cohort ran over the imported specs (the Lab judged them)
    assert report.cohort is not None and report.cohort.generated >= 1


def test_inbox_is_idempotent(tmp_path):
    store = _store(tmp_path)
    inbox = _seed_inbox(tmp_path)
    first = scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    assert len(first.imported) == 3
    second = scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())  # unchanged files
    assert len(second.imported) == 0
    assert len(second.skipped) == 3


def test_inbox_changed_file_reimports(tmp_path):
    store = _store(tmp_path)
    inbox = _seed_inbox(tmp_path)
    scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    (inbox / "brief.md").write_text("Oversold mean reversion on crypto, daily bars, buy the dip.")
    report = scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    assert any(f.kind == "brief" and f.imported for f in report.imported)


def test_missing_inbox_dir_is_safe(tmp_path):
    store = _store(tmp_path)
    report = scan_inbox(store, inbox_dir=tmp_path / "nope")
    assert report.scanned == 0 and report.imported == []


# A .md may lead with a typed YAML front-matter block (the authored format the README documents). It must be
# parsed as that EXACT spec — not silently degraded to a heuristic prose draft (which discarded the author's
# named features + fitted param_space and produced a mangled name).
_FRONTMATTER_MD = """---
name: Front-matter reversion
rationale: buy oversold dips on spot
universe: {venues: [binance], asset_classes: [crypto], min_instruments: 5}
horizon: {bar_size: 1d, min_hold_days: 1, max_hold_days: 7}
entry:
  - feature: {name: rsi, lookback: {param: rsi_lookback}}
    op: lt
    threshold: {param: rsi_floor}
exit:
  stop_loss: {param: stop}
  take_profit: {param: tp}
param_space:
  rsi_lookback: {kind: int, lo: 7, hi: 21, step: 1}
  rsi_floor: {kind: float, lo: 20.0, hi: 40.0}
  stop: {kind: float, lo: 0.03, hi: 0.12}
  tp: {kind: float, lo: 0.05, hi: 0.2}
---

# Front-matter reversion
Thesis prose that the heuristic drafter would otherwise parse instead of the typed block above.
"""


def test_inbox_md_frontmatter_parses_typed_spec(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "fm.md").write_text(_FRONTMATTER_MD)
    report = scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    assert len(report.imported) == 1
    rec = report.imported[0]
    # parsed via the typed front-matter path, with the AUTHORED name preserved verbatim (not a "(chat)" draft)
    assert rec.kind == "md-spec"
    assert rec.name == "Front-matter reversion"


def test_queue_idea_writes_brief_and_records_event(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    idea = queue_idea(store, "Buy oversold dips on BTC when funding flips negative.", inbox_dir=inbox)
    # a brief file is written into the inbox
    path = Path(idea.path)
    assert path.exists() and path.suffix == ".md"
    assert path.parent == inbox
    assert "oversold dips" in path.read_text()
    # the queue is auditable off the event ledger and starts as "queued"
    rows = list_queued(store)
    assert len(rows) == 1 and rows[0].status == "queued" and rows[0].name


def test_queue_idea_rejects_empty(tmp_path):
    store = _store(tmp_path)
    try:
        queue_idea(store, "   ", inbox_dir=tmp_path / "inbox")
    except ValueError:
        pass
    else:
        raise AssertionError("empty idea must raise")


def test_queued_idea_flips_to_imported_after_scan(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    queue_idea(store, "Trend-confirmed momentum on crypto with ADX confirmation, swing horizon.", inbox_dir=inbox)
    assert list_queued(store)[0].status == "queued"
    scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    # once the scanner imports the queued brief's content-hash, the queue row reflects it honestly
    assert list_queued(store)[0].status == "imported"


def test_inbox_skips_readme_docs(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "README.md").write_text("# Strategy Inbox\nDrop strategy files here.")
    (inbox / "spec.json").write_text(json.dumps(seed_momentum_spec().model_dump(mode="json")))
    report = scan_inbox(store, inbox_dir=inbox, market_data=_FixtureBars())
    # README is documentation, never a spec — only the real spec is scanned/imported
    assert report.scanned == 1
    assert {f.kind for f in report.imported} == {"json"}
