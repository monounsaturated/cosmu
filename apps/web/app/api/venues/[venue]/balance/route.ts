import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ venue: string }> }
) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const { venue } = await params;
    const upstream = new URL(`${apiBaseUrl}/venues/${venue}/balance`);
    const force = new URL(request.url).searchParams.get("force");
    if (force) upstream.searchParams.set("force", force);
    const res = await fetch(upstream, {
      headers: { "x-api-key": apiSecretKey },
      cache: "no-store"
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    );
  }
}
