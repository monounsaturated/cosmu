import { proxyApi } from "../../../../proxy";

export async function POST(_request: Request, context: { params: Promise<{ candidateId: string }> }) {
  const { candidateId } = await context.params;
  return proxyApi(`/research/candidates/${candidateId}/promote-to-pro`, { method: "POST" });
}
