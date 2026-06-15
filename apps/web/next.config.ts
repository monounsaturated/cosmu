import type { NextConfig } from "next";

// The v18 redesign is the whole frontend: SIX surfaces — Strategies · Paper · Live · Costs · Keys ·
// Commands (landing = Strategies). The previous app's research/knowledge/ops pages were folded; their
// backend data keeps accruing, but the pages are gone from the UI. These redirects keep any old URL
// (bookmarks, deep links) working by sending it to the nearest surviving surface — no 404s, no clutter.
const FOLDED_TO_STRATEGIES = [
  "/overview",
  "/console",
  "/lab",
  "/verdicts",
  "/correlations",
  "/explorer",
  "/mind",
  "/research",
  "/scores",
  "/steer",
  "/farm",
  "/settings",
];

const nextConfig: NextConfig = {
  devIndicators: false,
  async redirects() {
    return [
      // forward_test → paper rename: the old name lands on the Paper dashboard.
      { source: "/paper", destination: "/paper", permanent: false },
      // Every folded surface (and its sub-paths) → the Strategies screener, the new home.
      ...FOLDED_TO_STRATEGIES.flatMap((src) => [
        { source: src, destination: "/strategies", permanent: false },
        { source: `${src}/:path*`, destination: "/strategies", permanent: false },
      ]),
    ];
  },
};

export default nextConfig;
