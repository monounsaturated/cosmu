import { proxyApi } from "../../../proxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  return proxyApi(`/research/evaluations/${jobId}`);
}
