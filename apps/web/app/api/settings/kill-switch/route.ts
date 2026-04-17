import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

async function getApiKey() {
  const key = process.env.API_SECRET_KEY;
  if (!key) throw new Error("API_SECRET_KEY is required");
  return key;
}

export async function GET() {
  try {
    const apiKey = await getApiKey();
    const res = await fetch(`${apiBaseUrl}/settings/kill-switch`, {
      headers: { "x-api-key": apiKey }
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

export async function PUT(request: Request) {
  try {
    const apiKey = await getApiKey();
    const body = await request.json();
    const res = await fetch(`${apiBaseUrl}/settings/kill-switch`, {
      method: "PUT",
      headers: { "x-api-key": apiKey, "content-type": "application/json" },
      body: JSON.stringify(body)
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
