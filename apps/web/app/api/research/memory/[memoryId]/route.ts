import { proxyApi } from "../../../proxy";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ memoryId: string }> }
) {
  const { memoryId } = await params;
  return proxyApi(`/research/memory/${memoryId}`, {
    method: "PATCH",
    body: await request.text()
  });
}
