// Barrel: re-exports everything from every domain module so that existing imports of the form
//   import { getX } from "@/app/data"
// continue to resolve unchanged after the monolithic data.ts was split into this directory.

export * from "./client";
export * from "./overview";
export * from "./costs";
export * from "./live";
export * from "./settings";
export * from "./research";
export * from "./mind";
export * from "./conviction";
