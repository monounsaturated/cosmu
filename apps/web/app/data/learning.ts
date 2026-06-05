import type {
  MemoryInsight,
  MemoryInsightsResponse,
  Skill,
  SkillsResponse,
} from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptySkills: SkillsResponse = { skills: [] };

const emptyInsights: MemoryInsightsResponse = { insights: [] };

// GET /skills — distilled skill recipes the brain has learned (the flywheel made visible). Empty
// when the brain hasn't distilled any reusable recipe yet.
export async function getSkills(): Promise<{ skills: Skill[]; connected: boolean }> {
  const { data, connected } = await getJson("/skills", emptySkills);
  return { skills: data.skills, connected };
}

// GET /memory/insights — dead-ends the brain avoids and winner patterns it leans into.
export async function getInsights(): Promise<{ insights: MemoryInsight[]; connected: boolean }> {
  const { data, connected } = await getJson("/memory/insights", emptyInsights);
  return { insights: data.insights, connected };
}
