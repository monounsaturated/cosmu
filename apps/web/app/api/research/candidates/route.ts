import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/research/candidates");
}

