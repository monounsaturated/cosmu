#!/usr/bin/env node
/**
 * Script to fetch available models from xAI API and display them.
 * Run with: XAI_API_KEY=your_key npx tsx scripts/fetch-xai-models.ts
 */

import "dotenv/config";

const XAI_API_KEY = process.env.XAI_API_KEY;

if (!XAI_API_KEY) {
  console.error("Error: XAI_API_KEY environment variable is required");
  console.error("Usage: XAI_API_KEY=your_key npx tsx scripts/fetch-xai-models.ts");
  process.exit(1);
}

async function fetchXaiModels() {
  console.log("Fetching models from xAI API...\n");

  try {
    const response = await fetch("https://api.x.ai/v1/models", {
      headers: {
        Authorization: `Bearer ${XAI_API_KEY}`,
        "Content-Type": "application/json"
      },
      signal: AbortSignal.timeout(10000)
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`API Error: ${response.status} ${response.statusText}`);
      console.error(`Response: ${errorText}`);
      process.exit(1);
    }

    const data = await response.json();
    const models = Array.isArray(data?.data) ? data.data : [];

    console.log(`Found ${models.length} models from xAI:\n`);
    console.log("─".repeat(60));

    // Sort by creation date (newest first)
    const sortedModels = models
      .map((row: { id?: string; created?: number; object?: string; owned_by?: string }) => ({
        id: row.id ?? "",
        created: typeof row.created === "number" ? row.created : null,
        object: row.object,
        owned_by: row.owned_by
      }))
      .filter((m: { id: string }) => m.id.length > 0)
      .sort((a: { created: number | null }, b: { created: number | null }) => {
        if (!a.created || !b.created) return 0;
        return b.created - a.created;
      });

    for (const model of sortedModels) {
      const createdDate = model.created
        ? new Date(model.created * 1000).toISOString().split("T")[0]
        : "unknown";
      console.log(`Model ID:     ${model.id}`);
      console.log(`Created:      ${createdDate}`);
      if (model.object) console.log(`Object:       ${model.object}`);
      if (model.owned_by) console.log(`Owned by:     ${model.owned_by}`);
      console.log("─".repeat(60));
    }

    // Output SQL insert statements for easy database insertion
    console.log("\n\n-- SQL INSERT statements for model_profiles table:\n");
    console.log("-- Run these in your database to add all available models:\n");

    for (const model of sortedModels) {
      const profileName = `xAI ${model.id}`;
      console.log(
        `INSERT INTO model_profiles (name, provider, model, settings) VALUES ('${profileName}', 'xai', '${model.id}', '{"temperature":0.2}'::jsonb) ON CONFLICT (name) DO UPDATE SET provider = excluded.provider, model = excluded.model, settings = model_profiles.settings;`
      );
    }

    // Output JSON for programmatic use
    console.log("\n\n-- JSON format for API usage:\n");
    const modelProfiles = sortedModels.map((model: { id: string }) => ({
      name: `xAI ${model.id}`,
      provider: "xai",
      model: model.id,
      settings: { temperature: 0.2 }
    }));
    console.log(JSON.stringify(modelProfiles, null, 2));

  } catch (error) {
    console.error("Error fetching models:", error);
    process.exit(1);
  }
}

fetchXaiModels();
