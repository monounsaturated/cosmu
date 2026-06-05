import type { Event, Recommendation } from "@cosmu/contracts-ts";
import { getJson } from "./client";

export async function getRecommendations(): Promise<{ items: Recommendation[]; connected: boolean }> {
  const { data, connected } = await getJson("/recommendations", { items: [] as Recommendation[] });
  return { items: data.items, connected };
}

export async function getEvents(): Promise<{ events: Event[]; connected: boolean }> {
  const { data, connected } = await getJson("/events", { events: [] as Event[] });
  return { events: data.events, connected };
}
