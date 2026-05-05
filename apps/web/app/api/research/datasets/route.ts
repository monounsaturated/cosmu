import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/research/datasets");
}

export async function POST(request: Request) {
  return proxyApi("/research/datasets", {
    method: "POST",
    body: await request.text()
  });
}
