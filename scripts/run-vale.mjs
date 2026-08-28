// Lint the prose in every tracked .md, .py and .ts file.
//
// Tracked, rather than a directory walk with an exclusion list: the list would
// have to name .venv, node_modules and seven scratch dotdirs, and it would go
// stale the first time someone adds an eighth. `git ls-files` already knows.
//
// The files go to vale in chunks, because Windows caps a process's whole
// command line at 32767 bytes and the full list is most of the way there.
//
// JSON rather than vale's own line format, for the two things this script does
// that vale cannot: read each finding's severity so only an error fails the
// build, and drop a warning that an error already covers.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const CHUNK_SIZE = 200;
const EXTENSIONS = ["*.md", "*.py", "*.ts"];

function missing() {
  console.error("==> vale is not installed. Run `make npm`.");
  console.error("    The binary arrives through @vvago/vale's postinstall, so");
  console.error("    an install with lifecycle scripts disabled leaves none.");
  process.exit(1);
}

// The package's own executable, not the node_modules/.bin shim. On Windows
// that shim is a .cmd, and since Node 18.20 spawning one without a shell
// throws EINVAL — so the shim would break `make check` on the documented
// Windows path. Resolving the package also survives a hoisting change.
function locateBinary() {
  const require = createRequire(import.meta.url);
  let manifest;
  try {
    manifest = require.resolve("@vvago/vale/package.json");
  } catch {
    missing();
  }
  return path.join(
    path.dirname(manifest),
    "bin",
    process.platform === "win32" ? "vale.exe" : "vale",
  );
}

const binary = locateBinary();

if (!existsSync(binary)) {
  missing();
}

const tracked = spawnSync("git", ["ls-files", "-z", ...EXTENSIONS], {
  encoding: "utf8",
});
if (tracked.status !== 0) {
  console.error(tracked.stderr || "==> git ls-files failed.");
  process.exit(1);
}

// A broad rule and a narrow one can both match the same words: the narrow rule
// names a settled sense of a term and errors, the broad rule says the term is
// imprecise and warns. Go's regexp has no lookahead, so the broad rule cannot
// exclude the narrow one and the overlap is resolved here instead. The error
// message says everything the warning would have.
function withoutCoveredWarnings(findings) {
  const errors = findings.filter((finding) => finding.severity === "error");
  return findings.filter((finding) => {
    if (finding.severity === "error") {
      return true;
    }
    return !errors.some(
      (error) =>
        error.file === finding.file &&
        error.line === finding.line &&
        error.start <= finding.end &&
        finding.start <= error.end,
    );
  });
}

const files = tracked.stdout.split("\0").filter(Boolean);
const findings = [];

for (let start = 0; start < files.length; start += CHUNK_SIZE) {
  const chunk = files.slice(start, start + CHUNK_SIZE);
  const result = spawnSync(binary, ["--output=JSON", ...chunk], {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  //: vale exits 1 for a finding and 2 for a fault. Only the second is
  //: this script's problem; the first is the answer it was asked for.
  if (result.status !== 0 && result.status !== 1) {
    console.error(result.stderr || `==> vale exited ${result.status}.`);
    process.exit(2);
  }
  const reported = JSON.parse(result.stdout || "{}");
  for (const [file, alerts] of Object.entries(reported)) {
    for (const alert of alerts) {
      findings.push({
        file,
        line: alert.Line,
        start: alert.Span[0],
        end: alert.Span[1],
        severity: alert.Severity,
        message: alert.Message,
        check: alert.Check,
      });
    }
  }
}

const reportable = withoutCoveredWarnings(findings);
reportable.sort(
  (left, right) =>
    left.file.localeCompare(right.file) ||
    left.line - right.line ||
    left.start - right.start,
);

for (const finding of reportable) {
  const where = `${finding.file}:${finding.line}:${finding.start}`;
  console.log(`${where}: ${finding.severity}: ${finding.message}`);
}

const errorCount = reportable.filter(
  (finding) => finding.severity === "error",
).length;
const warningCount = reportable.length - errorCount;

if (errorCount > 0) {
  console.error(
    `==> ${errorCount} errors and ${warningCount} warnings in ${files.length} files. See docs/vocabulary.md.`,
  );
  process.exit(1);
}

if (warningCount > 0) {
  //: A warning does not fail the build. The word may be the right one;
  //: the rule cannot tell, and only a reader can.
  console.log(
    `==> vale: ${files.length} files, ${warningCount} warnings, no errors.`,
  );
  process.exit(0);
}

console.log(`==> vale: ${files.length} files, no findings.`);
