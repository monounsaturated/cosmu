import { NextRequest } from "next/server";
import { proxyApi } from "../../proxy";

export async function POST(request: NextRequest) {
  const body = await request.text();
  return proxyApi("/trading-agents/analyze", { method: "POST", body });
}
