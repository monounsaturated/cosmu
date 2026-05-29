import { proxyApi } from "../../../../proxy";

export async function POST(_request: Request, { params }: { params: Promise<{ candidateId: string }> }) {
  const { candidateId } = await params;
  return proxyApi(`/research/candidates/${candidateId}/venue-bot`, { method: "POST" });
}
