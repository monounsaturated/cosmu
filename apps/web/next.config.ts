import type { NextConfig } from "next";

const sharedDistEntry = new URL("../../packages/shared/dist/index.js", import.meta.url).pathname;
const sharedDistEntryForTurbopack = "../../packages/shared/dist/index.js";

const nextConfig: NextConfig = {
  devIndicators: false,
  turbopack: {
    resolveAlias: {
      "@cosmu/shared": sharedDistEntryForTurbopack
    },
    resolveExtensions: [".tsx", ".ts", ".jsx", ".js", ".mjs", ".json"]
  },
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@cosmu/shared": sharedDistEntry
    };
    return config;
  }
};

export default nextConfig;
