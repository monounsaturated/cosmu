import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export async function GET(request: Request, { params }: { params: Promise<{ botId: string }> }) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const { botId } = await params;
    const url = new URL(request.url);
    const query = url.searchParams.toString();
    const target = `${apiBaseUrl}/bots/${botId}/runs${query ? `?${query}` : ""}`;
    const res = await fetch(target, {
      method: "GET",
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey }
    });

    const data = await res.json();
    if (!res.ok) return NextResponse.json(data, { status: res.status });
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Request failed" },
      { status: 500 }
    );
  }
}
