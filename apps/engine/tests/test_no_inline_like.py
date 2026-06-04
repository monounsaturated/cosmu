# intent: guard against a Postgres-only bug class — an inline `LIKE '%...%'` whose literal `%` collides
# with psycopg2's %-paramstyle (the store passes a params tuple) → IndexError in prod, invisible on SQLite.
# inputs: engine source tree; outputs: a failing test if any inline-% LIKE sneaks back; invariants: LIKE
# patterns must be BOUND PARAMETERS (`LIKE ?`), never inlined.
from __future__ import annotations

import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "cosmu"
# Matches a LIKE whose pattern is an inline string literal containing % (the landmine).
_INLINE_LIKE = re.compile(r"LIKE\s+'[^']*%[^']*'", re.IGNORECASE)


def test_no_inline_percent_like_in_engine() -> None:
    offenders: list[str] = []
    for path in ENGINE.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if _INLINE_LIKE.search(line):
                offenders.append(f"{path.relative_to(ENGINE)}:{i}: {line.strip()}")
    assert not offenders, (
        "Inline `LIKE '%...%'` collides with psycopg2 %-paramstyle (IndexError on Postgres). "
        "Bind the pattern as a parameter (`LIKE ?`, params=('%...%',)). Offenders:\n" + "\n".join(offenders)
    )
