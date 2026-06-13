# Handoff — finishing the v18 web port

> Context: the v18 design (`mockups/cosmu-final-v18.html`) was ported to `apps/web` in #192 / #195.
> This PR lands the fixes that need **no live engine data** (verified in cloud with a real build +
> headless-Chromium screenshots). The items below need **your local env** (a reachable engine +
> `.env.local` secrets) to finish, because the cloud box has no engine/DB to render real numbers.

## What this PR already fixed (cloud, build-verified)

1. **v18 density restored.** The port had dropped `zoom:1.15` (following an earlier "scale via tokens"
   note), which is the main reason it "didn't look like v18" — everything rendered at the wrong scale.
   Re-applied `body{zoom:1.15}` and switched the full-height fixed elements (`body`, `.shell`,
   `.sidebar`, `.overlay`, `.side-panel`) to `calc(100dvh/1.15)` — pixel-faithful to the mockup.
   (A rem/scale-token refactor can replace the `zoom` later; this gets parity now.)
2. **Costs crash guard.** `LlmCallsSummary` did `Object.entries(by_task)`; a deployed engine sending
   `by_task: null` would throw and break the Costs page. Now `Object.entries(by_task ?? {})`.
3. **Faster load.** `getSupplierCosts()` fired three vendor billing fetches with no cap — up to ~15s
   if they hang. Each is now capped at **3s** (falls back to its estimate), so the Costs page paints
   fast regardless of vendor API latency.
4. **Dropped dead weight.** Removed `recharts` and `lightweight-charts` from `apps/web` deps — both
   were unused (the equity chart is a hand-rolled SVG). Lockfile updated.

Not changed (already correct): Iris-Bento tokens are verbatim v18, sidebar order is right, honest
empty states, `force-dynamic` + Suspense streaming, `app/icon.svg` is already the favicon.

## What needs YOUR local env (the real "broken dashboards")

### P0 — Deploy config (most likely why it looks broken)
- The deployed dashboards almost certainly show **"ENGINE NOT CONNECTED"** because **`API_BASE_URL`
  is not set on Vercel** (and `API_SECRET_KEY` if the engine gates with `X-API-Key`). Set them on the
  Vercel project and confirm the engine is reachable from Vercel's region. With those unset, every
  page renders its honest empty state — which reads as "broken". This is config, not code.

### P1 — Live-data QA (cloud can't see real numbers)
- With the engine connected, walk **Strategies · Paper · Live · Costs** and confirm tables/KPIs
  populate and match v18. Specifically re-check the v18 design requirements that depend on real data:
  `$` on all dollar values, OOS window next to OOS %, the strat-sheet "Recent trades" showing the
  time, and P&L as the two columns ($ overall + %).

### P2 — Costs chart (v18 parity, needs a backend series)
- v18 puts the **cumulative-spend curve** on top of Costs (7D/30D/All, same component as the equity
  chart). The port shows "no dated spend curve yet" **on purpose**: `/costs` returns point-in-time
  totals, not a daily series. To restore the chart faithfully, add a **daily/cumulative spend series**
  to the backend (a field on `CostsResponse` or a `/costs/series` route), then reuse
  `components/charts/equity-chart.tsx`. Do **not** fabricate a trend from a single total.

### P3 — Honest-empty feeds that await endpoints
- **Live "Recent trades"** is an intentional empty state — there's no `/live/trades` endpoint. Wire it
  if/when the engine exposes recent live fills (or carries them on `/live/positions`).
- **Light theme**: `globals.css` defines `.light` but no toggle is wired. Add the toggle if light mode
  ships (v18 had it).
- **Tooltip clamp**: now that `zoom:1.15` is back, verify the strategy-sheet tooltip on the detail
  panel positions correctly (mirror the mockup's `/1.15` viewport clamp if it reads `window.innerWidth`).

## How to verify locally
```
# from repo root
API_BASE_URL=http://localhost:8000 API_SECRET_KEY=… pnpm dev      # against a running engine
# or the cloud recipe used for this PR:
pnpm build && PORT=3112 pnpm --filter @cosmu/web start
# then screenshot each route with headless chromium to compare against mockups/cosmu-final-v18.html
```
