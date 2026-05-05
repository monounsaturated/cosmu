import { proxyApi } from "../proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyApi(`/signals${url.search}`);
}

export async function POST(request: Request) {
  return proxyApi("/signals", {
    method: "POST",
    body: await request.text()
  });
}
