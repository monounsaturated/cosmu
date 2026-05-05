import { proxyApi } from "../../../../proxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ datasetId: string }> }
) {
  const { datasetId } = await params;
  return proxyApi(`/research/datasets/${datasetId}/versions`);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ datasetId: string }> }
) {
  const { datasetId } = await params;
  return proxyApi(`/research/datasets/${datasetId}/versions`, {
    method: "POST",
    body: await request.text()
  });
}
