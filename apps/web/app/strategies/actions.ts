"use server";

import { getStrategy } from "../data";
import type { StrategyDetailResponse } from "@cosmu/contracts-ts";

export async function fetchStrategyDetail(
  versionId: string
): Promise<{ strategy: StrategyDetailResponse; connected: boolean }> {
  return getStrategy(versionId);
}
