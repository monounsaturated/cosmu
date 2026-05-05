import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/research/sessions");
}

export async function POST(request: Request) {
  return proxyApi("/research/sessions", {
    method: "POST",
    body: await request.text()
  });
}
