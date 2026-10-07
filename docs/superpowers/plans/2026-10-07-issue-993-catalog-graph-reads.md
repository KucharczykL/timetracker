# Plan: the catalog graph reads its rows once (#993)

Spec: `docs/superpowers/specs/2026-10-07-issue-993-catalog-graph-reads-design.md`.

## Task 1: tests first (`tests/test_state_catalog_graph.py`)

- `test_statement_size_does_not_change_the_reads`: build a graph of 1×1 and
  of 3×3 platformed Releases (shared Platform), restate each with the same
  rows under `CaptureQueriesContext`; assert `SELECT` count is 3 for both.
  Second case: a new Platform → 4.
- `test_a_removed_standing_release_passes_the_mark_to_a_live_sibling`:
  Edition with Releases A (default), B; state the Edition naming A removed,
  B unmentioned, no mark → B is default.
- Edition twin: Editions A (default), B; state A removed, B unmentioned →
  B default.
- Run: red on the count test only.

## Task 2: `games/catalog_writes.py`

- `GraphRows` frozen dataclass: `editions: dict[EditionId, Edition]`,
  `releases: dict[ReleaseId, Release]`, `platforms: dict[PlatformId, Platform]`.
  PEP 695 aliases for the pk types.
- `_graph_rows(owner, library, editions)`: two reads, wire `edition.game`,
  `release.edition`; `select_related("platform")`; then `_locked_platforms`.
- `_newly_named_platforms(library, editions, stored_releases)` → pks, the
  exact "newly" rule; lock read ordered by pk, `removed_at__isnull=True`.
  Needs resolved releases, so order is: graph read → resolve → lock read.
- `_resolved_edition(rows, owner, state)`, `_resolved_release(rows, parent,
  state)`: dict lookups.
- `_refuse_platform(library, row, stored, locked)`: membership in `locked`.
- `_refuse_the_set`: `untouched` from live map rows minus named.
- Standing defaults from the map (live, `is_default`) before step 1.
- Step 1 release clear: one `UPDATE` with `edition_id__in`.
- `_edition_to_mark` / `_release_to_mark`: kept check is `removed_at is None`
  on the map instance; fallback is min pk among live map rows of that parent.
- Drop `_live_editions`/`_live_releases`/`_clear_*` helpers made unused.

## Gotchas

- Keep refusal order: platform refusal inside the per-Edition loop.
- Lock read happens after resolves (needs stored rows) and before
  `_refuse_the_set`; resolves themselves cannot raise on platforms.
- mypy: `Release.edition` assignment typed; pk types UUID.
