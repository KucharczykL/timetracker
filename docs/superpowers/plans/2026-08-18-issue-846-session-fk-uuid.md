# ID-08 implementation plan: session foreign keys on UUID identity

Executes
[the ID-08 design](../specs/2026-08-18-issue-846-session-fk-uuid-design.md) for
#846. Four commits. The first two are behaviour-preserving against the current
integer schema and land independently; the third is the cutover and cannot be
split without a red gate in between.

Delete this file before the PR merges — ID-07's plan was consumed the same way,
leaving the spec as the durable half.

## Task 1 — filter lookups and the ownership audit (pre-cutover)

`games/filters.py`: the six sites at `:185`, `:258`, `:259`, `:309`, `:320`,
`:575`, plus the two `# filters on …_id` field comments.
`games/management/commands/audit_library_ownership.py`: `:218`, `:230`.

`game__id` / `device__id` resolve the same rows on an integer foreign key, which
is what lets this land first — with one deliberate exception. `DeviceFilter`'s
NONE/ALL path stops returning zero devices when a matching session has no
device (spec, "not behaviour-neutral"); that is the one assertion in this commit
that changes.

Tests: extend `tests/test_filters.py`'s `fields[...].lookup` metadata
assertions, and add the `DeviceFilter` null-device case to
`tests/test_filter_cross_entity.py`. Run `make test-fast ARGS="tests/test_filters.py
tests/test_filter_cross_entity.py tests/test_filter_execution.py"` while
iterating.

## Task 2 — form initial seeding (pre-cutover)

`games/forms.py`: `seed_related_initial` skips a field whose current initial is
already a `models.Model` (the caller-seeded case), then `SessionForm.__init__`
calls it with `("game", "device")`.

Order matters: write the guard first. Adding the call without it regresses
`tests/test_user_preference_consumers.py:167` — the default-device prefill
`edit_session` (`games/views/session.py:247`) passes in.

Tests: the existing prefill test must stay green; add the explicit case that a
caller-supplied instance survives seeding on a session whose own device is NULL.

## Task 3 — the cutover (one commit)

The moment the foreign keys move, the committed fixture stops deserializing and
three query sites compare a uuid against a bigint, so models, migration, read
and write paths, fixture, loader and anonymizer land together.

**Schema**
- `games/models.py`: `to_field="uuid"` on `Session.game`, `Session.device`,
  `UserLibraryPreferences.default_device`; `set_default_device`'s short-circuit
  compares `getattr(device, "uuid", None)`.
- `games/migrations/0011_session_fk_uuid.py`, hand-written, depending on
  `0010_platform_fk_uuid`. Six operations for `Session.game`, five each for the
  two nullable relations, one `RunPython` carrying all three backfills and the
  reconciliation, one `SET CONSTRAINTS ALL IMMEDIATE` before the schema
  alterations. Copy the shape from `0010`; copy the NOT NULL variant from
  `0009`.
- Confirm `makemigrations --check --dry-run` is clean afterwards.

**Read/write paths**
- `games/views/game.py:109`: `game=OuterRef("pk")` → `OuterRef("uuid")`.
- `games/signals.py:113`: `Game.objects.filter(pk=game_pk)` → `filter(uuid=…)`.
- `games/api.py:490-494`: bind the `owned_or_404` result and assign
  `session.device = device`.
- `common/layout.py:190`: `seen: set[int]` → `set[uuid.UUID]`.

**Fixture and commands**
- Regenerate `games/fixtures/sample.yaml.gz` with the throwaway transform (spec,
  three steps). Do not commit the script. Record the verification numbers in the
  PR body.
- `load_sample_data.FIXTURE_RELATIONSHIPS`: `reference_field="uuid"` on both
  `games.session` entries.
- `anonymize_sample._anonymize`: the session loop reads `game_offsets_by_uuid`.

**Tests**
- New `tests/test_session_fk_uuid.py` — migration, reverse, ORM, database
  integrity (both models, via `bulk_create`), form, API, filtered playtime. Mirror
  `tests/test_playhistory_fk_uuid.py`'s harness; write the migration test before
  the migration and read the failure rather than guessing whether Django's final
  `AlterField` renames and constrains in one step (it did in `0009` and `0010`).
- Update: `tests/test_library_commands.py:309` and `:350-378`,
  `tests/test_library_models.py:219`, `tests/test_stats_links.py:156`,
  `tests/test_library_api_isolation.py:262`,
  `e2e/test_custom_elements_e2e.py:108`.

## Task 4 — documentation and handoffs

- Amend the wave plan: ID-08 owns `UserLibraryPreferences.default_device` (its
  "belongs to no wave" note goes), and add the two lessons this slice adds to the
  checklist — correlated subqueries are a fourth lookup direction, and a second
  `seed_related_initial` call site meets callers that seed their own initial.
- Comment on #847 (ID-09) and #850 (ID-14) with what each inherits: ID-09 owns
  the global integer→UUID flip of filter and search option values; ID-14 finds
  no integer foreign key left pointing at `Device`.
- Reduce this plan to nothing (delete) and keep the spec.

No follow-up issues expected: the two gaps this slice touches are already filed
(#869 fixture uuid timestamps, #870 `AutoPlayEventIn`).

## Gate

Full `make check`, including `e2e/`, before the PR. `make check-fast` while
iterating. `PYTEST_WORKERS=0` when reading a failure.
