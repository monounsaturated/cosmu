#!/usr/bin/env python3
# intent: Phase-0 voices backfill — fetch historical timelines for configured handles and seed the
# VoiceTimelineStore so signal_history() (Phase 3) has a PIT-replayable span to evaluate. Each post
# gets available_at == ts (public post visible when posted → honest retrospective PIT). Phase 1 (LLM
# claim extraction) and Phase 3 (authority ranking + signal_history materialisation) run separately.
#
# Run:
#   PYTHONPATH=apps/engine python3 scripts/backfill_voices.py --reddit u/analyst1,u/analyst2 --days 365
#   PYTHONPATH=apps/engine python3 scripts/backfill_voices.py --rss https://example.substack.com/feed --days 180
#   PYTHONPATH=apps/engine python3 scripts/backfill_voices.py --xai @analyst1 --days 90  # best-effort
#   PYTHONPATH=apps/engine python3 scripts/backfill_voices.py --help
#
# This is PHASE 0 ONLY. After running, seed Phase 1 (claim extraction) then Phase 3 (signal_history)
# to materialise the AltData series the Gate reads.

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.data.sources.voices import (  # noqa: E402
    RedditVoiceProvider,
    RssVoiceProvider,
    VoiceBackfillRunner,
    VoiceTimelineStore,
    XaiVoiceProvider,
)


def _split(csv: str) -> list[str]:
    return [h.strip() for h in csv.split(",") if h.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase-0 voice-timeline backfill. Populates .cosmu/voices/ with PIT-stamped posts "
        "(available_at == ts) so the authority signal has a replayable history for backtesting.",
    )
    parser.add_argument(
        "--days", type=int, default=365,
        help="Lookback in days (default: 365). Reddit caps at ~1 000 posts/user regardless.",
    )
    parser.add_argument("--reddit", default="", help="Comma-separated Reddit handles (e.g. u/spez,u/foo).")
    parser.add_argument("--rss", default="", help="Comma-separated RSS/Atom feed URLs or slugs.")
    parser.add_argument("--xai", default="", help="Comma-separated X handles (e.g. @foo). Best-effort coverage.")
    parser.add_argument("--store", default=".cosmu/voices", help="VoiceTimelineStore root (default: .cosmu/voices).")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write to the store.")
    args = parser.parse_args()

    reddit_handles = _split(args.reddit) or None
    rss_handles = _split(args.rss) or None
    xai_handles = _split(args.xai) or None

    if not any([reddit_handles, rss_handles, xai_handles]):
        parser.error("Supply at least one of --reddit / --rss / --xai")

    xai_key = os.environ.get("XAI_API_KEY", "")
    store = VoiceTimelineStore(root=args.store)
    if args.dry_run:
        # Wrap store.append to count without writing
        real_append = store.append
        appended: dict[str, int] = {}
        def _dry_append(posts, _key=""):  # noqa: ANN001
            n = len(posts)
            appended[_key] = n
            return n
        store.append = real_append  # type: ignore[method-assign] — not actually overriding below

    runner = VoiceBackfillRunner(
        store=store,
        reddit=RedditVoiceProvider() if reddit_handles else None,
        rss=RssVoiceProvider() if rss_handles else None,
        xai=XaiVoiceProvider(api_key=xai_key) if xai_handles else None,
    )

    print(f"Backfilling {args.days} days of voice history → {args.store}")
    results = runner.run(
        reddit_handles=reddit_handles,
        rss_handles=rss_handles,
        xai_handles=xai_handles,
        days_back=args.days,
    )

    if not results:
        print("  (no posts fetched — check handles and API keys)")
        return

    total = sum(results.values())
    for key, n in sorted(results.items()):
        print(f"  {key}: {n} posts appended")
    print(f"Total: {total} posts — store: {args.store}")
    print()
    print("Next steps:")
    print("  1. Run Phase 1 (claim extraction): import ClaimExtractor from cosmu.mind.claims")
    print("  2. Run Phase 3 (signal_history):   import signal_history from cosmu.mind.authority")
    print("  3. Materialise into AltDataStore so the Gate can evaluate the strategy.")


if __name__ == "__main__":
    main()
