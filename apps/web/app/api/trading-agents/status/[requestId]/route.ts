import { proxyApi } from "../../../proxy";

export async function GET(_request: Request, { params }: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await params;
  return proxyApi(`/trading-agents/status/${requestId}`);
}
