import { sql } from "../../db.js";

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
