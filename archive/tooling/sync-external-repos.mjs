#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const lockPath = path.join(root, "external-repos.lock.json");
const targetRoot = path.join(root, ".external");

const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
fs.mkdirSync(targetRoot, { recursive: true });

for (const repo of lock.repos) {
  const dir = path.join(targetRoot, repo.name.replace(/[^a-z0-9_-]/gi, "-").toLowerCase());
  if (!fs.existsSync(dir)) {
    console.log(`Cloning ${repo.name}...`);
    execFileSync("git", ["clone", repo.url, dir], { stdio: "inherit" });
  } else {
    console.log(`Fetching ${repo.name}...`);
    execFileSync("git", ["fetch", "--all", "--tags"], { cwd: dir, stdio: "inherit" });
  }
  execFileSync("git", ["checkout", repo.commit], { cwd: dir, stdio: "inherit" });
  const head = execFileSync("git", ["rev-parse", "HEAD"], { cwd: dir, encoding: "utf8" }).trim();
  console.log(`${repo.name}: ${head}`);
}

