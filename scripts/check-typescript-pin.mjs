// Verify that this project's own TypeScript is installed, and that its major
// matches the pin in package.json.
//
// Getting the right node is not enough: `pnpm exec <tool>` falls back to a
// global binary when node_modules/ is absent, so a worktree that never had
// `pnpm install` run in it silently type-checks against whatever tsc happens to
// be on the system. An older tsc does not know the ESNext.Temporal lib this
// project's tsconfig asks for, so it rejects the `lib` array outright and then
// reports every Temporal reference in ts/ as an undefined name — reading like
// the code's fault rather than the install's.
//
// Both files are read by explicit path rather than through `require`, whose
// resolution walks up to a PARENT directory's node_modules: a git worktree
// nested under the main checkout would find that copy and pass while `pnpm
// exec` — which does not walk up — still runs the global tsc. Reading
// ./node_modules directly measures what `pnpm exec` sees.
//
// This script also owns the failure message, rather than the Makefile echoing
// one around a bare exit status. Reporting a version resolved some other way
// (`pnpm exec tsc --version`) can contradict the check that actually failed:
// a leftover .bin/tsc symlink still resolves after the package directory is
// gone, producing "resolved 7.0.2, which is not the major package.json pins"
// when 7 is exactly the pin. Print what was measured, or nothing.

import { readFileSync } from "node:fs";
import { join } from "node:path";

const projectRoot = join(import.meta.dirname, "..");
const installedManifest = join(projectRoot, "node_modules", "typescript", "package.json");

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function pinnedMajor() {
  const manifest = readJson(join(projectRoot, "package.json"));
  const specifier =
    (manifest.devDependencies || {}).typescript ||
    (manifest.dependencies || {}).typescript;
  if (specifier === undefined) {
    return null;
  }
  return specifier.replace(/[~^>=< v]/g, "").split(".")[0];
}

function installedVersion() {
  try {
    return readJson(installedManifest).version;
  } catch (error) {
    return null;
  }
}

function fail(lines) {
  console.log(
    [
      "==> This project's JS dependencies are missing or stale.",
      ...lines,
      "    Without a matching tsc the ESNext.Temporal lib in tsconfig.json is",
      "    rejected and every Temporal reference in ts/ is reported as an",
      "    undefined name, as if the code were broken.",
      "    Run  make npm  to install this project's pinned dependencies.",
    ].join("\n"),
  );
  process.exit(1);
}

let want;
try {
  want = pinnedMajor();
} catch (error) {
  fail([`    Could not read package.json: ${error.message}`]);
}
if (want === null) {
  fail(["    package.json declares no typescript dependency to pin against."]);
}

const have = installedVersion();
if (have === null) {
  fail([`    ./node_modules/typescript is not installed; package.json pins major ${want}.`]);
}
if (have.split(".")[0] !== want) {
  fail([`    ./node_modules/typescript is ${have}; package.json pins major ${want}.`]);
}
