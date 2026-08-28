// Lint the prose in every tracked .md, .py and .ts file.
//
// Tracked, rather than a directory walk with an exclusion list: the list would
// have to name .venv, node_modules and seven scratch dotdirs, and it would go
// stale the first time someone adds an eighth. `git ls-files` already knows.
//
// The files go to vale in chunks, because Windows caps a process's whole
// command line at 32767 bytes and the full list is most of the way there. The
// output format is one finding per line so a chunk boundary cannot land in the
// middle of a report, and so each finding reads as path:line:column.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const CHUNK_SIZE = 200;
const EXTENSIONS = ["*.md", "*.py", "*.ts"];

const binary = path.join(
  "node_modules",
  ".bin",
  process.platform === "win32" ? "vale.cmd" : "vale",
);

if (!existsSync(binary)) {
  console.error("==> vale is not installed. Run `make npm`.");
  console.error("    The binary arrives through @vvago/vale's postinstall, so");
  console.error("    an install with lifecycle scripts disabled leaves none.");
  process.exit(1);
}

const tracked = spawnSync("git", ["ls-files", "-z", ...EXTENSIONS], {
  encoding: "utf8",
});
if (tracked.status !== 0) {
  console.error(tracked.stderr || "==> git ls-files failed.");
  process.exit(1);
}

const files = tracked.stdout.split("\0").filter(Boolean);
const findings = [];
let failed = false;

for (let start = 0; start < files.length; start += CHUNK_SIZE) {
  const chunk = files.slice(start, start + CHUNK_SIZE);
  const result = spawnSync(binary, ["--output=line", ...chunk], {
    encoding: "utf8",
  });
  //: vale exits 1 for a finding and 2 for a fault. Only the second is
  //: this script's problem; the first is the answer it was asked for.
  if (result.status !== 0 && result.status !== 1) {
    console.error(result.stderr || `==> vale exited ${result.status}.`);
    process.exit(2);
  }
  const reported = result.stdout.split("\n").filter(Boolean);
  findings.push(...reported);
  if (reported.length > 0) {
    failed = true;
  }
}

for (const finding of findings) {
  console.log(finding);
}

if (failed) {
  console.error(
    `==> ${findings.length} prose findings in ${files.length} files. See docs/vocabulary.md.`,
  );
  process.exit(1);
}

console.log(`==> vale: ${files.length} files, no findings.`);
