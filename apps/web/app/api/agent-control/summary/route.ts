import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/agent-control/summary");
}

