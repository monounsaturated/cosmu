# SETUP — External APIs & Keys

The engine runs with **zero keys** (free keyless providers + offline fixtures).
Keys unlock real data, LLM authoring, or live execution. Nothing auto-arms live trading — that still requires a manual Gate pass + confirmation screen.

Keys live in three places you keep in sync: `.env.local` → Railway dashboard → `pnpm modal:secret`.
See `.env.example` for the exact variable names and a fill-in template.

---

## Key table

| Key (env var) | What it does | Required? | Where to get it | Cost tier |
|---|---|---|---|---|
| `DATABASE_URL` | Supabase Postgres connection string (transaction pooler, port 6543) | **required** | [supabase.com](https://supabase.com) → new project → Settings → Database | Free tier (500 MB); Pro $25/mo |
| `API_SECRET_KEY` | Locks the control-plane API; web proxy injects it as `X-API-Key` — set the **same** value on engine (Railway) and web (Vercel) | **required** | Generate locally: `openssl rand -hex 32` | Free |
| `XAI_API_KEY` | LLM strategy authoring via Grok (preferred provider) | optional | [console.x.ai](https://console.x.ai) | Pay-per-token; check vendor |
| `OPENROUTER_API_KEY` | LLM authoring fallback when xAI is unset; routes to Qwen/DeepSeek/Grok/Claude/GPT — free models available | optional | [openrouter.ai/keys](https://openrouter.ai/keys) | Free models available; pay-per-token on paid models |
| `FRED_API_KEY` | Macro series (rates, yields, DXY, credit spreads) via St. Louis Fed | optional | [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html) | Free |
| `LUNARCRUSH_API_KEY` | Social/sentiment scores; turns edge-gate from synthetic fixture into a real verdict | optional | [lunarcrush.com/developers](https://lunarcrush.com/developers) | Paid (no free tier as of 2026); check vendor |
| `POLYMARKET_TOKEN` | Prediction-market risk-on signal (a market token ID, not a secret) | optional | [polymarket.com](https://polymarket.com) | Free |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Real-money execution on Binance spot — only active when live mode = `real` and you explicitly arm it | live-only | [binance.com/en/my/settings/api-management](https://www.binance.com/en/my/settings/api-management) | Free to create; venue fees apply on trades |
| `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` | Testnet execution (fake money, real mechanics) | optional | [testnet.binance.vision](https://testnet.binance.vision) | Free |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | Authenticates non-interactive `modal run` from Claude Code / CI | optional (or run `modal setup` once locally) | [modal.com/settings/tokens](https://modal.com/settings/tokens) | Usage-based; generous free credits; check vendor |
| `SLACK_WEBHOOK_URL` | Ops alerts to a Slack channel | optional | Slack → Your App → Incoming Webhooks | Free |
| `RAILWAY_API_TOKEN` | Fetches Railway spend for the cost dashboard | optional | [railway.app/account/tokens](https://railway.app/account/tokens) | Free; Railway hosting starts ~$5/mo hobby |

### Web-only (Vercel / Next.js)

| Key (env var) | What it does | Required? |
|---|---|---|
| `API_BASE_URL` | Engine URL used by Next.js server components | required |
| `NEXT_PUBLIC_API_BASE_URL` | Client-side flag to enable interactive surfaces | required |

---

> **Unused in engine right now** — `NOUS_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `HUGGINGFACE_API_KEY` appear in `.env.example` for future adapters but are not read by the engine settings. Leave them blank.
