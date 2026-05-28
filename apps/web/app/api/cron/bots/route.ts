import { NextResponse } from "next/server";
import { proxyApi } from "../../proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const isAuthorized = (request: Request) => {
  const secret = process.env.CRON_SECRET;
  return Boolean(secret) && request.headers.get("authorization") === `Bearer ${secret}`;
};

export async function GET(request: Request) {
  if (!isAuthorized(request)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  return proxyApi("/internal/scheduler/tick", { method: "POST" });
}

export const POST = GET;
