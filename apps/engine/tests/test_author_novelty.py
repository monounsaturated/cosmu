# NOVELTY: the research brain's hypothesis corpus must span the ENABLED FEATURE REGISTRY, not 6 frozen briefs
# (the audit's starvation finding: `_BRIEFS[i % 6]` re-proposed the same six theses forever), and successive
# ticks must ROTATE through the corpus instead of authoring the same window every time. Volume can't
# manufacture a winner — every extra brief is one more trial the same deflation/FDR brake absorbs.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.lab.research import _BRIEFS, _brief_offset, _registry_briefs, author_candidates


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/novelty.sqlite3", openrouter_api_key=None))


def test_registry_extends_the_corpus_beyond_the_handwritten_six():
    extra = _registry_briefs()
    assert len(extra) > len(_BRIEFS)  # the enabled registry is far wider than 6 theses
    covered = {f for _, feats in _BRIEFS for f in feats}
    for _, feats in extra:
        new = [f for f in feats if f not in covered and f != "ret_Nd"]
        assert new, "every registry brief must introduce a feature the hand-written corpus doesn't cover"
    # Deterministic: two reads produce the identical corpus (sorted registry, no randomness).
    assert extra == _registry_briefs()


def test_ticks_rotate_through_the_corpus(tmp_path):
    store = _store(tmp_path)
    first = [rec.brief for _, rec in author_candidates(4, store=store)]

    # Advance the tick counter (what run_tick writes before authoring) → the window must MOVE.
    store.append_event(actor="master", kind="autonomy_tick_started", ref_type="autonomy", ref_id="global")
    assert _brief_offset(store) == 1
    second = [rec.brief for _, rec in author_candidates(4, store=store)]

    assert first != second  # tick 2 explores new briefs instead of re-proposing tick 1's window
    # Determinism for a FIXED store state: re-authoring without a new tick yields the same window.
    assert second == [rec.brief for _, rec in author_candidates(4, store=store)]


def test_no_store_authors_from_the_handwritten_head():
    # Bare CLI (no store): offset 0 → the hand-written corpus leads, exactly the prior behaviour.
    briefs = [rec.brief for _, rec in author_candidates(3)]
    assert briefs == [b for b, _ in _BRIEFS[:3]]
