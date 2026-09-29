-- Migration: add target_vol to tracks (T1 vol-target sizing).
-- target_vol = median EWMA vol of the underlying asset's price returns over the backtest validation window,
-- frozen at funding time. NULL → track uses T0 static sizing (max_position_pct × conviction). NOT NULL →
-- paper/live executor uses the vol-target envelope: f = clamp(target_vol/realized_vol × conviction, floor, cap).
-- Safe to apply before or after deploy: NULL is the T0-compatible default; no data loss; no cascade.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS target_vol REAL;
