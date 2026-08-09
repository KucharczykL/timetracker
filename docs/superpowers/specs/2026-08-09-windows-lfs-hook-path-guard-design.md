# Windows LFS Hook-Path Guard Design

## Problem

On Windows, invoking Git LFS while `core.hooksPath=/dev/null` creates an
untracked `dev/null/` directory in the repository root. Git LFS writes its
`pre-push`, `post-checkout`, `post-commit`, and `post-merge` hook scripts there.
The directory is generated clutter, not a project source directory.

## Cause

`/dev/null` is a POSIX null-device path sometimes supplied as an ephemeral Git
configuration to disable hooks. Git LFS updates its hooks automatically. On
Windows, its hook-path handling resolves that value beneath the worktree as
`dev/null/`.

## Design

Add two layers of protection:

1. Extend the repository-root `AGENTS.md` with a Windows-specific prohibition
   on `git -c core.hooksPath=/dev/null`. If an explicitly authorized operation
   must bypass verification hooks, use Git's native `--no-verify` flag instead.
2. Add a pytest repository-hygiene test that fails when the generated
   root-level `dev/null/` directory exists. This turns a future accidental
   recreation into an immediate test failure rather than an unnoticed untracked
   directory.

Do not add `/dev/` to `.gitignore`: hiding the artifact would preserve the bad
agent behavior and could mask a future legitimate source directory.

## Cleanup

After the guard test is written and demonstrated failing against the existing
artifact, delete the known generated `dev/null/` directory. The test must then
pass.

## Verification

- Run the new repository-hygiene test before cleanup and observe its failure.
- Remove only `C:\\Users\\lukas\\git\\timetracker\\dev`, after confirming its
  contents are the four duplicate Git LFS hook scripts.
- Run the test again and the normal relevant check target with parallel workers.
