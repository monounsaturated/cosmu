import { proxyApi } from "../../../proxy";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ signalId: string }> }
) {
  const { signalId } = await params;
  return proxyApi(`/signals/${signalId}/status`, {
    method: "PATCH",
    body: await request.text()
  });
}
