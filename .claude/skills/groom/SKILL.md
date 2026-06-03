---
name: groom
description: Self-maintenance pass — prune dead code, graveyard stale strategies, keep docs/memory/vocabulary lean and coherent, and leave the tree green. Use periodically or when the codebase has drifted.
---

# groom

Keep the machine lean and coherent. No new features — only removal, consolidation, and truth-reconciliation.

## Steps
1. **Dead code:** remove unused modules/exports/imports. `cd apps/engine && python3 -m ruff check cosmu --select F401,F811,F841`. Delete, don't comment out.
2. **Stale strategies:** graveyard Versions whose edge didn't hold; confirm kill_reasons are recorded. Check the drift monitor defunded decayed Tracks (`master/drift.py`).
3. **Docs ↔ code truth:** when code and the big docs diverge, reconcile in `docs/IMPLEMENTATION.md`. Keep `AGENTS.md` (entry), `docs/GLOSSARY.md` (vocabulary), and `docs/VISION.md` honest. Trim anything aspirational stated as built.
4. **Vocabulary coherence:** run `pnpm naming:check` (scripts/check_naming.py) — the lifecycle is LOCKED (Lab → Strategies → Forward-test → Live, SIM/LIVE, no pooled wallet). Fix any drift; the guard fails the build on dead terms.
5. **Memory hygiene:** keep the knowledge store lean — dead-end notes and winner patterns are useful; duplicate/empty rows are not.

## Verify
- `pnpm verify` (naming:check + contracts:generate + engine:test + typecheck) is GREEN.
- `git diff` is net-negative or flat — grooming removes more than it adds.
