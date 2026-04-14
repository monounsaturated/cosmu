import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export async function GET(_request: Request, { params }: { params: { venue: string } }) {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
    }

    const res = await fetch(`${apiBaseUrl}/venues/${params.venue}/symbols`, {
      headers: {
        "x-api-key": apiSecretKey
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
