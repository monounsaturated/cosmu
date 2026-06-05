# intent: expose the venue-catalog seed and execution seam; inputs: settings; outputs: seeded venue/instrument rows; invariants: seed_catalog is idempotent (ON CONFLICT DO NOTHING), live off by default.

from __future__ import annotations

import json
from dataclasses import dataclass

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.spine.venue import VenueCatalog, default_catalog


@dataclass(frozen=True)
class EngineFacade:
    settings: Settings
    store: Store
    catalog: VenueCatalog

    @classmethod
    def create(cls, settings: Settings) -> "EngineFacade":
        store = Store(settings)
        catalog = default_catalog()
        facade = cls(settings=settings, store=store, catalog=catalog)
        facade.seed_catalog()
        return facade

    def seed_catalog(self) -> None:
        for venue in self.catalog.venues:
            self.store.rows(
                "INSERT INTO venues(id, name, kind, adapter, fee_schedule, constraints, enabled) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                (
                    venue.id,
                    venue.name,
                    venue.kind,
                    venue.adapter,
                    json.dumps({"maker_bps": str(venue.maker_fee_bps), "taker_bps": str(venue.taker_fee_bps)}),
                    json.dumps({"min_notional": str(venue.min_notional), "lot_size": str(venue.lot_size)}),
                    int(venue.enabled),
                ),
            )
        for instrument in self.catalog.instruments:
            self.store.rows(
                "INSERT INTO instruments(id, venue_id, symbol, asset_class, tick_size, lot_size, min_notional, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                (
                    instrument.id,
                    instrument.venue_id,
                    instrument.symbol,
                    instrument.asset_class,
                    str(instrument.tick_size),
                    str(instrument.lot_size),
                    str(instrument.min_notional),
                    int(instrument.active),
                ),
            )


