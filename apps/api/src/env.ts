import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  API_PORT: z.coerce.number().optional(),
  PORT: z.coerce.number().optional(),
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),
  WEB_BASE_URL: z.preprocess(
    (value) => {
      if (typeof value === "string" && value.trim().length === 0) {
        return undefined;
      }

      return value;
    },
    z.string().url().optional()
  ),
  /** Comma-separated extra allowed browser origins (e.g. https://app.example.com). */
  CORS_EXTRA_ORIGINS: z.preprocess(
    (value) => {
      if (typeof value === "string" && value.trim().length === 0) {
        return undefined;
      }
      return value;
    },
    z.string().optional()
  ),
  /** When "false", HTTPS *.vercel.app preview URLs are not auto-allowed. Default: allow. */
  CORS_ALLOW_VERCEL_PREVIEWS: z.preprocess(
    (value) => {
      if (value === undefined || value === "") return undefined;
      return String(value).trim().toLowerCase();
    },
    z.enum(["true", "false"]).optional()
  ),
  /** When "true", CORS allows any origin (old behavior when WEB_BASE_URL was unset). Prefer explicit origins. */
  CORS_ALLOW_ANY_ORIGIN: z.preprocess(
    (value) => {
      if (value === undefined || value === "") return undefined;
      return String(value).trim().toLowerCase();
    },
    z.enum(["true", "false"]).optional()
  ),
  XAI_API_KEY: z.string().min(1, "XAI_API_KEY is required"),
  BINANCE_API_KEY: z.string().min(1, "BINANCE_API_KEY is required"),
  BINANCE_API_SECRET: z.string().min(1, "BINANCE_API_SECRET is required"),
  SLACK_WEBHOOK_URL: z.string().url().optional(),
  API_SECRET_KEY: z.string().min(32, "API_SECRET_KEY must be at least 32 characters")
});

const parsedEnv = envSchema.parse(process.env);

export const env = {
  ...parsedEnv,
  API_PORT: parsedEnv.PORT ?? parsedEnv.API_PORT ?? 4000
};
