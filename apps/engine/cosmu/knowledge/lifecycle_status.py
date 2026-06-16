"""Single source of truth for ``strategy_versions.status`` — the lifecycle vocabulary.

Canonical write-set (what code actually writes): ``SCREENED`` → ``PAPER`` → ``LIVE``, plus ``KILLED``
(terminal — failed the Gate or demoted by FDR). Two values are deliberately NOT canonical:

* ``forward_test`` — a LEGACY spelling of ``PAPER`` from the 2026-06-03 rename (reversed 2026-06-11).
  No code writes it anymore, but READERS stay tolerant via :data:`PAPER_ALIASES` for any un-migrated row.
* ``forward`` — a PHANTOM: it appeared in a couple of read-side ``IN (...)`` lists but was NEVER written
  by any path. It is intentionally dropped (codifying a typo would canonise it).

``draft`` / ``active`` / ``paused`` belong to the SEPARATE ``indexes`` table (see ``indexes/spec.py``),
never to ``strategy_versions`` — do not add them here.

Import these constants/sets instead of hand-writing ``status IN ('paper', ...)`` literals, so a rename
touches ONE place and a typo or dead value cannot silently ship across the ~8 status consumers
(overview, intelligence, population, the brain snapshot, the boot lifespan, the orchestrator clock,
the paper-step executor). Mirrors the frontend's ``web/lib/utils.ts`` ``isPaper`` predicate.

NOTE: status is BADGE-ONLY for the money path. The live/arming interlock reads the ``track_opened``
event + forward evidence (``master/live_eligibility``), NOT this column — so changing how status is
counted never changes what is armable.
"""

from __future__ import annotations

SCREENED = "screened"   # gate-passed, backtest evidence only (badge: Backtest)
PAPER = "paper"         # has started trading on paper — real forward evidence (badge: Paper)
LIVE = "live"           # armed on a real venue
KILLED = "killed"       # terminal — failed the Gate or demoted by FDR

#: Every status the engine writes today. A DB CHECK is intentionally NOT enforced (the SQLite test
#: store applies ``schema.sql`` verbatim and some fixtures insert ad-hoc statuses); this set + the
#: guard test in ``tests/`` are the enforcement.
CANONICAL: frozenset[str] = frozenset({SCREENED, PAPER, LIVE, KILLED})

#: Legacy spelling of PAPER tolerated in READERS only (no writer emits it post-2026-06-11).
PAPER_ALIASES: frozenset[str] = frozenset({PAPER, "forward_test"})

#: Forward-test cohort (paper / pre-live) — what the leaderboard + intelligence count as "forward".
FORWARD_STATUSES: frozenset[str] = PAPER_ALIASES

#: Funded cohort — standalone capital deployed: paper + live.
FUNDED_STATUSES: frozenset[str] = PAPER_ALIASES | {LIVE}

#: Everything still alive in the funnel (not killed): screened + paper + live.
ALIVE_STATUSES: frozenset[str] = {SCREENED} | PAPER_ALIASES | {LIVE}


def is_paper(status: str | None) -> bool:
    """True when ``status`` is the paper/forward-test stage (mirrors web ``isPaper``)."""
    return status in PAPER_ALIASES


def sql_in_list(statuses: frozenset[str]) -> str:
    """Render a SQL ``IN`` list literal, e.g. ``('forward_test', 'paper')``.

    Values are a fixed internal whitelist (never user input), so direct embedding is injection-safe
    and keeps the surrounding query readable. Sorted for deterministic SQL text.
    """
    return "(" + ", ".join(f"'{s}'" for s in sorted(statuses)) + ")"
