import { proxyApi } from "../../proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyApi(`/signals/observations${url.search}`);
}

export async function POST(request: Request) {
  return proxyApi("/signals/observations", {
    method: "POST",
    body: await request.text()
  });
}
