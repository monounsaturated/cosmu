import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type GitHubRelease = {
  tag_name?: string;
  name?: string;
  published_at?: string;
  html_url?: string;
};

const findLocalPyproject = async () => {
  const candidates = [
    path.resolve(process.cwd(), "TradingAgents-main", "pyproject.toml"),
    path.resolve(process.cwd(), "..", "..", "TradingAgents-main", "pyproject.toml"),
    path.resolve(process.cwd(), "..", "TradingAgents-main", "pyproject.toml")
  ];

  for (const candidate of candidates) {
    try {
      const text = await readFile(candidate, "utf8");
      return { path: candidate, text };
    } catch {
      // Try the next common monorepo cwd. The route must keep working in dev and deployment.
    }
  }

  return null;
};

const parseProjectVersion = (pyproject: string) => {
  const match = pyproject.match(/^\s*version\s*=\s*"([^"]+)"/m);
  return match?.[1] ?? null;
};

const normalizeTag = (version: string | null) => {
  if (!version) return null;
  return version.startsWith("v") ? version : `v${version}`;
};

export async function GET() {
  const local = await findLocalPyproject();
  const localVersion = local ? parseProjectVersion(local.text) : null;
  const currentTag = normalizeTag(localVersion);

  let latest: GitHubRelease | null = null;
  let releaseError: string | null = null;

  try {
    const response = await fetch("https://api.github.com/repos/TauricResearch/TradingAgents/releases/latest", {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "cosmu-trading-agents-version-check"
      },
      next: { revalidate: 3600 }
    });

    if (!response.ok) {
      releaseError = `GitHub release check failed (${response.status})`;
    } else {
      latest = await response.json() as GitHubRelease;
    }
  } catch (error) {
    releaseError = error instanceof Error ? error.message : "GitHub release check failed";
  }

  const latestTag = latest?.tag_name ?? null;

  return NextResponse.json({
    local: {
      version: localVersion,
      tag: currentTag,
      sourcePath: local?.path ?? null,
      present: Boolean(local)
    },
    latest: latest ? {
      tag: latestTag,
      name: latest.name ?? latestTag,
      publishedAt: latest.published_at ?? null,
      url: latest.html_url ?? null
    } : null,
    updateAvailable: Boolean(currentTag && latestTag && currentTag !== latestTag),
    releaseError
  });
}
