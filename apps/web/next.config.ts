import type { NextConfig } from "next";

// The v18 redesign is the whole frontend: SEVEN surfaces — Strategies · Paper · Live · Costs · Research ·
// Keys · Commands (landing = Strategies). Most of the previous app's knowledge/ops pages were folded; their
// backend data keeps accruing, but the pages are gone from the UI. These redirects keep any old URL
// (bookmarks, deep links) working by sending it to the nearest surviving surface — no 404s, no clutter.
// EXCEPTIONS — UN-folded surfaces that host real pages, so they must NOT be in the folded list or the
// catch-all would shadow them: /research (the Experiments memory from gate_verdicts), /lab (the per-symbol
// backtest screener — every strategy × symbol × venue, verdict-labelled), and /mind (the read-only
// credibility surface — the followed-voices scoreboard off /mind/credibility).
const FOLDED_TO_STRATEGIES = [
  "/overview",
  "/console",
  "/verdicts",
  "/correlations",
  "/explorer",
  "/scores",
  "/steer",
  "/farm",
  "/settings",
];

const nextConfig: NextConfig = {
  devIndicators: false,
  async redirects() {
    return [
      // Research surface entry: the bare path lands on its only page, the Experiments memory.
      { source: "/research", destination: "/research/experiments", permanent: false },
      // Every folded surface (and its sub-paths) → the Strategies screener, the new home.
      ...FOLDED_TO_STRATEGIES.flatMap((src) => [
        { source: src, destination: "/strategies", permanent: false },
        { source: `${src}/:path*`, destination: "/strategies", permanent: false },
      ]),
    ];
  },
};

export default nextConfig;
