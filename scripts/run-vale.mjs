// Lint the prose in .md, .py and .ts files.
//
// Only the files this checkout changed, by default: a word banned today then
// blocks the work that touches it, rather than every file that already holds
// it. `--all` lints the whole codebase, which is how a new rule's backlog is
// read, and `--since <rev>` states another base.
//
// The list comes from git, rather than a directory walk with an exclusion
// list: the list would have to name .venv, node_modules and seven scratch
// dotdirs, and it would go stale the first time someone adds an eighth.
//
// The files go to vale in chunks, because Windows caps a process's whole
// command line at 32767 bytes and the full list is most of the way there.
//
// JSON rather than vale's own line format, for the two things this script does
// that vale cannot: read each finding's severity so only an error fails the
// build, and drop a broad rule's finding where a narrow rule already covers it.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const CHUNK_SIZE = 200;
const EXTENSIONS = ["*.md", "*.py", "*.ts"];
const SUFFIXES = [".md", ".py", ".ts"];
//: Tried in order for the default base. A fetched remote branch is the
//: honest answer; the local one may lag it, which widens the run rather
//: than narrowing it, so it stands second and never first.
const DEFAULT_BASES = ["origin/main", "main"];
const USAGE = "usage: run-vale.mjs [--all] [--since <rev>]";

function refuse(reason, ...hints) {
  console.error(`==> ${reason}`);
  for (const hint of hints) {
    console.error(`    ${hint}`);
  }
  process.exit(2);
}

function git(...args) {
  return spawnSync("git", args, { encoding: "utf8" });
}

function parseArguments(argv) {
  let all = false;
  let since = null;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--all") {
      all = true;
    } else if (argument === "--since") {
      since = argv[index + 1];
      index += 1;
      if (since === undefined) {
        refuse("--since needs a revision.", USAGE);
      }
    } else if (argument.startsWith("--since=")) {
      since = argument.slice("--since=".length);
      if (!since) {
        refuse("--since needs a revision.", USAGE);
      }
    } else {
      refuse(`unknown argument ${argument}.`, USAGE);
    }
  }
  if (all && since !== null) {
    refuse("--all lints every file, so --since says nothing beside it.", USAGE);
  }
  return { all, since };
}

function resolveCommit(revision) {
  const resolved = git(
    "rev-parse",
    "--verify",
    "--quiet",
    `${revision}^{commit}`,
  );
  return resolved.status === 0 ? resolved.stdout.trim() : null;
}

// The merge base, never the revision itself: a diff against a branch that has
// moved on reports its commits too, and prose someone else wrote is not this
// checkout's to answer for. For an ancestor the two are the same revision.
function resolveBase(stated) {
  const candidates = stated === null ? DEFAULT_BASES : [stated];
  for (const candidate of candidates) {
    if (resolveCommit(candidate) === null) {
      continue;
    }
    const base = git("merge-base", "HEAD", candidate);
    if (base.status === 0) {
      return { commit: base.stdout.trim(), label: candidate };
    }
  }
  if (stated !== null) {
    refuse(`git cannot resolve ${stated} to a commit.`, USAGE);
  }
  refuse(
    `no base to compare against: ${DEFAULT_BASES.join(" and ")} both resolve to nothing.`,
    "A shallow clone has no main to compare against. Fetch it, state one",
    "with --since <rev>, or lint the whole codebase with --all.",
  );
}

function lintable(names) {
  return names.filter(
    (name) =>
      SUFFIXES.some((suffix) => name.endsWith(suffix)) && existsSync(name),
  );
}

function readList(result, what) {
  if (result.status !== 0) {
    refuse(result.stderr.trim() || `${what} failed.`);
  }
  return result.stdout.split("\0").filter(Boolean);
}

function trackedFiles() {
  return readList(git("ls-files", "-z", ...EXTENSIONS), "git ls-files");
}

// A new file is untracked and has no diff, so it is asked for separately.
// Both lists name paths from the repository root, which is where make runs.
function changedFiles(base) {
  const changed = readList(
    git("diff", "--name-only", "--diff-filter=d", "-z", base.commit, "--"),
    "git diff",
  );
  const untracked = readList(
    git("ls-files", "--others", "--exclude-standard", "-z"),
    "git ls-files",
  );
  return [...new Set([...changed, ...untracked])];
}

function selectFiles({ all, since }) {
  if (all) {
    return { files: lintable(trackedFiles()).sort(), scope: "files" };
  }
  const base = resolveBase(since);
  return {
    files: lintable(changedFiles(base)).sort(),
    scope: `changed files since ${base.label}`,
  };
}

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

const { files, scope } = selectFiles(parseArguments(process.argv.slice(2)));

if (files.length === 0) {
  console.log(`==> vale: no ${scope}.`);
  process.exit(0);
}

// A broad rule and a narrow one can both match the same words: the narrow rule
// names a settled sense of a term, the broad one says the term is imprecise.
// Go's regexp has no lookahead, so the broad rule cannot exclude the narrow one
// and the overlap is resolved here instead. The narrow message says everything
// the broad one would have and names the one replacement, so the broad finding
// is the one dropped — whatever its level, because `fold` errors at both.
const BROAD_CHECKS = new Set([
  "Timetracker.DiscouragedTerms",
  "Timetracker.RemovalTerms",
  "Timetracker.HealTerms",
]);

function withoutCoveredFindings(findings) {
  const narrow = findings.filter((finding) => !BROAD_CHECKS.has(finding.check));
  return findings.filter((finding) => {
    if (!BROAD_CHECKS.has(finding.check)) {
      return true;
    }
    return !narrow.some(
      (other) =>
        other.file === finding.file &&
        other.line === finding.line &&
        other.start <= finding.end &&
        finding.start <= other.end,
    );
  });
}

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

const reportable = withoutCoveredFindings(findings);
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
    `==> ${errorCount} errors and ${warningCount} warnings in ${files.length} ${scope}. See docs/vocabulary.md.`,
  );
  process.exit(1);
}

if (warningCount > 0) {
  //: A warning does not fail the build. The word may be the right one;
  //: the rule cannot tell, and only a reader can.
  console.log(
    `==> vale: ${files.length} ${scope}, ${warningCount} warnings, no errors.`,
  );
  process.exit(0);
}

console.log(`==> vale: ${files.length} ${scope}, no findings.`);
