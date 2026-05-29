// module: Venue primitives — the single source of truth for testnet vs live.
import { z } from "zod";

export const ALL_SYMBOLS_TOKEN = "__ALL__";
export const venueSchema = z.enum(["binance", "binance-testnet", "ibkr-paper", "ibkr"]);
export type Venue = z.infer<typeof venueSchema>;
/** Venue is the single source of truth for testnet vs live. `binance` = live, `binance-testnet` = testnet. */
export const isTestnetVenue = (venue: Venue): boolean => venue === "binance-testnet";
export const assetClassSchema = z.enum(["spot", "equity"]);
export type AssetClass = z.infer<typeof assetClassSchema>;
