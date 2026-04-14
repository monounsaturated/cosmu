import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const provider = searchParams.get("provider");
    const targetUrl = provider ? `${apiBaseUrl}/models?provider=${encodeURIComponent(provider)}` : `${apiBaseUrl}/models`;

    const res = await fetch(targetUrl, {
      headers: { "x-api-key": apiSecretKey }
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Request failed" },
      { status: 500 }
    );
  }
}

export async function POST(request: Request) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const body = await request.json();
    const res = await fetch(`${apiBaseUrl}/models`, {
      method: "POST",
      headers: {
        "x-api-key": apiSecretKey,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Request failed" },
      { status: 500 }
    );
  }
}
