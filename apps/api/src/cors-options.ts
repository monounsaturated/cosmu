import type { CorsOptions } from "cors";
import { env } from "./env.js";

const vercelPreviewsAllowed = () => env.CORS_ALLOW_VERCEL_PREVIEWS !== "false";

const extraOrigins = () => {
  const raw = env.CORS_EXTRA_ORIGINS?.trim();
  if (!raw) return [] as string[];
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
};

const isLocalhostOrigin = (origin: string) => {
  try {
    const u = new URL(origin);
    return u.protocol === "http:" && (u.hostname === "localhost" || u.hostname === "127.0.0.1");
  } catch {
    return false;
  }
};

const isVercelPreviewOrigin = (origin: string) => {
  if (!vercelPreviewsAllowed()) return false;
  try {
    const u = new URL(origin);
    return u.protocol === "https:" && u.hostname.endsWith(".vercel.app");
  } catch {
    return false;
  }
};

export const corsOriginAllows = (origin: string | undefined): boolean => {
  if (!origin) return true;
  if (env.WEB_BASE_URL && origin === env.WEB_BASE_URL) return true;
  if (extraOrigins().includes(origin)) return true;
  if (isVercelPreviewOrigin(origin)) return true;
  if (isLocalhostOrigin(origin)) return true;
  return false;
};

/** Returns undefined to mirror cors package "allow any origin" behavior. */
export const buildCorsOptions = (): CorsOptions | undefined => {
  if (env.CORS_ALLOW_ANY_ORIGIN === "true") {
    return undefined;
  }
  return {
    origin: (origin, callback) => {
      if (corsOriginAllows(origin)) {
        callback(null, origin || true);
      } else {
        callback(new Error("Not allowed by CORS"));
      }
    }
  };
};

export const corsDiagnostics = () => ({
  allowAnyOrigin: env.CORS_ALLOW_ANY_ORIGIN === "true",
  webBaseUrlConfigured: Boolean(env.WEB_BASE_URL),
  extraOriginsCount: extraOrigins().length,
  vercelPreviewHostnamesAllowed: vercelPreviewsAllowed(),
  localhostAllowed: true
});
