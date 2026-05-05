import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/research/experiments");
}

export async function POST(request: Request) {
  return proxyApi("/research/experiments", {
    method: "POST",
    body: JSON.stringify(await request.json())
  });
}

