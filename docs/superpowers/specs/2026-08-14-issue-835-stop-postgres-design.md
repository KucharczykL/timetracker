# Issue #835: Worktree PostgreSQL Shutdown Design

Status: approved design.

Issue: [#835 — Add Make target to stop worktree-managed PostgreSQL](https://github.com/KucharczykL/timetracker/issues/835)

## Problem

The Make workflow provisions and starts a PostgreSQL cluster rooted at
`.cache/postgres/data`, but it has no supported shutdown command. This is
especially disruptive on Windows, where a running server keeps worktree files
open and can prevent `git worktree remove` from cleaning up completed work.

The generated `.cache/postgres.mk` file is currently an unconditional Make
include with a forced remake rule. A shutdown target that follows that normal
parse path can start, initialize, or download PostgreSQL before its shutdown
recipe runs. The cleanup operation must avoid that lifecycle inversion.

## Goals

- Add `make stop-postgres` as the supported cleanup command for the managed
  cluster in the current worktree.
- Stop that cluster through its PostgreSQL `pg_ctl` tool, using fast shutdown
  and waiting for completion.
- Make missing and already-stopped clusters successful no-ops.
- Preserve the real failure status when cluster state cannot be determined or
  shutdown fails.
- Guarantee that the stop-only Make invocation cannot download, initialize,
  start, or provision PostgreSQL.
- Support Windows and Unix-like development environments without broad
  process-name termination.

## Non-goals

- Stopping an operator-managed server supplied through `DATABASE_URL`.
- Stopping PostgreSQL clusters belonging to other worktrees.
- Deleting the local cluster, port metadata, generated include, or downloaded
  PostgreSQL binaries.
- Adding a general service manager or lifecycle framework.
- Supporting a combined invocation such as `make stop-postgres test`.

## Approaches considered

The selected approach extends `scripts/ensure_postgres.py` with a non-
provisioning stop mode. Provisioning and shutdown then share the managed
cluster paths and PostgreSQL tool model without duplicating them in another
script.

A separate shutdown script would keep its imports smaller, but it would
duplicate cluster and fallback-tool discovery. Defining the target in the
generated include was rejected because generating that include is the action
that must be bypassed during cleanup.

## Make interface

`stop-postgres` is a phony target whose recipe invokes the existing helper in
stop mode. When it is the sole requested goal, Make does not include or define
the remake rule for `.cache/postgres.mk`. Therefore Make cannot execute the
normal `--makefile` provisioning path while preparing the stop invocation.

If `stop-postgres` is combined with another goal, Make exits with a clear error
before running recipes. Requiring a standalone invocation avoids ambiguous
ordering and preserves the guarantee that requesting shutdown cannot
indirectly provision a database for another goal.

Normal invocations, including Make's default goal and all existing development
and test targets, continue to include and regenerate `.cache/postgres.mk`
exactly as they do today.

## Helper interface and data flow

The helper CLI exposes two mutually exclusive operations:

- `--makefile PATH` keeps the existing ensure/start/provision behavior and
  updates the generated Make include.
- `--stop` examines and, if necessary, stops the worktree-local managed
  cluster.

The stop operation always derives its cache directory from the repository
containing the helper. It never reads a data-directory argument from the user,
so it can act only on `.cache/postgres/data` in the current worktree. An
explicit external `DATABASE_URL` does not redirect the operation: the target
still concerns only the optional local managed cluster.

The stop flow is:

1. If the managed data directory does not exist, report that no managed
   cluster exists and return success without discovering PostgreSQL tools.
2. If the server PID metadata is absent, report that the cluster is already
   stopped and return success without discovering PostgreSQL tools.
3. Locate PostgreSQL 18 tools from `PATH` or from the already-extracted,
   version-pinned fallback under this worktree's `.cache`. This lookup must not
   call the fallback downloader or create directories.
4. Use `pg_ctl status -D <worktree-data-directory>` to distinguish a running
   server from PostgreSQL's documented not-running status. A not-running
   result is a successful no-op; any other unexpected status failure is an
   error.
5. For a running server, execute `pg_ctl` with the same data directory, fast
   shutdown mode, and wait enabled. The checked subprocess result becomes the
   command's exit status.

Fast mode is intentional: cleanup should disconnect lingering clients and
finish predictably rather than wait indefinitely for every client to leave.
Waiting remains mandatory so a successful Make result means worktree files are
no longer held by PostgreSQL.

The stop path must not call `fallback_tools`, `initialize_cluster`,
`choose_port`, `start_cluster`, `wait_for_ready`, `provision_database`, or
`verify_contract`.

## Error handling

Missing and already-stopped clusters are normal states and return zero. If PID
metadata indicates that a server may exist but compatible existing tools
cannot be found, the helper fails with an actionable error rather than
downloading tools or claiming success. Unexpected `pg_ctl status` results and
failed shutdowns also propagate as nonzero exits through the helper's existing
error boundary.

The target does not remove stale metadata. Its responsibility is process
shutdown; later worktree deletion removes the disposable cache. Avoiding
cleanup mutations also prevents a failed status check from destroying evidence
needed for diagnosis.

## Testing

Focused helper tests cover:

- a running cluster, asserting the exact worktree data directory plus fast and
  wait arguments;
- an already-stopped initialized cluster;
- a missing data directory;
- discovery from an existing extracted fallback without downloading;
- unexpected status and shutdown failures returning errors; and
- the stop CLI selecting shutdown without entering the ensure path.

A focused Make integration test invokes a dry run with an alternate missing
`POSTGRES_MK` path and an explicit inert external `DATABASE_URL`. It verifies
that `make stop-postgres` succeeds without creating or remaking that include
and that the printed recipe selects `--stop`, not `--makefile`. A second test
verifies that mixed goals fail before either lifecycle operation can run.

The complete repository gate remains `make check`, using the default parallel
worker count and the managed hidden-process procedure required on Windows.

## Documentation

The README development section identifies `make stop-postgres` as the command
to run before removing a worktree. `docs/database.md` documents the managed
cluster lifecycle, its fast shutdown behavior, idempotency, and the fact that
the command does not affect an external `DATABASE_URL` server.
