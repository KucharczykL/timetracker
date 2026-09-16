# CLEAN-03: Remove legacy Session storage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop the legacy `Session` table and every one-time module written to
migrate off it, convert the sample fixture to session events, and squash the
migration history with Django's tool.

**Architecture:** Five commits, each green on the full `make check`, ordered
so the migration history stops depending on the application first and every
later step is ordinary Django. The fixture lands first because it is the
conversion modules' last runtime caller.

**Tech Stack:** Django 6 migrations (`RunPython.noop`, `squashmigrations`,
`replaces`), PyYAML fixture, pydantic TypedDict payloads, pytest.

**Spec:** [docs/superpowers/specs/2026-09-16-issue-772-session-storage-removal-design.md](../specs/2026-09-16-issue-772-session-storage-removal-design.md)
— the plan argues from it; read both.

## Global Constraints

- Every command through `make`; no `direnv exec`, no raw `uv run` around a
  Makefile target. A missing target is added, not worked around.
- Gate is the full `make check` including `e2e/`; `make check-fast` for
  iterating only. Never run e2e while `make dev` is up.
- Nothing destroys a record; `delete` is Django's word, so prose says remove.
  `make vale` enforces the vocabulary over docs and comments.
- Comments explain intent only, no issue numbers except forward TODOs.
- Complete-word identifiers; compound types named.
- A test that POSTs through a dispatching view needs
  `@pytest.mark.django_db(transaction=True)`.
- Heredocs in a Bash call give the command a live stdin; a prompting command
  hangs. `make makemigrations` already passes `--noinput`.
- `make format` rewrites ```` ```python ```` fences in Markdown; use
  ```` ```text ```` for fragments.
- Do not read `games/migrations/0001_initial.py` whole (2,356 lines); grep it.

---

## Task 0: Preconditions

**Files:** none changed.

- [ ] Rebase the branch onto `origin/main`; worktrees are cut from stale
      `main`.
- [ ] `make fetch-dump` (the user runs it; needs `PROD_SSH_HOST` in `.env`).
      Confirm a file in `.dumps/`. **No dump, no start** (spec §Verification).
- [ ] Capture the baseline count on the current commit: into the empty
      development database, `make devlogin` then `make loadsample USER=admin`,
      and read `PlayerSession.objects.count()` in `make shell`. Write the
      number into the Task 1 checklist. Captured on `bb41e358`: 2,807
      sessions, 873 runs, 0 calendars. `make reset-db` empties it again.
- [ ] Capture the before pages: `make restore-dump` prints a `DATABASE_URL`;
      `make render-pages DATABASE_URL=<url> ARGS="--user <prod user> --out
      /tmp/render-main"`. Kept for Task 5's diff. `make drop-dump` after.

---

## Task 1: The sample fixture carries session events

**Files:**
- Modify: `games/events/vocabulary.py` (`EventTypeRegistry`)
- Modify: `games/management/commands/anonymize_sample.py`
- Modify: `games/management/commands/load_sample_data.py`
- Replace: `games/fixtures/sample.yaml.gz` (regenerated, never hand-edited)
- Rewrite: `tests/test_anonymize_sample.py`
- Modify: `tests/test_library_commands.py:248,345,406` (fixture-format cases
  with `"model": "games.session"` records)
- Test: `tests/test_event_references.py` (holds the `references_in` cases;
  the two new registry methods go beside them)

**Interfaces produced:**
- `EventTypeRegistry.aggregate_id_keys(event_type: EventType) -> tuple[str, ...]`
  — top-level payload keys annotated `ReferenceId`, from
  `get_type_hints(payload, include_extras=True)`, matching on
  `isinstance(hint, TypeAliasType) and hint.__name__ == "ReferenceId"`.
- `EventTypeRegistry.dated_keys(event_type: EventType) -> DatedKeys` — a
  `NamedTuple(instants: tuple[KeyPath, ...], days: tuple[KeyPath, ...])`,
  `type KeyPath = tuple[str, ...]`, walking top-level hints, `X | None`
  unions, and a nested TypedDict or discriminated union of TypedDicts (the
  `timing` field: its alias's `__value__` is `Annotated[Union[...], Field]`;
  walk every member, union of their keys). `InstantText` and `DayText` are
  `TypeAliasType`s too.
- Anonymizer module functions, pure, tested directly:
  - `shift_instant(text: str, *, days: int, zone: str) -> str` — read in
    `zone`, move `days` calendar days at the same wall time, write back
    canonical instant text.
  - `shift_timing(payload: dict, *, days: int) -> dict` — start shifted with
    `shift_instant` in the payload's `day_zone`; end = shifted start + original
    elapsed; `stated_day` moved `days` days. Uses `dated_keys` to know which
    keys, so no mode branching beyond "an end follows its start".

**Behaviour to implement (spec §The sample fixture carries session events):**

Anonymizer:
1. `DUMP_LABELS`, `IDENTITY_MODELS`, `_prune_other_libraries`, the session
   pass (`:279-294`), `GENERATED_FIELDS`' two duration entries, the
   `"sessions"` count: gone. Count reports `library.playersession.created`
   events.
2. `game_id_by_aggregate` gains
   `dict(PlayerSession.objects.values_list("pk", "playthrough__player_game__game_id"))`.
3. Calendar event (`aggregate_id == library.pk`): skipped by the offset
   lookup, by `_group_replacements` for aggregates, and written with
   `aggregate_id = TARGET_LIBRARY_MARKER` in `_write_fixture` (the dump emits
   the literal uuid; replace where `library` gets its marker). It keeps
   `FIXED_EPOCH` as `recorded_at`.
4. Dated payload keys shifted with `shift_timing` / `shift_instant` over the
   keys `dated_keys` answers (`ended` events carry a top-level `ended_at`).
5. Undated event's `recorded_at`: the `_midnight` of the latest earlier dated
   event in the same aggregate (by `sequence`), else `FIXED_EPOCH`. Compute
   in one pass over events sorted by `(aggregate_id, sequence)`.
6. Bare aggregate keys: for each key in `aggregate_id_keys(event_type)`,
   `payload[key] = str(aggregate_replacements.get(UUID(payload[key]), ...))`.
   Remove the `PLAYTHROUGH_CREATED` special case (`:529-535`) and its import.
7. References: for each `found` in `references_in`, look the kind up in
   `DEFAULT_REFERENCE_KINDS` for its model, take that model's replacement map
   from `replacements_by_model`, `capture_reference(model.objects.get(pk=new))`.
   `LibraryEventReference.referenced_id` remapped by the same kind→model map.
8. `event.source_metadata = {}`.

Loader:
1. `LOADABLE_MODELS` / `FIXTURE_RELATIONSHIPS` lose `games.session`; the
   `Session` import, the `games.backfill.*` imports, `SAMPLE_REPORT_PREFIXES`,
   the `convert_library` block and the "converted" clause of the success line
   go.
2. `_prepare_private_records`: for `games.libraryevent` with
   `fields["aggregate_id"] == TARGET_LIBRARY_MARKER`, write `str(library.pk)`.
3. `_validate_records`' payload-reference pass: generic over kinds — map
   `found.value["kind"]` through `DEFAULT_REFERENCE_KINDS` to the model's
   `_meta.label_lower`, require `(label, id)` in `record_keys`; keep the
   platform refusal. Same for `games.libraryeventreference` rows.

**Tests (name each; assert the behaviour, not the implementation):**
- vocabulary: `aggregate_id_keys` answers `("playthrough",)` for created and
  moved, `("player_game",)` for playthrough.created, `()` for
  `playergame.created`; `dated_keys` answers instants
  `(("timing","started_at"), ("timing","ended_at"))` and days
  `(("timing","stated_day"),)` for created, `(("ended_at",),)` for ended.
- `shift_instant` across a DST change keeps wall time; `shift_timing` keeps
  elapsed time and moves `stated_day` by the offset.
- `test_anonymize_sample.py`: `_build_dataset` records three sessions through
  `record_session(actor, SessionDraft(...), correlation_id=uuid.uuid7())`
  (one Timed with device and note, one Duration-only, one Corrected then
  removed via `remove_session`), and changes the calendar through
  `change_user_setting(... DISPLAY_TIME_ZONE ...)` so a calendar event exists.
  Assertions: no `games.session` record; every dated session event's day
  moved by its game's offset (read the offset back from the `playergame.created`
  event's `effective_time` delta); notes blank; device reference label equals
  the scrubbed device name; `playthrough` key equals the created event's new
  `aggregate_id` for that run; calendar event `aggregate_id ==
  "__target_library__"`; `source_metadata == {}`; the removed session's
  `removed` event `recorded_at` is not before its `created`; reload via
  `load_sample_data` gives `PlayerSession.objects.count() == 3` and one
  `LibraryCalendar` whose id is the target library.
- `test_library_commands.py`: retarget the three fixture-format cases onto
  `games.libraryevent` records (copy one from the real fixture's shape).

**Regenerate the fixture** (the user's step, on the restored dump):
`make restore-dump`, `make migrate DATABASE_URL=<url>`,
`make anonymize-sample USER=<prod user> DATABASE_URL=<url>`. Then into the
empty scratch database `make loadsample USER=admin` and check
`PlayerSession.objects.count()` equals Task 0's number, `make
verify-replay-parity` and `make audit-uuid-identity` clean, a second
`loadsample` refused with a sentence.

- [ ] Vocabulary methods + tests → `make test ARGS="tests/<vocab file> -x"`.
- [ ] Anonymizer + loader + tests → `make test ARGS="tests/test_anonymize_sample.py tests/test_library_commands.py -x"`.
- [ ] Regenerate gz; loadsample checks above.
- [ ] `make check` green. Commit: `feat: carry session events in the sample fixture`.

---

## Task 2: The migration history stops depending on the application

**Files:**
- Modify: `games/migrations/0004_playersession_conversion.py` — keep
  `dependencies`; operations become
  `[migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop, elidable=True)]`;
  drop the module-level constants and the callable.
- Modify: `games/migrations/0005_library_calendar.py` — same for
  `seed_calendars`; keep `CreateModel`.
- Remove: `games/backfill/` (whole), `games/preflight/` (whole),
  `games/management/commands/preflight_sessions.py`,
  `games/management/library_scope.py`
- Remove: `tests/test_playersession_conversion.py`,
  `tests/test_session_preflight.py`; the block
  `tests/test_calendar.py:327-500` from the `# --- migration 0005's seed and gate`
  divider to end, and its now-unused imports (`CalendarMismatchCode`,
  `seeding`, `Mismatch`); the `MODE_VERDICTS` import in
  `tests/test_playersession_projection.py:44`.
- Modify: `tests/test_playersession_projection.py:475-478` — the test becomes
  `assert {mode.value for mode in PlayerSessionTimingMode} == {"timed", "duration_only", "corrected"}`
  with a docstring saying the payload discriminator spells them.
- Modify: `Makefile:364-368` (`preflight-sessions` block), CLAUDE.md row
  `Census the legacy Session rows`, the `#700's games/backfill/playersession.py`
  paragraph under **PlayerSession**, the `MODE_VERDICTS` sentence in
  `games/models.py:1767`.

**Gotcha:** `test_calendar.py:387-403` migrates the test database backward to
`0004` and forward to `0005` with a `MigrationExecutor`. It goes with the
block; a harness that migrates backward past a dropped table is the trap that
killed two CLEAN-02 attempts (docs/migration-squash.md step 4).

- [ ] `make check-fast` green; `grep -rn "games.backfill\|games.preflight\|library_scope" games tests Makefile CLAUDE.md` empty.
- [ ] `make check` green. Commit: `refactor: retire the session conversion and census`.

---

## Task 3: One playtime source

**Files:**
- Remove: `games/reads/playtime/legacy.py`, `games/reads/playtime_parity.py`,
  `games/reads/session_parity.py`,
  `games/management/commands/verify_session_parity.py`,
  `tests/test_session_parity.py`
- Create: `games/reads/playtime.py` from `games/reads/playtime/__init__.py` +
  `source.py` (minus the three Protocols) + `projection.py` (its functions at
  module level under the names `__init__` exported; keep `UnscopedSum` and
  `UnscopedPlaytimeRead`). Then remove the package directory.
- Modify: `games/management/commands/render_pages.py:22,86` and
  `games/events/benchmark_reads.py:17,67` — `from games.reads.playtime import played_years`.
- Modify: `tests/test_playtime_sources.py` — drop the `legacy` cases
  (`:240-251`, `:333`), import the projection names from `games.reads.playtime`.
- Modify: `Makefile:383-386` (`verify-session-parity` block), CLAUDE.md row
  `Compare every playtime and session figure...`, the **Playtime reads**
  paragraph (one source, no `PlaytimeSource`, no parity command), the
  `#704's gates` paragraph's `verify-session-parity` sentence, and the
  convention **Playtime is read, never stored** (a new figure is a function in
  `games/reads/playtime.py`).

**Interfaces:** every public name of the package survives:
`DayInterval`, `MonthPlaytime`, `PlatformPlaytime`, `DayPlaytime`,
`UnscopedPlaytimeRead`, `game_playtime`, `game_playtime_between`,
`playtime_between`, `playtime_by_game`, `playtime_by_month`,
`playtime_by_platform`, `playtime_matching`, `playtime_sort_key`,
`total_playtime`, `played_years`, `playtime_by_day`.

- [ ] `make check-fast` green; `grep -rn "playtime.source\|playtime.projection\|playtime.legacy\|SOURCE\b" games tests | grep playtime` empty.
- [ ] `make bench` still runs (`ARGS="--seed 300"` is enough).
- [ ] `make check` green. Commit: `refactor: read playtime from one source`.

---

## Task 4: The table goes

**Files:**
- Modify: `games/models.py:1180-1291` — remove `SessionQuerySet` and `Session`;
  the `Device` docstring line that names them; the legacy comparisons in
  `PlayerSession`'s comments (`:1810`, `:1823`) become plain statements.
- Modify: `games/removal.py:23,34` — drop the import and the registry entry.
- Modify: `games/views/device.py:164` —
  `library_sessions(library).filter(device=device).count()`; import
  `library_sessions` from `games.reads.player_sessions`.
- Create: `games/migrations/0006_remove_session.py` via
  `make makemigrations ARGS="games --name remove_session"`, then add the guard
  as the first operation:

```text
def refuse_unconverted_rows(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM games_session s WHERE NOT EXISTS ("
            "SELECT 1 FROM games_libraryevent e WHERE e.aggregate_id = s.id "
            "AND e.event_type = 'library.playersession.created')"
        )
        (unconverted,) = cursor.fetchone()
    if unconverted:
        raise RuntimeError(
            f"{unconverted} legacy session row(s) have no event; upgrade "
            "through a release that applied 0004_playersession_conversion first."
        )
```

  `migrations.RunPython(refuse_unconverted_rows, migrations.RunPython.noop, elidable=True)`.
  No `games.models` import anywhere in the file.
- Modify: `tests/session_rows.py` — remove `Session` import, `Twin`,
  `timed_twin`, `duration_only_twin`, `corrected_twin`; keep `tracked_run`,
  `projection_row`, `timed_row`, `duration_only_row`, `corrected_row`,
  `session_row`, `run_id`.
- Remove: `tests/test_session_import_guard.py`,
  `tests/test_generated_duration_columns.py`, `tests/test_session_querysets.py`,
  `tests/test_session_timezones.py`, `games/fixtures/data.yaml`, `Makefile:392-393`
  (`loadall`).
- Retarget (the 27-file list in spec §Tests; enumerate again with the AST
  scan below, never from memory):
  - `tests/test_removable_models.py:50,80` — drop `_session` builder and row.
  - `tests/test_removal.py`, `tests/test_retention.py`, `tests/test_signals.py`,
    `tests/test_sentinel_removal.py`, `tests/test_library_models.py`,
    `tests/test_library_config_identity.py`, `tests/test_catalog_hierarchy.py`,
    `tests/test_playergame_view_cutover.py`, `tests/test_playthrough_view_cutover.py:396-423`
    — build `PlayerSession` rows with `timed_row(tracked_run(library, game), ...)`.
  - `tests/test_keyset.py` — page `PlayerSession` on `("sort_instant", "id")`.
  - `tests/test_uuid_identity_audit.py:65-66,122-127,383` — drop the
    `games_session` pairs from the expected relation set; the doctored-type
    case keys on `games_playersession.playthrough_id`.
  - `tests/test_session_fk_uuid.py`, `tests/test_session_identity.py` — keep
    only assertions about `PlayerSession`; a case whose subject is the legacy
    column goes.
  - `tests/test_filters.py:3435` — `player_games__playthroughs__sessions__note`;
    `:3088` docstring names `effective_duration`.
  - `tests/test_api.py:177`, `tests/test_stats.py:5,78,108`,
    `tests/test_session_form_derivation.py:161`, `tests/test_relation_algebra.py`
    — `duration_manual` kwargs are `session_row(...)`'s own parameter; leave
    unless the scan flags them.
  - `e2e/test_datetime_field_e2e.py:303` docstring.
- Docs: CLAUDE.md — remove the **Session** bullet (`:159`), the
  `tests/test_session_import_guard.py` sentence in it, the `GeneratedField
  constraint` list (`:417`, `:819`) loses `duration_calculated`/`duration_total`;
  `docs/database.md:76-78` loses the two bullets. CHANGELOG `## Unreleased`
  → `### Changed`: one line, "The legacy session table is gone; every session
  is its events."

**The AST scan** (run before and after; the after-run must print nothing).
A throwaway `scripts/legacy_session_scan.py`, run with the interpreter the
Makefile uses (`uv run --frozen python scripts/legacy_session_scan.py`),
removed before the commit. It walks `tests/` and `e2e/` with `ast` and
reports every `ImportFrom("games.models")` alias in
`{"Session", "SessionQuerySet"}`, every `Name` in
`{"timed_twin", "duration_only_twin", "corrected_twin", "MODE_VERDICTS"}`,
and every string constant containing `games_session`, `games.session` or
`sessions__` (allowing `playthroughs__sessions__`). Start from
`tests/test_session_import_guard.py`'s `legacy_reads`, which already matches
the first shape.

- [ ] Model + registry + view + migration; `make check-migrations` clean.
- [ ] Guard rehearsal: on a copy of the dump (`make restore-dump`), insert one
      `games_session` row whose id names no event, run `make migrate
      DATABASE_URL=<url>`, expect the sentence; drop the row, migrate again,
      expect success. `make drop-dump`.
- [ ] Test triage; scan prints nothing.
- [ ] `make verify-dump` green. `make check` green.
- [ ] Commit: `feat: remove the legacy Session table`.

---

## Task 5: Squash

**Files:**
- Modify: `Makefile` — add after `check-migrations`:

```text
# Squash the history with Django's tool. Usage: make squash-migrations ARGS="games 0006"
squash-migrations: ensure-postgres
	uv run --frozen python manage.py squashmigrations --no-input $(ARGS)
```

- Create: `games/migrations/0001_squashed_0006_remove_session.py` — the tool's
  output, unedited. Expect 70 operations, `replaces` naming six, no
  `RunPython`, `CreateModel Session` and `DeleteModel Session` both present.
- Modify: `docs/migration-squash.md` — a dated paragraph under a new
  `## Second squash, 2026-09` heading: tool used, both `RunPython`s elided,
  the four `RunSQL` barriers kept the Create/Delete pair and the `playtime`
  add/remove, old files kept until the deployment recorded the squash.
- Modify: CLAUDE.md commands table — a row for `make squash-migrations`.

- [ ] `make squash-migrations ARGS="games 0006"`; inspect with grep only.
- [ ] `make check-migrations` clean; `make check` green (fresh test databases
      now build from the squashed file alone).
- [ ] Bare `make verify-baseline` green against the dump.
- [ ] `make render-pages` at the branch head against the restored dump;
      `diff -r /tmp/render-main /tmp/render-branch` empty.
- [ ] Commit: `chore: squash the migration history through 0006`.

---

## Task 6: Close out

- [ ] File the follow-up issue: "Squash step two" — after the deployment has
      applied `0006` and `django_migrations` holds the squashed row, remove
      `0001`–`0006`, drop `replaces`, retarget
      `tests/test_dump_restore_roundtrip.py:191`'s import of `0001_initial`
      (the squashed file inlines the SQL; export the constant from it or read
      it from the deployment). Link it from the spec's Follow-ups.
- [ ] Comment on #772 with the commit list and the loadsample / verify-dump /
      verify-baseline / render-pages evidence.
- [ ] Docs sweep: this plan file is removed; the spec is rewritten timeless
      (200–500 words) in its Design section; comments trimmed.
- [ ] Open the PR with `gh pr create`; merge only when told.
