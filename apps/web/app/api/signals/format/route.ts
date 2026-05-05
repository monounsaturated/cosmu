import { proxyApi } from "../../proxy";

export async function POST(request: Request) {
  return proxyApi("/signals/format", {
    method: "POST",
    body: await request.text()
  });
}
