import { proxyApi } from "../../../../proxy";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;
  return proxyApi(`/research/sessions/${sessionId}/run-engine`, {
    method: "POST"
  });
}
