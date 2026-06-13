#!/usr/bin/env python3
"""Naming guard — fail if dead vocabulary returns to code/contracts.

The COSMU lifecycle is LOCKED: Lab → Strategies → Paper → Live, NO pooled wallet, money state
SIM/LIVE (see docs/GLOSSARY.md). This guard scans CODE (Python / TS / TSX / SQL) for the dead spellings
so a rename can't silently regress. Docs/markdown, the GLOSSARY's dead-list, the one-shot migrations, and
this script are excluded. Runs in `pnpm verify`; exits non-zero on any hit.

2026-06-11: the stage formerly called "forward test" is now "paper" (operator decision). The OLD
spellings below are banned as WRITE/identifier patterns only — tolerant READERS may still match the
legacy DB value via `IN ('paper', 'forward_test', ...)` until the 2026-06-11 migration has run in prod.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Dead identifier spellings that must not appear in code. Word-boundaried where it matters.
BANNED = [
    r"PaperPortfolio",
    r"fund_wallet_from_survivors",
    r"WalletFundingReport",
    r"mark_paper_positions",
    r"PortfolioResponse",
    r"DriftSleeve",
    r"sleeve_return_pct",
    r"\bclass Sleeve\b",
    r"\bSleeve\(",
    r"\bdef rotate\b",
    r"kelly_fraction",
    # The dead TABLE names — banned in SQL/table contexts only. The bare words stay legal in prose:
    # Faber GTAA's strategy literally allocates across "sleeves" (comments/prints/docstrings), and a
    # word-boundary ban on common English made the guard cry wolf on honest domain language.
    r"(?i:\b(from|join|into|update|table)\s+sleeves\b)",
    r"(?i:\b(from|join|into|update|table)\s+allocations\b)",
    r"sleeve_opened",
    r"sleeve_defunded",
    r"reset_paper_state",
    r"paper_state_reset",
    r"scope = 'pool'",
    r"scope = 'sleeve'",
    # 2026-06-11 stage rename: forward_test → paper. Ban the dead WRITE/identifier spellings; the bare
    # 'forward_test' inside a tolerant IN-list / ==-chain stays legal until the prod migration lands.
    r"status = 'forward_test'",
    r"status\s*=\s*\"forward_test\"",
    r"forward_test_promotion_watch",
    r"\bforward_stepped\b",
    r"FORWARD_TEST_MIN_DAYS",
    r"override_forward_test",
    r"forward_test_days",
    r"\bforward_age_days\b",
    r"\bforward_return_pct\b",
    r"ForwardMaturity",
    r"forward-test",
]

# Only scan source; skip generated dirs, docs, the migration, the glossary, and this guard itself.
EXTS = {".py", ".ts", ".tsx", ".sql"}
SKIP_DIRS = {".git", ".claude", "node_modules", ".next", "__pycache__", "dist", ".venv", "migrations"}
SKIP_FILES = {"check_naming.py"}

pattern = re.compile("|".join(BANNED))


def main() -> int:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if path.suffix not in EXTS or not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts) or path.name in SKIP_FILES:
            continue
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()}")
    if hits:
        print("✗ dead vocabulary found (see docs/GLOSSARY.md — Lab → Strategies → Forward-test → Live, no pooled wallet):")
        print("\n".join(hits))
        return 1
    print("✓ naming guard: no dead vocabulary in code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
