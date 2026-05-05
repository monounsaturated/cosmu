import { proxyApi } from "../../proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const status = url.searchParams.get("status");
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return proxyApi(`/agent-control/approvals${query}`);
}
