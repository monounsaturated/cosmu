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
