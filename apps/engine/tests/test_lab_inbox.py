# The strategies/inbox scanner: scan *.{md,pine,json} → translate (reuse pine + author) → typed StrategySpec →
# Lab via the deterministic FarmLoop. Idempotent (unchanged files skipped via content-hash). Offline-safe.

from __future__ import annotations

import json
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_momentum_spec
from cosmu.knowledge.store import Store
from cosmu.lab.inbox import scan_inbox
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
