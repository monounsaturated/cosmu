// Liveness endpoint for Railway's healthcheck (healthcheckPath = "/health").
// Static + always 200 so the web replica is marked healthy as soon as it serves.
export const dynamic = "force-static";

export function GET() {
  return Response.json({ ok: true, service: "cosmu-web" });
}
