import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export async function GET() {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY not configured" }, { status: 500 });
    }

    const res = await fetch(`${apiBaseUrl}/internal/diagnostics`, {
      headers: { "x-api-key": apiSecretKey }
    });

    const data = await res.json();
    return NextResponse.json({ webEnv: { apiBaseUrl, hasKey: true }, backend: data });
  } catch (error) {
    return NextResponse.json({
      webEnv: { apiBaseUrl, hasKey: Boolean(process.env.API_SECRET_KEY) },
      backendError: error instanceof Error ? error.message : String(error)
    }, { status: 500 });
  }
}
