# Cosmu: agent entry point

This repo is a **static landing page** (`apps/web`, Next.js, deployed on Vercel) that showcases the Cosmu
quant engine. The engine itself is archived in `archive/` (see `archive/README.md`) and at the tag
`v1-engine-archive`. Don't revive archived code unless asked.

## Rules
- **Real numbers only.** Every figure on the page comes from `apps/web/lib/cibr-hacks.json` (built from
  real closes by `scripts/landing/build_cibr_demo.py`) or from counted repo facts in `apps/web/lib/site.ts`.
  Never invent data.
- **One design system.** `apps/web/app/globals.css` (Iris Bento tokens, dark default + `.light`). No Tailwind,
  no UI kit. Reuse `.cell`, `.chip`, `.btn`, `.kpi` before adding classes.
- **No backend.** `output: "export"`. Nothing needs Railway or API keys.
- **Before pushing:** `pnpm verify` (typecheck + build). Feature branch + PR, never push to `main`.

## Communication
Plain words, numbered, ranked by importance, no analogies.
