import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  API_PORT: z.coerce.number().optional(),
  PORT: z.coerce.number().optional(),
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),
  WEB_BASE_URL: z.string().url().default("http://localhost:3000"),
  XAI_API_KEY: z.string().min(1, "XAI_API_KEY is required"),
  BINANCE_API_KEY: z.string().min(1, "BINANCE_API_KEY is required"),
  BINANCE_API_SECRET: z.string().min(1, "BINANCE_API_SECRET is required"),
  SLACK_WEBHOOK_URL: z.string().url().optional()
});

const parsedEnv = envSchema.parse(process.env);

export const env = {
  ...parsedEnv,
  API_PORT: parsedEnv.API_PORT ?? parsedEnv.PORT ?? 4000
};
