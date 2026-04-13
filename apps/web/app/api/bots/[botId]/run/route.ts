import { NextRequest, NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
const apiSecretKey = process.env.API_SECRET_KEY;

if (!apiSecretKey) {
  throw new Error("API_SECRET_KEY is required");
}

export async function POST(
  request: NextRequest,
  { params }: { params: { botId: string } }
) {
  try {
    const res = await fetch(`${apiBaseUrl}/bots/${params.botId}/run`, {
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
      { error: error instanceof Error ? error.message : "Request failed" },
      { status: 500 }
    );
  }
}
