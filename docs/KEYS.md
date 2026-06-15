# Keys

The canonical table of every secret/key Cosmu can use: what it unlocks, whether it's required, free or
paid, and where to set it. This is the single source of truth that the Settings → Keys page (read-only) and
`GET /settings/keys` reflect.

## Principles

- **Keys live on the engine, never in the browser.** They are read from the engine's environment into typed
  settings (`apps/engine/cosmu/config/settings.py`). The web app never sees a key's value — only a boolean
  `configured` flag via `GET /settings/keys`.
- **Research runs offline.** The deterministic edge/cross-asset gates, the strategy lab, and the scorer all
  run with **zero** API keys (synthetic fixtures + free keyless providers). Keys only unlock *real* data,
  *paid* LLM authoring, or *live* execution.
- **Live trading stays off by default.** Execution keys do nothing until the Gate has passed on real data and
  you explicitly arm live on the Live screen.

## Requirement legend

- **required** — the deployment needs it to do its core job (here: secure the API).
- **optional** — unlocks an extra/paid path; the app is fully functional without it.
- **live-only** — only needed once you arm real-money trading.

## Where to set

All keys are **engine** environment variables (set on Railway, or in a local `.env.local` for dev). The web
app needs two **server-side** vars to reach the engine:

- `API_BASE_URL` — the engine URL (used by Next.js server components and the `/api/engine` proxy).
- `API_SECRET_KEY` — must match the engine's `API_SECRET_KEY`; the proxy injects it as `X-API-Key`.
- `NEXT_PUBLIC_API_BASE_URL` — client "is the engine wired?" flag (no secret; any truthy value enables the
  interactive surfaces, which then call the engine through the same-origin proxy).

## The table

| Key | Env var | Unlocks | Requirement | Free/Paid | Where to add |
| --- | --- | --- | --- | --- | --- |
| API secret | `API_SECRET_KEY` | Locks the control-plane API — the web app sends it via the proxy; nobody else can call the engine. When unset, the API is open (fine for local dev only). | required | free | Engine env (Railway) + web env (must match) |
| xAI (Grok) | `XAI_API_KEY` | LLM strategy authoring (preferred provider). Research still runs offline without it. | optional | paid | Engine env (Railway) |
| OpenRouter | `OPENROUTER_API_KEY` | LLM authoring fallback when xAI is not set. | optional | paid | Engine env (Railway) |
| LunarCrush | `LUNARCRUSH_API_KEY` | Social-sentiment scores **and a real (non-synthetic) edge-gate verdict**. Until a real source is wired, the gate shows an honest "needs real data" state — never a synthetic PASS. | optional | paid | Engine env (Railway) |
| FRED | `FRED_API_KEY` | Macro-regime cross-asset source (free key from the St. Louis Fed). | optional | free | Engine env (Railway) |
| Polymarket | `POLYMARKET_TOKEN` | Prediction-market risk-on cross-asset source. A market token id, **not a secret**. | optional | free | Engine env (Railway) |
| Polymarket (live) | `POLYMARKET_PRIVATE_KEY` (+ optional `POLYMARKET_API_KEY` / `POLYMARKET_API_SECRET` / `POLYMARKET_PASSPHRASE` / `POLYMARKET_FUNDER_ADDRESS` / `POLYMARKET_SIGNATURE_TYPE`) | Real-money execution on the Polymarket CLOB (Polygon, USDC). Honored ONLY with `live.mode=="real"`; testnet key takes precedence. L2 API creds are derived from the signing key when omitted. Install `pip install -e ".[live]"` (py-clob-client). | live-only | free | Engine env (Railway) |
| Polymarket (testnet) | `POLYMARKET_TESTNET_PRIVATE_KEY` (+ optional testnet API creds) | Paper execution against the Polymarket Amoy (Polygon testnet) CLOB. | optional | free | Engine env (Railway) |
| Binance (live) | `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Real-money execution on Binance spot. Only needed once you arm live trading. | live-only | free | Engine env (Railway) |
| Binance (testnet) | `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` | Paper execution against Binance testnet (testnet.binance.vision). | optional | free | Engine env (Railway) |
| Alpaca (paper) | `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET` | US equities market data (IEX feed) + free paper execution — the equity data/forward-test lane (`adapters/data/alpaca.py`, `adapters/exec/alpaca.py`). Free account at alpaca.markets. | optional | free | Engine env (Railway) |
| Alpaca (live) | `ALPACA_API_KEY` / `ALPACA_API_SECRET` | Real-money US equities execution on Alpaca. Honored ONLY with `live.mode=="real"` — paper keys always take precedence. | live-only | free | Engine env (Railway) |
| Slack alerts | `SLACK_WEBHOOK_URL` | Ops alerts to a Slack channel. | optional | free | Engine env (Railway) |

> "Free/Paid" is the cost of the **key/account**, not of trading itself. Binance keys are free to create;
> you still pay venue fees when you trade.

## Notes per key

- **`API_SECRET_KEY`** — set the **same** value on the engine and the web app. The engine's middleware
  rejects any request without a matching `X-API-Key` header (except `/health` and the OpenAPI docs, which
  stay open for liveness probes). The web app's `/api/engine` proxy injects the header server-side, so the
  secret never reaches the browser. If `API_SECRET_KEY` is unset on the engine, the gate is a no-op
  (keyless local dev/tests).
- **LLM keys (`XAI_API_KEY`, `OPENROUTER_API_KEY`)** — the LLM only *authors and mutates* ideas. It is out
  of the survival/scoring/money path; the deterministic Gate alone decides what survives and gets funded.
- **`LUNARCRUSH_API_KEY` / market bars** — wiring these is what turns the edge gate from a synthetic-fixture
  demo into a genuine stop-or-go verdict on real data.
- **Binance live keys** — present keys never auto-arm anything. Live requires: real-data gate pass + a
  two-click confirmation on the Live screen.
- **Polymarket live keys** (`POLYMARKET_PRIVATE_KEY`) — the Polygon signing key for the CLOB execution
  adapter (`adapters/exec/polymarket.py`). Same never-auto-live interlock as Binance: honored ONLY with
  `live.mode=="real"`, and `POLYMARKET_TESTNET_PRIVATE_KEY` (Amoy) always takes precedence. The signing key
  is read once into the adapter's factory closure and is never stored on the instance, logged, or returned.
  Supplying `POLYMARKET_API_KEY`/`_SECRET`/`_PASSPHRASE` (the CLOB L2 creds) avoids a per-resolve network
  derive; absent them, py-clob-client derives them from the signing key. CLOB trading is fee-free (0 bps) and
  gasless via Polymarket's relayer; the binding cost is the order-book spread, already charged in SIM.
