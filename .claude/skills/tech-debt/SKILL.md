---
name: tech-debt
description: Focused cleanup pass (sharper than groom) — kill dead imports/vars, resolve debt markers, reconcile docs with reality, and remove unused web components for a net-negative diff. Use when the codebase has accreted cruft.
---

# tech-debt

Targeted debt paydown. Removal and truth-reconciliation only — no features. Aim for a net-negative diff. (For the broader self-maintenance sweep — strategies, memory, vocabulary — use `/groom`.)

## Steps
1. **Dead imports/vars:** `cd apps/engine && python3 -m ruff check cosmu --select F401,F811,F841`. Delete, don't comment out.
2. **Debt markers:** `grep -rn "TODO\|FIXME\|HACK\|XXX" apps/engine/cosmu/` — resolve or file to `BACKLOG.md` (don't leave orphan markers).
3. **Docs ↔ reality:** confirm `AGENTS.md`, `docs/GLOSSARY.md`, `docs/IMPLEMENTATION.md` describe what's actually built; trim anything aspirational stated as done.
4. **Dead web components:** `grep -rn "import.*from" apps/web/` — find components/exports no longer referenced and remove them.
5. **Run `pnpm verify`** — leave the tree green.
6. **Report:** what was cleaned, and what debt remains (with a pointer to where it's now tracked).

## Verify
- `pnpm verify` exits 0.
- `git diff --stat` is net-negative (more deleted than added).
