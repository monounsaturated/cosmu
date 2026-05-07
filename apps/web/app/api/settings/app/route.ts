import { proxyApi } from "../../proxy";

export async function GET() {
  return proxyApi("/settings/app");
}

export async function PUT(request: Request) {
  return proxyApi("/settings/app", {
    method: "PUT",
    body: await request.text()
  });
}
