import { proxyApi } from "../../../proxy";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ sourceId: string }> }
) {
  const { sourceId } = await params;
  return proxyApi(`/research/data-sources/${sourceId}`, {
    method: "PATCH",
    body: await request.text()
  });
}
