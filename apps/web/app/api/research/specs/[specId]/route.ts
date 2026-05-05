import { proxyApi } from "../../../proxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ specId: string }> }
) {
  const { specId } = await params;
  return proxyApi(`/research/specs/${specId}`);
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ specId: string }> }
) {
  const { specId } = await params;
  return proxyApi(`/research/specs/${specId}`, {
    method: "PATCH",
    body: await request.text()
  });
}
