---
name: add-venue
description: Add a trading venue or asset class (data + optional execution adapter) with REAL per-venue fees and jurisdiction legality. Use when wiring a new exchange/broker/market (e.g. Kraken, IBKR, Polymarket) or asset class.
---

# add-venue

Add a venue with **real, volume-tiered fees** and explicit jurisdiction legality. Fees are the single source of truth in the catalog — the screen, gate, and forward-test all price against `catalog.venue_for(spec.universe.venues)`, so a new venue is priced correctly by construction.

## Steps (mirror `docs/CODING_STANDARDS.md` "Adding a venue / asset class")
1. **Catalog entry** in `cosmu/spine/venue.py` `default_catalog()`: a `Venue` with real `maker_fee_bps`/`taker_fee_bps`, `fee_tiers` (30d-volume tiers), `min_notional`/`lot_size`, `live_enabled` (False for data/research-only venues), and `restricted_jurisdictions` (ISO-3166 alpha-2). Add its `Instrument`s.
2. **DataAdapter** in `cosmu/adapters/data/<venue>.py`: implement the `core/interfaces.py` `DataAdapter` protocol.
3. **ExecutionAdapter** (optional, only when going live there) in `cosmu/adapters/exec/<venue>.py`: implement `ExecutionAdapter`. Keep it OFF the LLM/tool path.
4. **Universe gate** in `cosmu/spine/universe.py`: add to `VENUES_WITH_DATA` / `CLASSES_WITH_DATA` ONLY once data actually flows — otherwise it shows an honest "no data yet" (never faked).
5. **Test** with offline fixtures: fees correct (`tests/test_venue_fees.py`), adapter parses a canned response, `venue_for([...])` resolves it.

## Invariants
- Fees are REAL and per-venue — no fee-free "paper" venue. `venue.effective_fee(volume_30d_usd)` picks the richest tier met.
- Live availability is a **venue + country** fact (`live_legal_in`), not a global toggle.
- Never collapse the model decision and the venue execution — they stay separate records.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_venue_fees.py tests/cross_asset -q`
