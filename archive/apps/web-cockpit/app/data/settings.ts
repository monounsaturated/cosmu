import type { SettingsKeyRow, SettingsKeysResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

// GET /settings/keys — the read-only key inventory for Settings → Keys: which provider keys are
// configured on the engine and what each unlocks. SECURITY: the engine returns a boolean `configured`
// per key, NEVER the value. Honest empty/offline when the engine is unreachable.
const emptySettingsKeys: SettingsKeysResponse = { rows: [] };

export async function getSettingsKeys(): Promise<{ keys: SettingsKeyRow[]; connected: boolean }> {
  const { data, connected } = await getJson<SettingsKeysResponse>("/settings/keys", emptySettingsKeys);
  // Coalesce rows — the default only applies on a failed fetch; a partial success could still omit it.
  return { keys: data.rows ?? [], connected };
}
