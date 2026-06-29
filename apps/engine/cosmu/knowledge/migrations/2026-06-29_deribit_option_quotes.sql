-- Migration: deribit_option_quotes — the APPEND-ONLY, point-in-time capture log for the Deribit forward options
-- logger (cosmu.options.logger). NOT YET APPLIED — the operator applies it (and deploys the cron) when they want a
-- DB-backed hoard; until then the logger writes the IDENTICAL row shape to local JSONL (cosmu.options.sink) and,
-- optionally, R2. This table is 1:1 with cosmu.options.sink.snapshot_to_rows, so `\copy` of the JSONL lands here
-- directly. RESEARCH substrate only — the money/Gate paths never read it (it is not a feature source).
--
-- Append-only & PIT: one row per (instrument) per POLL, stamped with capture_ts = the instant WE observed it (NOT a
-- Deribit field — Deribit publishes no historical L2, so our own capture time is the only honest PIT). A vendor
-- revision is a NEW row at a later capture_ts, never an UPDATE. Prices are COIN-denominated (× index_price → USD),
-- exactly as Deribit publishes them; sizes are in contracts (== coin units). bid_size/ask_size/greeks are NULL for
-- the cheap whole-chain (book_summary) rows and populated only on the order-book-enriched long-tail subset.
CREATE TABLE IF NOT EXISTS deribit_option_quotes (
  id               BIGSERIAL PRIMARY KEY,
  capture_ts       TIMESTAMPTZ NOT NULL,         -- PIT: when WE polled (the only honest forward timestamp)
  currency         TEXT        NOT NULL,         -- BTC / ETH / ...
  instrument       TEXT        NOT NULL,         -- e.g. BTC-25DEC26-58000-C
  expiry           DATE        NOT NULL,
  strike           NUMERIC     NOT NULL,         -- USD
  option_type      TEXT        NOT NULL CHECK (option_type IN ('C', 'P')),
  index_price      NUMERIC,                      -- underlying USD index at capture
  dvol             NUMERIC,                      -- 30d implied-vol index (crypto VIX) at capture
  bid_price        NUMERIC,                      -- COIN (× index_price → USD); NULL = unquoted side
  ask_price        NUMERIC,                      -- COIN
  mark_price       NUMERIC,                      -- COIN
  mark_iv          NUMERIC,                      -- percent
  bid_size         NUMERIC,                      -- contracts at the touch; NULL until order-book-enriched
  ask_size         NUMERIC,                      -- contracts at the touch; NULL until order-book-enriched
  open_interest    NUMERIC,
  volume           NUMERIC,
  underlying_price NUMERIC,                      -- per-expiry forward Deribit reports (USD)
  delta            NUMERIC,                      -- greeks: NULL until order-book-enriched
  gamma            NUMERIC,
  vega             NUMERIC,
  theta            NUMERIC
);

-- Read paths: "the whole chain as-of a capture" and "this instrument's capture history".
CREATE INDEX IF NOT EXISTS idx_deribit_opt_ccy_capture ON deribit_option_quotes (currency, capture_ts);
CREATE INDEX IF NOT EXISTS idx_deribit_opt_instrument  ON deribit_option_quotes (instrument, capture_ts);
