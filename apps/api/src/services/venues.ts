// module: Venue config/resolution — Binance vs Binance Testnet credentials.
import { env } from "../env.js";
import { getAccountBalance, isBinanceVenue, type BinanceNet } from "../adapters/binance.js";
import type { Venue } from "@cosmu/shared";

export type VenueId = Venue;

type VenueDefinition = {
  id: VenueId;
  label: string;
  mode: BinanceNet | "paper" | "live";
  assetClass: "spot" | "equity";
  execution: "active" | "planned";
};

export type VenueConnectionStatus = {
  id: VenueId;
  label: string;
  mode: VenueDefinition["mode"];
  configured: boolean;
  connected: boolean;
  checkedAt: string;
  balance: Awaited<ReturnType<typeof getAccountBalance>> | null;
  error: string | null;
};

const VENUE_STATUS_TTL_MS = 30 * 1000;

export const VENUES: VenueDefinition[] = [
  { id: "binance", label: "Binance", mode: "live", assetClass: "spot", execution: "active" },
  { id: "binance-testnet", label: "Binance Testnet", mode: "testnet", assetClass: "spot", execution: "active" },
  { id: "ibkr-paper", label: "IBKR Paper", mode: "paper", assetClass: "equity", execution: "planned" },
  { id: "ibkr", label: "IBKR", mode: "live", assetClass: "equity", execution: "planned" }
];

const statusCache = new Map<VenueId, { expiresAt: number; status: VenueConnectionStatus }>();

export const parseVenueId = (value: string): VenueId | null =>
  value === "binance" || value === "binance-testnet" || value === "ibkr-paper" || value === "ibkr"
    ? value
    : null;

export const getVenueDefinition = (venue: VenueId) => VENUES.find((entry) => entry.id === venue)!;

const venueConfigured = (mode: VenueDefinition["mode"]) =>
  mode === "testnet"
    ? Boolean(env.BINANCE_TESTNET_API_KEY && env.BINANCE_TESTNET_API_SECRET)
    : mode === "live"
    ? Boolean(env.BINANCE_API_KEY && env.BINANCE_API_SECRET)
    : false;

export const describeVenueError = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  if (/aborted|timed out|timeout/i.test(message)) {
    return message.includes("Binance")
      ? message
      : `Binance account request timed out or was aborted: ${message}`;
  }
  const binanceCodeMatch = message.match(/"code":(-?\d+)/);
  const binanceMessageMatch = message.match(/"msg":"([^"]+)"/);
  if (binanceCodeMatch || binanceMessageMatch) {
    return `Binance ${binanceCodeMatch?.[1] ?? "error"}: ${binanceMessageMatch?.[1] ?? message}`;
  }
  return message
    .replace(/signature=[^&\s]+/g, "signature=[redacted]")
    .replace(/timestamp=\d+/g, "timestamp=[redacted]");
};

export const checkVenueConnection = async (
  venue: VenueId,
  options: { force?: boolean } = {}
): Promise<VenueConnectionStatus> => {
  const cached = statusCache.get(venue);
  if (!options.force && cached && cached.expiresAt > Date.now()) {
    return cached.status;
  }

  const definition = getVenueDefinition(venue);
  const checkedAt = new Date().toISOString();
  const configured = venueConfigured(definition.mode);

  if (!isBinanceVenue(definition.id)) {
    const status: VenueConnectionStatus = {
      id: definition.id,
      label: definition.label,
      mode: definition.mode,
      configured: false,
      connected: false,
      checkedAt,
      balance: null,
      error: `${definition.label} execution adapter is planned but not enabled yet`
    };
    statusCache.set(venue, { expiresAt: Date.now() + VENUE_STATUS_TTL_MS, status });
    return status;
  }

  if (!configured) {
    const status: VenueConnectionStatus = {
      id: definition.id,
      label: definition.label,
      mode: definition.mode,
      configured,
      connected: false,
      checkedAt,
      balance: null,
      error:
        definition.mode === "testnet"
          ? "BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET are required on the backend"
          : "BINANCE_API_KEY and BINANCE_API_SECRET are required on the backend"
    };
    statusCache.set(venue, { expiresAt: Date.now() + VENUE_STATUS_TTL_MS, status });
    return status;
  }

  try {
    const binanceMode: BinanceNet = definition.id === "binance-testnet" ? "testnet" : "live";
    const balance = await getAccountBalance(binanceMode);
    const status: VenueConnectionStatus = {
      id: definition.id,
      label: definition.label,
      mode: definition.mode,
      configured,
      connected: true,
      checkedAt,
      balance,
      error: null
    };
    statusCache.set(venue, { expiresAt: Date.now() + VENUE_STATUS_TTL_MS, status });
    return status;
  } catch (error) {
    const status: VenueConnectionStatus = {
      id: definition.id,
      label: definition.label,
      mode: definition.mode,
      configured,
      connected: false,
      checkedAt,
      balance: null,
      error: describeVenueError(error)
    };
    statusCache.set(venue, { expiresAt: Date.now() + VENUE_STATUS_TTL_MS, status });
    return status;
  }
};

export const getVenueConnectionStatuses = async (options: { force?: boolean } = {}) =>
  Promise.all(VENUES.map((venue) => checkVenueConnection(venue.id, options)));
