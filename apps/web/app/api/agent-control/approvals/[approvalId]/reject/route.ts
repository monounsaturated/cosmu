import { proxyApi } from "../../../../proxy";

export async function POST(_request: Request, context: { params: Promise<{ approvalId: string }> }) {
  const { approvalId } = await context.params;
  return proxyApi(`/agent-control/approvals/${approvalId}/reject`, { method: "POST" });
}
