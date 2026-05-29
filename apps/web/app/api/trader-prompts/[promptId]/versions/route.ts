import { proxyApi } from "../../../proxy";

export async function POST(request: Request, { params }: { params: Promise<{ promptId: string }> }) {
  const { promptId } = await params;
  const body = await request.json();
  return proxyApi(`/trader-prompts/${promptId}/versions`, {
    method: "POST",
    body: JSON.stringify(body)
  });
}
