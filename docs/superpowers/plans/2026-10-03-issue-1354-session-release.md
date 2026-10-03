# Plan: a session or a record names its Release (#1354)

Spec: [design](../specs/2026-10-03-issue-1354-session-release-design.md).
Implementation inline, TDD per behaviour. Iterate with focused
`make test ARGS=…` and `make check-fast` under the shared lock.

## Task 1 — Payload and vocabulary

Files: `games/events/references.py` (or `games/events/playersession.py`),
`games/events/playersession.py`, `games/events/historical_playtime.py`,
`games/events/idempotency.py`.

- `ReleaseReference = Annotated[Reference, AfterValidator(_release_kind)]`,
  refusing any kind but `catalog.release`. Place beside `Reference`
  so both payload modules import it.
- `PlayerSessionCreatedPayload.release: ReleaseReference | None`; drop
  the "reserved and always None" sentence.
- New `PLAYERSESSION_RELEASE_CHANGED` (`library.playersession.release_changed`,
  payload `{release: ReleaseReference | None}`), registered;
  `playersession_release_changed(session_id, *, release)`.
- `HistoricalPlaytimeStatementPayload.release: ReleaseReference | None`;
  `_statement`, `historicalplaytime_created`, `historicalplaytime_restated`
  take `release`.
- `HistoricalPlaytimeMovedPayload.release: NotRequired[None]`;
  `historicalplaytime_moved(..., clears_release: bool = False)` sets the
  key only when true.
- `FINGERPRINT_VERSION = 4`.

Tests: `tests/test_playersession_events.py` (release kind accepted /
device kind refused; release_changed shape), `tests/test_historical_playtime_events.py`
(":122 release-stated" case flips to a valid `catalog.release` and a
refused `device`; the moved payload pin at :268 gains the keyed case).

## Task 2 — Model, migration, audit

Files: `games/models.py`, `games/projections.py`, new migration via
`make makemigrations ARGS="games --name session_record_release"`.

- `PlayerSession.release`, `HistoricalPlaytime.release`: `ForeignKey(
  Release, on_delete=RESTRICT, null=True, related_name="+")`. No
  default on the session (the creation names it); the record's
  creation and restatement name it too.
- `AUDITED_PROJECTION_REFERENCES`: `ProjectionReference.on(PlayerSession,
  "release")`, `ProjectionReference.on(HistoricalPlaytime, "release")`.
- Audit beside `entry_game_violations`: `session_release_violations`,
  `record_release_violations`, each `filter(release__isnull=False)`
  before `.exclude(release__edition__game=F(<row's game path>))`;
  join them where `entry_game_violations` is joined.

Tests: the audit tests beside `entry_game_violations`' (a null row is
no violation; a mismatched one is).

Gotcha: `_required_columns` counts a nullable FK with no default as
required, so Task 3's projectors must name `release_id` everywhere.

## Task 3 — Projectors

Files: `games/projectors/playersession.py`,
`games/projectors/historical_playtime.py`.

- `_created` names `release_id` (from `payload["release"]`).
- `_release_changed` amends `release_id`; add to `handles`.
- `StatementColumns`/`columns_for_statement` gain `release_id`.
- `_moved` (record) writes `release_id=None` only when `"release" in
  payload`.

Tests: projector tests; `tests/test_projection_replay_gate.py` — the
stream emits `release_changed` (needs a LibraryEntry on a Release of
the game), a session and a record created with a Release, and a record
`moved` with the key; bump the pinned `len(missing) == 64` count.

## Task 4 — The rule and the commands

Files: `games/reads/releases.py`, `games/commands/scope.py`,
`games/commands/playersession.py`, `games/commands/historical_playtime.py`,
`games/commands/session_reclassification.py`, `games/commands/playthrough.py`.

- `held_releases(library) -> QuerySet[Release]`: Releases named by
  `library_entries(library)`.
- `stated_release(context, release_id, *, game_id, held_id) ->
  Release | None` in `scope.py`: None → None; rule 2 always; rules 1
  and 3 only when `release_id != held_id`. Three sentences as constants
  (`RELEASE_REMOVED`, `RELEASE_OF_ANOTHER_GAME`, `NO_COPY_OF_RELEASE`).
  Rule 1: `visible_row(context, Release.objects.select_related(
  "edition__game"), Refusal(...), pk=…)`, then the three marks.
- `CreateSession.release_id: uuid.UUID | None = None`; build resolves
  against the run's game, held `None`.
- `StatedRelease(NamedTuple)`; `DescribeSession.release`; "states no
  fact" counts it; compare first (held → no event), then
  `stated_release`.
- `MoveSessionToPlaythrough`: when the target run's `player_game_id`
  differs and `session.release_id` is set, prepend
  `playersession_release_changed(session.pk, release=None)`.
- `HistoricalPlaytimeStatement.release_id = None`; Record (held None),
  Restate (held `record.release_id`, game = statement's runs' game),
  Reclassify (held `session.release_id`); `created_event` takes the
  release; `_held_columns` gains `release_id`.
- `MovePlaythroughToGame`: after `playthrough_moved`, one
  `release_changed(None)` per session of the run (plain manager,
  `library=`, `release__isnull=False`); records' moved pass
  `clears_release=record.release_id is not None` — `_records_that_follow`
  must answer the release with each id.

Tests (TDD, one per rule): create with held copy / ended copy passes;
no copy, removed copy, removed Release, another game's Release refused
with sentences; unseen Release 404; describe same Release Unchanged;
describe keeps held Release after `RemoveEntry`; restate record onto
another game repeating Release refused; reclassify carries Release;
move across games clears (event order); move within game keeps;
MovePlaythroughToGame clears sessions (removed too) and records.
Update `tests/test_command_answers.py` if a new conflict type appears
(none planned).

## Task 5 — Writes and answers

Files: `games/writes/playersession.py`, `games/writes/historical_playtime.py`,
`games/writes/playthrough.py`, `games/api.py`.

- `record_session(..., release_id=None)` passes through.
- `restate_session(..., release: StatedRelease | None)`: after the
  move, a separate `DescribeSession(release=...)` under the same
  correlation id, only when stated and differing.
- `describe_session` gains `release`.
- `MovedRun.cleared_releases: int = 0`; `_move` reads
  `dispatched_events(result)` payloads: `release_changed` events plus
  `historicalplaytime.moved` events with the key.
- Edit playthrough view toast names the count (sentence: "N sessions
  or records no longer name a release.").
- API: `SessionOut.release_id`, `SessionIn.release_id`, the PATCH body
  `release_id` dispatched after the move in its own describe;
  `HistoricalPlaytimeOut.release_id`. Readers add `release` to
  select/only lists if they restrict columns.

Tests: `tests/test_api_session*.py` (POST with Release, PATCH clear,
PATCH move+Release of target game), writes test for restate order,
playthrough move toast count.

## Task 6 — Search endpoints

Files: `games/api.py`, `games/reads/releases.py`.

- `GET /api/releases/held?game_id&q&limit` → `PickerOption`s over
  `held_releases(library).filter(edition__game_id=…)`, `matching_releases`,
  label `release_label`, `hint` = latest end way when every live copy
  of it is ended.
- `GET /api/releases/played?q&limit` → Releases named by
  `library_sessions`/`library_records` live rows; label
  `"{game} · {release_label}"`.
- `held_release_options(values, *, library, held=None)` resolver for
  the forms, which unions the held value.

Tests: API tests for both routes (scope, other library absent, hint).

## Task 7 — Forms

Files: `games/forms.py`, views that build `SessionForm` /
`HistoricalPlaytimeForm` (`games/views/session.py`,
`games/views/historical_playtime_entry.py`,
`games/views/session_reclassification.py`).

- `SessionForm.release` `ModelChoiceField(required=False)`,
  `SearchSelectWidget(search_url=HELD_RELEASE_SEARCH_URL, params=
  {"game_id": {"field": game_field}}, none_label="Not stated")`, label
  "Release", ordered after `playthrough`. Queryset
  `held_releases(library) | Release.objects.filter(pk=instance.release_id)`.
  `clean` refuses a Release whose game ≠ chosen game
  (`RELEASE_OF_ANOTHER_GAME`). `_session_initial` seeds it.
- `HistoricalPlaytimeForm.release` after `playthroughs`, params game
  fixed by `value`; seeds from record or session; `statement()` passes
  `release_id`.
- Views pass the release to `record_session`/`restate_session`.

Tests: form tests (choice listing, held kept, other game refused),
`test_rendered_pages` if it pins field order; e2e: one test in
`e2e/` picking a Release on the session form.

## Task 8 — Bulk Edit

Files: `games/bulk_session_edit.py`.

- `EditJson.release`, `EditStatement.release: StatedRelease | None`,
  encode/decode (`_release_key`), `describes()`, refusal text includes
  "a release".
- `BulkEditForm.release`: `UnsetWidget(SearchSelectWidget(search_url=
  HELD_RELEASE_SEARCH_URL, options_resolver=…), none_label="No release")`
  (inner picker without `none_label`); params set with the run picker's
  one game; `offer_edit` drops it with the playthrough field for
  several games; placeholder `keeping(rows, release name)`.
- `settle_edit` validates a stated Release is held.
- `edit_one`: description of release in its own `DescribeSession`
  after the main one; a row at another game refused per row (rule 2's
  sentence via `CommandFailed`).
- `values_before`/`_release_of`; `edit_back` restates the release in its
  own dispatch after the other facts.
- Preview column "Release".

Tests: `tests/test_bulk_session_edit.py` cases: set, ⊘ clear, keep,
Undo, Undo with copy gone refuses only the release, several-games
selection has no field.

## Task 8b — Seeds and fixtures

- `session_events` (bench seed) passes `release=None`; benchmark
  workload `HistoricalPlaytimeStatement` callers work via the default.
- `verify_reclassification_parity`, `statement_from_session`: carry the
  session's `release_id`.
- Sample fixture: unchanged (no stream names a Release).

## Task 9 — Filters and outside dates

Files: `common/criteria.py`, `games/filters.py`.

- `outside_interval_handler(day, lower, upper, *, unless: Q | None = None)`.
- `outside_playthrough_dates` passes
  `unless=Q(release__edition__kind=EditionKind.PRERELEASE)`.
- `PlayerSessionFilter` / `HistoricalPlaytimeFilter`: `release:
  UUIDMultiCriterion` (`FilterField("release_id", search_url=
  "/api/releases/played")`), `edition_kind: ChoiceCriterion`
  (`FilterField("release__edition__kind", label="Edition kind")`).

Tests: filter tests for both fields, null; outside-dates demo case for
True and False; `organization_counts` excludes demo; filter-tree
contract fixtures if they enumerate fields; builder field-list pins.

## Task 10 — Docs sweep (after green)

Delete this plan; rewrite the spec timeless (200–500 words, STE);
CLAUDE.md PlayerSession/HistoricalPlaytime bullets gain one sentence;
wave doc's "Demo play before #1354" and cross-wave handoff lines
updated; comment #1358 and #1361. File follow-ups: Release column on
Playtime lists; `edition_kind` quick facets.
