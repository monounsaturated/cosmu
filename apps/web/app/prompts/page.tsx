import Link from "next/link";
import { PromptVersionViewer } from "./prompt-version-viewer";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
export const dynamic = "force-dynamic";

interface PromptVersion {
  id: string;
  version: number;
  createdAt: string;
}

interface Prompt {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  latestVersionCreatedAt: string | null;
  versions: PromptVersion[];
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
          <p className="muted">View all prompts and their version history.</p>
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
                  <h3 style={{ margin: 0 }}>{prompt.name}</h3>
                  <p className="muted" style={{ marginTop: "4px" }}>
                    {prompt.versions.length} version{prompt.versions.length !== 1 ? "s" : ""}
                    {" · "}slug: {prompt.slug}
                  </p>
                </div>
                <span className="badge badge-neutral">
                  Created {new Date(prompt.createdAt).toLocaleDateString()}
                </span>
              </div>

              {prompt.versions.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {prompt.versions.map((version) => (
                    <PromptVersionViewer
                      key={version.id}
                      promptId={prompt.id}
                      versionId={version.id}
                      versionNumber={version.version}
                      createdAt={version.createdAt}
                    />
                  ))}
                </div>
              ) : (
                <p className="muted">No versions yet.</p>
              )}
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
