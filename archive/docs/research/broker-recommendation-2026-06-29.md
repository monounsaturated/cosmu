# Broker recommendation — COSMU (FR-resident solo quant fund) — 2026-06-29

**Question:** Which REAL execution broker(s) does COSMU use? Alpaca is **paper-emulation ONLY** (not FR-available);
we need the live TradFi broker + the crypto venue, both FR-resident-available, API-connectable, low-fee, trustworthy,
and — for TradFi — **fractional** (a ~$100 arm on a ~$550 ETF is impossible without fractional shares).

**Bottom line:** **IBKR (Interactive Brokers Ireland)** is the TradFi broker — it is the only FR-available, officially-API'd,
trustworthy broker that *also* does fractional on both US and European stocks/ETFs. **Kraken** is the crypto venue.
**Create Kraken FIRST** (zero adapter work, crypto natively fractional, an adapter already exists in our code), IBKR
second (it needs a brand-new exec adapter — see §5). There is **no funded edge and the live lane is not the bottleneck yet**,
so neither account is urgent; when we do open, the order is Kraken → IBKR.

---

## 1. TradFi broker: IBKR — meets ALL criteria, fractional CONFIRMED YES

| Criterion | IBKR | Verdict |
|---|---|---|
| FR-resident available | Yes — onboarded via **Interactive Brokers Ireland Ltd** (Central Bank of Ireland / ESMA regulated) post-Brexit | ✅ |
| API-connectable | Yes — two official APIs (TWS API + the new unified **IBKR Web API**, OAuth 2.0 REST). See §5. | ✅ |
| Low fees | IBKR **Pro Tiered/Fixed**. US stocks/ETFs ~USD 0.0035/sh (min $0.35). Western-European stocks **~€3/trade** for typical sizes, **0.05% of trade value above €6,000**; Euronext ETF exchange fee ~€0.75/execution passed through. Our codebase already models **~1 bp/side all-in on liquid ETFs** (`IBKR_ETF_BPS_PER_SIDE = 1.0`). | ✅ |
| Many assets | Global multi-asset: US/EU/UK/Asia stocks, ETFs, options, futures, bonds, FX. The widest of any retail-accessible broker. | ✅ |
| Trustworthy | Public (NASDAQ: IBKR), ~50yr operator, deep balance sheet, the de-facto quant/algo broker. | ✅ |
| **Fractional shares** | **YES.** ~22,825 US/Canadian/European stocks & ETFs eligible for fractional (per IBKR, 4/27/2026); ~10,500+ US fractional. **USD 1 minimum**, price-independent. EU fractional gated to names with avg daily volume > $5M and mkt cap > $5B (i.e. all the liquid ETFs we trade qualify). Monetary-value orders via the **`cashQty`** parameter — submit "$100 of SPY" directly, the venue computes the fraction. | ✅ |

**Note — IBKR Lite is NOT available in France.** Lite (commission-free US) is US/Singapore-retail only. French residents get
**IBKR Pro** (Fixed or Tiered commissions). This is the correct, expected tier for an automated fund and does not change the
recommendation — Pro Tiered is cheap at our size and is the algo-grade product.

**`cashQty` is the load-bearing fact for us:** our equity strategies arm in ~$100–$1000 sleeves against ETFs priced
$300–$600 (SPY ~$550). Without fractional / monetary-value orders we could not deploy a single equity arm faithfully.
IBKR's `cashQty` makes "spend exactly $X" a first-class order — a cleaner fractional path than computing a fractional
share count ourselves.

### Why our code already assumes IBKR
The equity-TAA strategies — per memory the **STRONGEST surviving edge** (DAA/VAA/ADM, forward since 2026-06-07) — are
**already paper-marked against IBKR fees today**: `VENUE = "ibkr"` and `IBKR_ETF_BPS_PER_SIDE = 1.0` appear across
`equity_daa_arm.py`, `equity_dual_momentum_arm.py`, `equity_risk_parity*.py`, `equity_faber_gtaa.py`,
`replication_cohort.py`, `matrix_search.py`. The taxonomy renders them `equity / IBKR / 1d`. So IBKR is *already the
designated live equity venue in the research layer* — the only thing missing is the execution adapter to route those
paper tracks to real money (§4–§5). This makes IBKR the obvious, low-surprise choice: the fee model and venue tag are
already wired; only the order plumbing is absent.

## 2. Alternatives considered — none beats IBKR (most fail "fractional" or "official API")

| Broker | FR avail | Official API | Fractional (stocks/ETF) | Verdict |
|---|---|---|---|---|
| **IBKR** | ✅ (IB Ireland) | ✅ TWS + Web API (OAuth2) | ✅ US **and** EU, `cashQty` | **PRIMARY** |
| **Saxo Bank** | ✅ | ✅ OpenAPI (REST+streaming, solid) | ❌ **No fractional stocks/ETFs** (only crypto-FX & CFD indices) | **Reject — fails hard criterion** |
| **Trade Republic** | ✅ | ❌ **No official/public API** (only unofficial reverse-engineered libs — `pytr` etc.) | ✅ (in-app) | **Reject — un-automatable / untrustworthy for money path** |
| **Trading 212** | ✅ | ⚠️ REST API exists but **beta**, limited order/instrument coverage, retail-grade | ✅ | **Weak fallback only** — not a serious automated-fund venue |
| **DEGIRO** | ✅ | ❌ No official trading API | ❌ No fractional | Reject |
| **Lynx** | ✅ | ✅ (it is an **IBKR introducing broker** — same TWS API + IBKR rails) | ✅ (IBKR fractional) | Redundant with IBKR; just use IBKR directly |

**Saxo's OpenAPI is genuinely good**, so if IBKR ever blocked us it would be the technical runner-up — but **Saxo has
no fractional equities**, which is disqualifying for $100 arms on $550 ETFs. **There is no FR-available broker that beats
IBKR on the union of {official API, fractional US+EU, low fee, trustworthy}.** IBKR is not a compromise; it's the
correct answer.

## 3. Crypto venue: Kraken — confirmed, already wired

- **FR/EU-legal** via **Payward Europe Ltd** (MiCA); spot trading permitted (only crypto **derivatives** are ESMA-restricted —
  that's the separate `kraken_futures` venue which stays `live_enabled=False`). US-legal via Payward Inc.
- **Official REST + WebSocket API**, well-documented, battle-tested; we drive it through **ccxt** (`ccxt.kraken`).
- **Fees:** spot maker/taker from ~0.25% / ~0.40%, volume-tiered down. (Avoid the 1%/1.5% "Instant Buy" widget — the
  order-book API path is the cheap one and is what the adapter uses.)
- **Fractional:** crypto is **natively fractional** — buy 0.0001 BTC, no special handling.
- **Already implemented** in our code: `apps/engine/cosmu/adapters/exec/kraken.py` (`KrakenSpotExecutionAdapter`,
  disabled-by-default, real money only with `KRAKEN_API_KEY/SECRET` + `live.mode=="real"`). **Zero adapter work to go live.**

Kraken is the crypto venue. (Binance spot also has a live adapter and is the primary crypto-data venue, but Kraken is the
FR-resident live crypto execution venue of record; the jurisdiction note is baked into `kraken.py`.)

## 4. Our code: NO IBKR exec adapter (confirmed)

`apps/engine/cosmu/adapters/exec/` contains: `binance.py`, `kraken.py`, `alpaca.py`, `polymarket.py`,
`_polymarket_clob.py`, `registry.py`, `__init__.py`. **There is no `ibkr.py`.**

The registry hard-codes the wired set:
```python
# apps/engine/cosmu/adapters/exec/registry.py
EXEC_ADAPTER_VENUES: frozenset[str] = frozenset({"binance", "kraken", "alpaca", "polymarket"})
```
**`"ibkr"` is absent** → `adapter_for("ibkr", …)` returns `None` → the live lane sim-fills any IBKR-tagged track instead of
routing real money. This is the precise gap: the equity-TAA winners are tagged `venue="ibkr"`, but with no adapter they can
never leave paper. **The prior audit's finding ("only Alpaca, which is paper") is confirmed** — and worse, the live equity
venue we actually intend (IBKR) has no adapter at all; Alpaca is only a US-paper stand-in (kept correctly paper-default, per
the hard rule).

## 5. Scope: what building an IBKR exec adapter takes

The adapter must implement the `core.ExecutionAdapter` interface (`submit / cancel / positions / fills`, plus the
safety/mode contract every adapter follows). **Alpaca is the closest template** (same asset class = EQUITY, same REST
shape, same `cashQty`-style monetary order, same OCO bracket need) — but **ccxt does NOT support IBKR** (ccxt is
crypto-only), so unlike Kraken/Binance we cannot lean on ccxt. That is the one material difference and the main cost driver.

**Choose the API path — recommend the new IBKR Web API (OAuth 2.0), not TWS/Gateway:**

| Path | Mechanics | Fit for an unattended solo fund |
|---|---|---|
| **TWS API** (`ib_async`, the maintained successor to `ib_insync`) | Needs **TWS or IB Gateway running** as a local process the adapter sockets into. | ❌ Operational drag: **IB Gateway requires daily 2FA re-login via the IBKR mobile app on restart** — a human must approve on the phone. Bad for a headless 24/7 fund. Fractional needs Gateway ≥ v163/1023. |
| **IBKR Web API** (unified Client-Portal/Web API, **OAuth 2.0** `private_key_jwt`, RFC 7521/7523) | Pure **REST over HTTPS**, signed-JWT first-party auth, **no Gateway process**. Supports `cashQty` monetary orders → fractional. | ✅ **Right choice.** Matches our existing pattern (Alpaca is plain `urllib` REST; Kraken/Binance are HTTP-via-ccxt). No daemon, no phone 2FA loop. First-party OAuth2 is supported for accessing one's own account. |

**Concrete work for `apps/engine/cosmu/adapters/exec/ibkr.py` (Web-API path):**

1. **Settings (small):** add `ibkr_*` credential fields to `config/settings.py` following the existing
   `Field(default=None, repr=False)` pattern (e.g. `ibkr_oauth_client_id`, `ibkr_private_key` / key path,
   `ibkr_account_id`). Web-API OAuth2 uses a signed JWT, so we store a private key + client id rather than a key/secret pair.
2. **Auth/transport (the new bit — no ccxt to lean on):** build the OAuth2 `private_key_jwt` flow — sign a `client_assertion`
   JWT, exchange for a bearer token, refresh on expiry, then a thin authed HTTPS transport (mirror Alpaca's
   `_urllib_transport` closure so **secrets live only in the closure, never on the instance/`__repr__`**). This is the bulk
   of the effort; budget for token lifecycle + the Web API's brokerage-session/"tickle" keep-alive.
3. **`resolve_mode` interlock:** copy Kraken/Alpaca exactly — `disabled` default; `live` **only** when keys present **and**
   `live.mode == "real"`. IBKR has a **paper account** too, so optionally support a `paper` mode (paper creds → paper base
   URL) like Alpaca; but **never auto-pick real money**.
4. **`build_order_body` + fractional:** map `core.Order` → IBKR order payload. For fractional/sleeve sizing, prefer
   **`cashQty`** (monetary value) so a "$100 of SPY" arm is exact; fall back to fractional share `qty` where `cashQty`
   order-type isn't accepted (`cqtTypes` advertises which). Map side, `market`/`limit`/`maker`(post-only-limit) like the
   others. **Idempotency:** carry our `client_order_id` (IBKR field `cOID`) so a replayed submit reconciles, never double-fills.
5. **`parse_order_id` / `parse_positions` / `parse_fills`:** pure mappers IBKR JSON → core types (keep them pure +
   unit-tested against canned fixtures, exactly like the Alpaca/Kraken `parse_*`). Fees: read the real commission from
   IBKR's execution/`cashtransactions` data (Pro is **not** commission-free, unlike Alpaca's `fee=0`).
6. **OCO bracket:** IBKR supports OCA/bracket orders natively — port the Alpaca `place_oco_bracket` shape (TP limit + SL stop)
   as best-effort post-fill, never failing the parent buy.
7. **Registry wiring (tiny):** add `"ibkr"` to `EXEC_ADAPTER_VENUES`, an `adapter_for` branch, and `resolve_mode`/
   `keys_present` cases in `registry.py`.
8. **Tests:** unit-test the pure parse/auth-signing layer against fixtures (no network), like the existing adapters.

**Effort estimate: ~2–4 focused days.** The interface, safety contract, registry, and a near-exact REST template (Alpaca)
all exist; ~70% of an adapter is boilerplate we copy. The genuinely new ~30% is the **OAuth2 `private_key_jwt` auth +
session keep-alive** (no ccxt shortcut) and IBKR's `cashQty`/fractional order semantics. Lower-risk than it sounds because
it's additive and SAFE-by-construction (disabled until keys + `live.mode=="real"`), so it can't arm anything by existing.

---

## Which to create FIRST — Kraken

**Kraken first, IBKR second.** Reasoning:
- **No funded edge yet and the app isn't built** → live execution is **not** the binding constraint. Neither account is urgent.
- **Kraken = zero engineering to go live** (adapter already shipped); opening the account is the only step.
- **IBKR needs the new adapter** (§5) before its account is useful — so its account should follow the adapter work, not precede it.
- The **strongest edge is equity-TAA (→ IBKR)**, so IBKR is the higher-value end state — but value-when-ready ≠ create-first.
  Open Kraken to have a live-capable crypto venue with zero lead time; build the IBKR adapter, then open IBKR when there's an
  equity track actually clearing the deployment bar and ready to arm.

**Action order:** (1) open Kraken (account only, leave disabled) → (2) build `ibkr.py` Web-API adapter → (3) open IBKR when
an equity arm is deployment-ready.

---

### Sources
- IBKR fractional trading (US + European, $1 min, eligibility): https://www.interactivebrokers.com/en/trading/fractional-trading.php · https://www.nasdaq.com/press-release/interactive-brokers-introduces-fractional-shares-trading-in-european-stocks-and-etfs
- IBKR European commissions (€3/trade, 0.05% > €6k, Euronext ETF fee): https://www.interactivebrokers.com/en/pricing/commissions-stocks-europe.php
- IBKR US commissions / Lite vs Pro (Lite = US/SG only): https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- IBKR `cashQty` monetary-value stock orders: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/ · https://interactivebrokers.github.io/cpwebapi/
- IBKR Web API OAuth 2.0 `private_key_jwt`, headless (no Gateway): https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/ · https://www.interactivebrokers.com/campus/ibkr-api-page/getting-started/
- TWS API vs Client Portal/Web API, Gateway 2FA constraint, `ib_async`: https://www.interactivebrokers.com/en/trading/ib-api.php · https://github.com/erdewit/ib_insync · https://pypi.org/project/ib_async/
- IBKR available to French residents (IB Ireland): https://brokerchooser.com/broker-reviews/interactive-brokers-review/interactive-brokers-france
- ccxt is crypto-only (no IBKR): https://pypi.org/project/ccxt/
- Saxo OpenAPI + NO fractional stocks/ETFs: https://www.home.saxo/platforms/api · https://www.help.saxo/hc/en-us/articles/4413408055953-Does-Saxo-offer-fractional-trading
- Trade Republic — no official API (unofficial only): https://github.com/Zarathustra2/TradeRepublicApi · https://pypi.org/project/pytr/
- Trading 212 public REST API (beta): https://docs.trading212.com/api · https://t212public-api-docs.redoc.ly/
- Kraken fees / API / MiCA FR-EU: https://www.kraken.com/features/fee-schedule · https://www.kraken.com/features/trading-api
