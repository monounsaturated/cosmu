import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/research/data-sources");
}

export async function POST(request: Request) {
  return proxyApi("/research/data-sources", {
    method: "POST",
    body: JSON.stringify(await request.json())
  });
}

