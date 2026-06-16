# Item 3: live ENTRIES only open on the EXACT frozen proven config. paper_step._frozen_config_ok refuses a new
# live position when the version has no promotion record OR its params drifted from the frozen params_hash — so
# live replicates what the Gate proved, never a silently re-fitted config. Exits are never gated by this.

from __future__ import annotations

import json

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.promotion import freeze_promotion
from cosmu.orchestrator.paper_step import _frozen_config_ok


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/freeze.sqlite3", openrouter_api_key=None))


def _seed(store: Store, vid: str, params: dict) -> None:
    sid = store.insert("strategies", {"name": vid, "thesis": "t", "origin": "seed", "created_at": utcnow()})
    store.insert(
        "strategy_versions",
        {
            "id": vid, "strategy_id": sid,
            "spec": json.dumps({"universe": {"venues": ["binance"], "asset_classes": ["crypto"]}}),
            "generated_code": "x", "code_hash": "h", "params": json.dumps(params),
            "origin": "seed", "status": "live", "created_at": utcnow(),
        },
    )


def test_frozen_config_ok_requires_a_matching_promotion_record(tmp_path):
    store = _store(tmp_path)
    _seed(store, "v1", {"entry_ret": 0.05, "stop": 0.06, "config_tag": "abc"})  # config_tag is a non-numeric carrier
    # No freeze yet → a live entry is REFUSED (missing record fails safe).
    assert _frozen_config_ok(store, "v1", {"entry_ret": 0.05, "stop": 0.06}) is False
    freeze_promotion(store, "v1")
    # Matching NUMERIC params → entry allowed (config_tag is ignored on both sides by params_hash).
    assert _frozen_config_ok(store, "v1", {"entry_ret": 0.05, "stop": 0.06}) is True
    assert _frozen_config_ok(store, "v1", {"entry_ret": 0.05, "stop": 0.06, "config_tag": "xyz"}) is True
    # Drifted numeric params → REFUSED (a real re-fit, not a label change).
    assert _frozen_config_ok(store, "v1", {"entry_ret": 0.09, "stop": 0.06}) is False
    # Unknown version → REFUSED (fail-safe).
    assert _frozen_config_ok(store, "ghost", {"entry_ret": 0.05}) is False
