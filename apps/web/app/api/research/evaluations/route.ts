import { proxyApi } from "../../proxy";

export async function POST(request: Request) {
  return proxyApi("/research/evaluations", {
    method: "POST",
    body: await request.text()
  });
}
