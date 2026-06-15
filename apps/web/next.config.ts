import type { NextConfig } from "next";

// The v18 redesign is the whole frontend: SEVEN surfaces — Strategies · Paper · Live · Costs · Research ·
// Keys · Commands (landing = Strategies). Most of the previous app's knowledge/ops pages were folded; their
// backend data keeps accruing, but the pages are gone from the UI. These redirects keep any old URL
// (bookmarks, deep links) working by sending it to the nearest surviving surface — no 404s, no clutter.
// EXCEPTION: /research is UN-folded — it now hosts the Experiments surface (the machine's tested-theory
// memory from gate_verdicts), so it must NOT be in the folded list or its catch-all would shadow the page.
const FOLDED_TO_STRATEGIES = [
  "/overview",
  "/console",
  "/lab",
  "/verdicts",
  "/correlations",
  "/explorer",
  "/mind",
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
