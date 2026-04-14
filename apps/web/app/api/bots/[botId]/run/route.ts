import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
export async function POST(_request: Request, { params }: { params: Promise<{ botId: string }> }) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const { botId } = await params;
    const res = await fetch(`${apiBaseUrl}/bots/${botId}/run`, {
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
