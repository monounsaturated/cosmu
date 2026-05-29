import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { z } from "zod";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function findRepoRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 12; i++) {
    if (fs.existsSync(path.join(dir, "pnpm-workspace.yaml"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(__dirname, "../../..");
}

const repoRoot = findRepoRoot();
// Load local files without overriding process env so Railway/Vercel secrets always win.
dotenv.config({ path: path.join(repoRoot, ".env.local") });
dotenv.config({ path: path.join(repoRoot, ".env") });

const optionalNonEmptyString = z.preprocess(
  (value) => {
    if (typeof value === "string" && value.trim().length === 0) return undefined;
    return value;
  },
  z.string().min(1).optional()
);

const optionalUrlString = z.preprocess(
  (value) => {
    if (typeof value === "string" && value.trim().length === 0) return undefined;
    return value;
  },
  z.string().url().optional()
);

const envSchema = z.object({
  API_PORT: z.coerce.number().optional(),
  PORT: z.coerce.number().optional(),
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),
  DATABASE_SSL: z.preprocess(
    (value) => {
      if (value === undefined || value === "") return undefined;
      return String(value).trim().toLowerCase();
    },
    z.enum(["true", "false"]).optional()
  ),
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
  XAI_API_KEY: optionalNonEmptyString,
  NOUS_API_KEY: optionalNonEmptyString,
  NOUS_BASE_URL: optionalUrlString,
  OPENAI_API_KEY: optionalNonEmptyString,
  OPENAI_BASE_URL: optionalUrlString,
  ANTHROPIC_API_KEY: optionalNonEmptyString,
  ANTHROPIC_BASE_URL: optionalUrlString,
  HUGGINGFACE_API_KEY: optionalNonEmptyString,
  HF_TOKEN: optionalNonEmptyString,
  HUGGINGFACE_BASE_URL: optionalUrlString,
  GOOGLE_API_KEY: optionalNonEmptyString,
  GEMINI_API_KEY: optionalNonEmptyString,
  GOOGLE_BASE_URL: optionalUrlString,
  GEMINI_BASE_URL: optionalUrlString,
  MISTRAL_API_KEY: optionalNonEmptyString,
  MISTRAL_BASE_URL: optionalUrlString,
  BINANCE_API_KEY: optionalNonEmptyString,
  BINANCE_API_SECRET: optionalNonEmptyString,
  BINANCE_TESTNET_API_KEY: optionalNonEmptyString,
  BINANCE_TESTNET_API_SECRET: optionalNonEmptyString,
  SLACK_WEBHOOK_URL: optionalUrlString,
  TRADING_AGENTS_URL: optionalUrlString,
  API_SECRET_KEY: z.string().min(32, "API_SECRET_KEY must be at least 32 characters")
});

const parsedEnv = envSchema.parse(process.env);

export const env = {
  ...parsedEnv,
  HUGGINGFACE_API_KEY: parsedEnv.HUGGINGFACE_API_KEY ?? parsedEnv.HF_TOKEN,
  GOOGLE_API_KEY: parsedEnv.GOOGLE_API_KEY ?? parsedEnv.GEMINI_API_KEY,
  GOOGLE_BASE_URL: parsedEnv.GOOGLE_BASE_URL ?? parsedEnv.GEMINI_BASE_URL,
  API_PORT: parsedEnv.PORT ?? parsedEnv.API_PORT ?? 4000
};
