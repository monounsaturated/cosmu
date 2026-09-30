# Cosmu: agent entry point

This repo is a **static landing page** (`apps/web`, Next.js, deployed on Vercel) that showcases the Cosmu
quant engine. The engine itself is archived in `archive/` (see `archive/README.md`) and at the tag
`v1-engine-archive`. Don't revive archived code unless asked.

## Rules
- **Real numbers only.** Every figure on the page comes from `apps/web/lib/showcase.json`, exported from
  real closes by `scripts/landing/build_showcase.py` (harness: `hypotheses.py`), or from
  `apps/web/lib/engine-stats.json` (aggregates from the archived engine's DB, `scripts/landing/engine_stats.py`).
  Never invent data.
- **One design system.** `apps/web/app/globals.css` (Iris Bento tokens; light by default via `.light` on `<html>`, dark through the toggle). No Tailwind,
  no UI kit. Reuse existing classes before adding new ones.
- **No backend.** `output: "export"`. Nothing needs Railway or API keys.
- **Before pushing:** `pnpm verify` (typecheck + research tests + build). CI runs the same on every push. Feature branch + PR, never push to `main`.

## Communication
Plain words, numbered, ranked by importance, no analogies.
