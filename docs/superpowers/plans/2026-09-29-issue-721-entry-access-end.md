# #721 plan: a copy's access ends and resumes

Spec: [A copy's access ends and resumes](../specs/2026-09-29-issue-721-entry-access-end-design.md).
Inline, test first, one commit per task. `make check-fast` while iterating;
full `make check` once at the end, under the shared lock.

## Task 1: the primitive's resume

- `games/events/endpoint.py`: `EndpointEvents.resumed: EventSpec[Any] | None
  = None`; `specs` property; `family -> tuple[EventType, ...]`;
  `endpoint_events(..., resumed: EventType | None = None)` registers
  through `specs`.
- `games/events/projection.py`: `project_resumed(endpoint: EndpointColumns,
  event)` = `unstated_columns()`.
- `games/commands/endpoint.py`: `resume_endpoint`; `EndpointSentences.
  nothing_to_resume: Rejection | None = None` (last); `normalized(statement)`
  over both shapes (`stated_date`, strip note); `certainly_reversed(*,
  earlier, later)` and `_bounding_qualifier`, moved from
  `games/commands/playthrough.py`.
- Callers: `games/commands/playthrough.py`, `games/writes/playthrough.py`,
  `tests/test_playthrough_command.py` (rename + keywords);
  `games/commands/device.py` and `games/commands/libraryentry.py` use the
  shared `normalized`.
- Tests: `tests/test_endpoint_primitive.py` walks `specs`; resume states
  unstated columns; refusal where none stands; `TypeError` without
  `resumed`; `family` with/without.

## Task 2: storage and ways

- `games/end_ways.py`: `RETURNED`, `EXPIRED`, `REVOKED`, `REFUNDED` + labels.
- `games/models.py`: `ENTRY_WAYS` (nine), `ENTRY_ACCESS_END_COLUMNS`
  (`name="access_end"`, the six columns), fields on `LibraryEntry`,
  `*endpoint_constraints(ENTRY_ACCESS_END_COLUMNS)` in `Meta.constraints`.
- `make makemigrations ARGS="games --name libraryentry_access_end"` →
  `0021`; confirm it touches only `libraryentry`.
- Tests: `tests/test_libraryentry_model.py` both CHECKs; E014 green.

## Task 3: events, projector, endpoint

- `games/events/libraryentry.py`: `EntryWayValue` Literal (nine);
  `LibraryEntryAccessEndPayload` (`way`, `note`), voided payload empty;
  `ENTRY_ACCESS_END_EVENTS = endpoint_events("libraryentry", stated=...,
  corrected=..., voided=..., resumed="library.libraryentry.access_resumed",
  payload=..., voided_payload=...)`; builders
  `libraryentry_access_ended`, `libraryentry_access_resumed`.
- `games/endpoints.py`: `ENTRY_ACCESS_END = Endpoint.over(...)`, in
  `ENDPOINTS`.
- `games/projectors/libraryentry.py`: four handlers.
- Tests: `tests/test_libraryentry_events.py` (Literal = `ENTRY_WAYS`),
  `tests/test_libraryentry_projection.py` (end, correct, void, resume,
  second end), `tests/test_projection_replay_gate.py` (count 45 → 49,
  stream through all four).

## Task 4: commands

- `games/events/dispatch.py`: `LIBRARYENTRY_END_ACCESS`,
  `_CORRECT_ACCESS_END`, `_VOID_ACCESS_END`, `_RESUME_ACCESS`.
- `games/commands/libraryentry.py`: `check_way`, sentences,
  `EndEntryAccess`, `CorrectEntryAccessEnd`, `VoidEntryAccessEnd`,
  `ResumeEntryAccess`; `before_event` = live act, then day order;
  `CorrectEntryAcquisition` gains the day order against a standing end.
- Tests: `tests/test_libraryentry_command.py` every refusal, `Unchanged`
  ahead of refusals, each day-order sentence, qualifier admits;
  `tests/test_endpoint_fingerprints.py` one per command.

## Task 5: writes and API

- `games/writes/libraryentry.py`: `Keep`/`KEEP`; `restate_entry(...,
  acquired=KEEP, access_end=KEEP)`: draft check, description, then the
  two endpoints in the safe order (`restate_run`'s `_order` pattern);
  `resume_entry_access`.
- `games/api.py`: `EntryAccessEndIn {ended, way, note}` (`extra="forbid"`,
  way an enum of `ENTRY_WAYS`); `EntryUpdate.access_end`; `EntryResumeIn
  {resumed, note}`; `POST /{entry_id}/resume`; `EntryOut` end fields.
- Tests: `tests/test_libraryentry_writes.py` (ordering both directions,
  reversed draft appends nothing, KEEP); API tests beside the M1 entry API
  tests (shapes, null void, absence, 422, resume, idempotency key, 409,
  foreign 404).

## Task 6: close

- `CLAUDE.md` LibraryEntry paragraph and the endpoint paragraph (a resume
  act); `docs/event-retention.md` if it lists endpoint acts.
- `make vale`, `make format`, `make lint-fix`, full `make check`.

## Follow-ups (comments, no new issues)

- #1344: the primitive's resume is ready; wire `library.device.access_resumed`.
- #1352: the entry form's end fields and the shared Device/entry fieldset.
- #727: refund day order and `refunded` by hand, per the spec's Limits.
