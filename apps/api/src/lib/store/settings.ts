import { sql } from "../../db.js";
import { appSettingsSchema, defaultAppSettings, type AppSettings } from "@cosmu/shared";

const APP_SETTINGS_KEY = "app_settings_v1";

export const getAppSetting = async (key: string): Promise<string | null> => {
  try {
    const [row] = await sql<{ value: string }[]>`
      select value from app_settings where key = ${key} limit 1
    `;
    return row?.value ?? null;
  } catch {
    return null;
  }
};

export const setAppSetting = async (key: string, value: string) => {
  await sql`
    insert into app_settings (key, value, updated_at)
    values (${key}, ${value}, now())
    on conflict (key) do update set value = excluded.value, updated_at = now()
  `;
};

export const getAppSettings = async (): Promise<AppSettings> => {
  const raw = await getAppSetting(APP_SETTINGS_KEY);
  if (!raw) return defaultAppSettings;

  try {
    return appSettingsSchema.parse(JSON.parse(raw));
  } catch (error) {
    console.warn("Invalid app settings, falling back to defaults:", String(error));
    return defaultAppSettings;
  }
};

export const setAppSettings = async (value: unknown): Promise<AppSettings> => {
  const parsed = appSettingsSchema.parse(value);
  await setAppSetting(APP_SETTINGS_KEY, JSON.stringify(parsed));
  return parsed;
};
