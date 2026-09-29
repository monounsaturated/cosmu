import type { NextConfig } from "next";

// Static landing page — no server, no engine. `output: "export"` keeps it deployable anywhere (Vercel free).
const nextConfig: NextConfig = {
  output: "export",
  devIndicators: false,
  images: { unoptimized: true },
};

export default nextConfig;
