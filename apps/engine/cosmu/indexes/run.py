# intent: the cron/Modal entrypoint that REFRESHES every active index — appends ONE point-in-time value per
# symbol per pass, reusing the canonical scorers (cosmu.lab.indexes for text, cosmu.mind.authority for social
# via the voices claims). inputs: env (store backend + optional XAI/OpenRouter keys) + injectable seams for
# tests; outputs: new alt_data points under provider='index' + an 'index_computed' audit event + a printed
# summary; invariants: KEY/NETWORK-GATED + OFFLINE-SAFE (a missing key/network/claims degrades a source to {} —
# the pass records 0, NEVER a fabricated value), DETERMINISTIC scoring (the existing primitives), append-only
# PIT storage, the LLM standardizes/judges text ONLY (never a gate/money path). HEAVY (scraping + LLM): run on
# Modal / a Railway cron, never inline in a chat session. Usage: python3 -m cosmu.indexes.run [--id <index_id>]

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import datetime

from cosmu.indexes.compute import (
    compute_social_point,
    compute_text_point,
    now_utc,
    store_index_points,
)
from cosmu.indexes.registry import active_indexes, get_index, indexes_available
from cosmu.indexes.spec import IndexSpec
from cosmu.knowledge.store import Store, utcnow


def _chat_from_settings(settings) -> tuple[Callable[[str, str], str | None] | None, str]:  # noqa: ANN001
    """The LLM chat seam for text-index scoring — xAI preferred (already on Railway), OpenRouter fallback. No
    key → (None, …) so a text index degrades honestly (records nothing) instead of fabricating a score."""
    from cosmu.lab.llm import OPENROUTER_URL, XAI_URL, openrouter_chat

    if getattr(settings, "xai_api_key", None):
        return openrouter_chat(settings.xai_api_key, url=XAI_URL), "grok-3-mini"
    if getattr(settings, "openrouter_api_key", None):
        return openrouter_chat(settings.openrouter_api_key, url=OPENROUTER_URL), "openai/gpt-4o-mini"
    return None, "openai/gpt-4o-mini"


def refresh_index(store: Store, spec: IndexSpec, *, settings, now: datetime | None = None) -> tuple[int, int]:  # noqa: ANN001
    """Compute + append one index's latest PIT value(s). Returns (points_written, symbols_written).
    Deterministic + offline-safe; an empty source writes nothing (honest)."""
    now = now or now_utc()
    if spec.is_text:
        chat, model_id = _chat_from_settings(settings)
        points = compute_text_point(spec, chat=chat, model_id=model_id)
    else:  # social
        from cosmu.data.market import BinanceSpotOHLCVProvider
        from cosmu.ingest.voices_pass import _bars_by_entity, _load_all_claims

        handles = set(spec.handles)
        claims = [c for c in _load_all_claims(store) if c.handle in handles]
        if claims:
            entities = set(spec.entities) or {c.entity for c in claims}
            bars = _bars_by_entity(entities, BinanceSpotOHLCVProvider())
            points = compute_social_point(spec, claims=claims, bars_by_entity=bars, now=now)
        else:
            points = {}
    written = store_index_points(store, spec, points)
    with store.batch() as w:
        w.append_event(
            actor="indexes.run", kind="index_computed", ref_type="index", ref_id=spec.id,
            payload={"points": written, "symbols": len(points), "transform_version": spec.transform_version},
        )
    return written, len(points)


def run_once(store: Store, *, settings, only_id: str | None = None) -> dict[str, tuple[int, int]]:  # noqa: ANN001
    """Refresh all active indexes (or one by id). Returns {index_id: (points, symbols)}. Fail-open per index."""
    if not indexes_available(store):
        print("[indexes.run] registry not active (apply 2026-06-15_indexes migration) — nothing to do.")
        return {}
    if only_id:
        spec = get_index(store, only_id)
        specs = [spec] if spec else []
    else:
        specs = active_indexes(store)
    out: dict[str, tuple[int, int]] = {}
    for spec in specs:
        try:
            out[spec.id] = refresh_index(store, spec, settings=settings)
        except Exception as exc:  # noqa: BLE001 — one bad index never aborts the pass
            print(f"[indexes.run] {spec.id}: ERROR {exc}")
            out[spec.id] = (0, 0)
    return out


def main(argv: list[str] | None = None) -> int:
    from cosmu.config.settings import get_settings

    parser = argparse.ArgumentParser(description="Refresh active indexes (cron/Modal). Heavy: scraping + LLM.")
    parser.add_argument("--id", default=None, help="refresh only this index id")
    args = parser.parse_args(argv)
    settings = get_settings()
    store = Store(settings)
    result = run_once(store, settings=settings, only_id=args.id)
    total = sum(p for p, _ in result.values())
    print(f"[indexes.run] {utcnow()} — refreshed {len(result)} index(es), {total} point(s) written.")
    for idx, (pts, syms) in sorted(result.items()):
        print(f"  · {idx}: {pts} pts across {syms} symbol(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
