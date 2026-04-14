import Link from "next/link";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
export const dynamic = "force-dynamic";

interface Prompt {
  id: string;
  name: string;
  slug: string;
  promptNumber: number;
  createdAt: string;
  latestVersionId: string | null;
  latestBody: string | null;
  latestVersionCreatedAt: string | null;
}

async function fetchPrompts(): Promise<Prompt[]> {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) throw new Error("API_SECRET_KEY is required");

    const res = await fetch(`${apiBaseUrl}/prompts`, {
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey }
    });

    if (!res.ok) throw new Error(`Failed: ${res.status}`);
    return res.json();
  } catch (error) {
    console.error("Failed to fetch prompts", error);
    return [];
  }
}

export default async function PromptsPage() {
  const prompts = await fetchPrompts();

  return (
    <main className="page">
      <section className="hero">
        <div>
          <Link href="/" className="muted" style={{ display: "inline-block", marginBottom: "16px", textDecoration: "none" }}>
            ← Back to Dashboard
          </Link>
          <h1>Prompts</h1>
          <p className="muted">Immutable prompt snapshots used by bots.</p>
        </div>
      </section>

      {prompts.length === 0 ? (
        <div className="panel">
          <p className="muted">No prompts yet.</p>
        </div>
      ) : (
        <div className="stack" style={{ marginTop: 0 }}>
          {prompts.map((prompt) => (
            <article key={prompt.id} className="panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
                <div>
                  <h3 style={{ margin: 0 }}>Prompt #{prompt.promptNumber}</h3>
                  <p className="muted" style={{ marginTop: "4px" }}>
                    {prompt.name} {" · "}slug: {prompt.slug}
                  </p>
                </div>
                <span className="badge badge-neutral">
                  Saved {new Date(prompt.createdAt).toLocaleDateString()}
                </span>
              </div>

              {prompt.latestBody ? (
                <div>
                  <p className="label" style={{ marginBottom: "8px" }}>Prompt Body</p>
                  <pre className="run-detail-pre" style={{ margin: 0 }}>
                    {prompt.latestBody}
                  </pre>
                </div>
              ) : (
                <p className="muted">Prompt body unavailable.</p>
              )}
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
