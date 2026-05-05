import { proxyApi } from "../../proxy";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const sessionId = searchParams.get("sessionId");
  const suffix = sessionId ? `?sessionId=${encodeURIComponent(sessionId)}` : "";
  return proxyApi(`/research/memory${suffix}`);
}
