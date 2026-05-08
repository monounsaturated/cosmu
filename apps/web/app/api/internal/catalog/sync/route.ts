import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export async function POST(request: Request) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const force = searchParams.get("force") === "true";
    const provider = searchParams.get("provider");
    const upstream = new URL(`${apiBaseUrl}/internal/catalog/sync`);
    if (force) upstream.searchParams.set("force", "true");
    if (provider) upstream.searchParams.set("provider", provider);

    const res = await fetch(upstream.toString(), {
      method: "POST",
      headers: {
        "x-api-key": apiSecretKey,
        "Content-Type": "application/json"
      }
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Sync request failed" },
      { status: 500 }
    );
  }
}
