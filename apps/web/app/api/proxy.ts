import { NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export const proxyApi = async (path: string, init: RequestInit = {}) => {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) {
    return NextResponse.json({ error: "API_SECRET_KEY is required" }, { status: 500 });
  }

  const res = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      "x-api-key": apiSecretKey,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {})
    },
    cache: "no-store"
  });
  const text = await res.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text || `API request failed with ${res.status}` };
  }
  return NextResponse.json(data, { status: res.status });
};

