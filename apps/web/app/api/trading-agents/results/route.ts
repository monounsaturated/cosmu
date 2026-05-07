import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/trading-agents/results");
}
