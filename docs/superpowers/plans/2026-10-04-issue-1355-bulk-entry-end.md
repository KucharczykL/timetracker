# Bulk end of access over copies — plan

Spec: `docs/superpowers/specs/2026-10-04-issue-1355-bulk-entry-end-design.md`.
Implementation inline, TDD per task. Iterate with focused
`make test ARGS=…` under the shared lock; `make check-fast` per task end.

## Task 1 — lift the Undo guard

- New `games/bulk_endpoint_undo.py`: `UndoSentences(NamedTuple:
  not_stated, changed_since)`, `refuse_unless_this_batch_wrote_it(events:
  Iterable[LibraryEvent], endpoint_events: EndpointEvents[Any], *,
  batch_id: uuid.UUID, row_description: str, sentences: UndoSentences) ->
  None`. Filters to `endpoint_events.family`; latest void passes; no
  batch stated event → `CommandRejected(not_stated)`; latest not the
  batch's last stated → `CommandRejected(changed_since)`. Messages name
  `row_description`, batch, event type and sequence.
- `games/bulk_playthrough_acts.py`: delete `_refuse_unless_this_batch_wrote_it`,
  `_START_FAMILY`, `_COMPLETION_FAMILY`; `void_start_one` /
  `void_completion_one` call the lifted guard under `answered("playthrough")`
  with `PLAYTHROUGH_START_EVENTS` / `PLAYTHROUGH_COMPLETION_EVENTS`,
  dropping the `stated_start(run) is not None` pre-check. Keep
  `NOT_STATED_BY_THIS_BATCH` / `CHANGED_SINCE` (tests import them) as a
  `RUN_UNDO = UndoSentences(...)`.
- Tests, `tests/test_bulk_endpoint_undo.py` (unit, over real events from
  a run or copy): latest void passes; no batch event refuses not_stated;
  later correction refuses changed_since; later resume refuses
  changed_since; batch's own event latest passes. In
  `tests/test_bulk_playthrough_acts.py`: run with start marker set by
  column update (`tracked_run` + update), no events, Undo refuses
  `NOT_STATED_BY_THIS_BATCH`. Existing run tests stay green.

## Task 2 — writes

- `games/writes/libraryentry.py`: `end_entry_access(..., source_metadata:
  SourceMetadata | None = None)` passed to `_dispatch`;
  `void_entry_access_end(actor, entry, *, correlation_id, idempotency_key,
  source_metadata)` dispatching `VoidEntryAccessEnd(entry_id=entry.pk)`.
- Tests in `tests/test_bulk_entry_end.py` cover them through the act;
  one direct test that the void answers `Unchanged` on a held copy.

## Task 3 — shared form and statement

- New `games/bulk_access_end.py`:
  - `encode_access_end(statement: WayActStatement) -> ChoiceValue`
    (`json.dumps(..., sort_keys=True)`, `when` as `.canonical`, None for
    unknown).
  - `decode_access_end(raw, ways: Sequence[EndWay]) -> WayActStatement`:
    `stated_object(raw, {"when", "way", "note"})`, all three keys
    required; `statement_unreadable` for a missing key, a way not in
    `ways`, a non-text day / note, an unparseable day, an unknown day
    spelled as text. Note through `normalised_note`.
  - `BulkAccessEndForm(PrimitiveWidgetsMixin, forms.Form)`:
    `__init__(data=None, *, prefix, ways, presentation, today)`; fields
    `way` (`ChoiceField`, label "What happened", choices from
    `END_WAY_LABELS`, blank first where UNSTATED absent), `ended`
    (`TemporalFormField(presentation=…, label="When", initial=
    TemporalValue.from_day(today))`), `note` (Textarea rows=2, label
    "Note", `clean_note` normalises); `statement() -> WayActStatement`.
  - `access_end_choice(ways) -> BulkChoice[Any]`: offer/settle closures;
    settle local-imports `CHOICE_FIELD`; refusal via `form_refusal(form,
    labelled=True)`.
- Tests (`tests/test_bulk_access_end.py`, no db where possible):
  encode/decode round trip incl. unknown day and month precision;
  `settle(settle(x)) == settle(x)`; decode refuses each malformed shape;
  form over `ENTRY_WAYS` initial way is `unstated`, day today; form over
  `DEVICE_WAYS` refuses blank way; settle refuses an invalid form with a
  labelled sentence.

## Task 4 — the act

- New `games/bulk_entry_end.py`:
  - `ENDED_ONE`/`ENDED_MANY` caution sentences, `already_ended(rows)`
    counting `copy_end(row) is not None`, None at zero.
  - `ENTRY_UNDO = UndoSentences(...)` copy wording from spec.
  - `END_PREVIEW = (*ENTRY_PREVIEW, PreviewColumn("Ended", _ended))`;
    `_ended` uses `copy_end(row)` and `present_temporal_value(end.when,
    presentations.dates)`, `–` when held.
  - `end_one(actor, entry, *, choice, idempotency_key, correlation_id)`:
    `settled(choice, partial(decode_access_end, ways=ENTRY_WAYS), …)`
    under `answered(SUBJECT)`, then `RowOutcome.of(end_entry_access(...,
    source_metadata={"bulk": {"action": ENTRY_END.name}}))`.
  - `end_back(actor, entry_id, *, undoes, idempotency_key,
    correlation_id)`: `removed_entry`, guard under `answered(SUBJECT)`
    over `aggregate_events(actor.library, entry_id)`, then
    `void_entry_access_end`.
  - `ENTRY_END = BulkAction(name="entry.end", label="I no longer have
    them…", title=ActTitle(one="I no longer have this copy",
    many="I no longer have these {count} copies"), confirm_label="Save",
    subject=SUBJECT, color="blue", undo_rows=EventRows(LibraryEntry),
    fallback="games:list_library", scope=entry_scope,
    resolve=entry_resolution, run=end_one, inverse=end_back,
    preview=END_PREVIEW, choice=access_end_choice(ENTRY_WAYS),
    caution=already_ended)`.
- `games/bulk_actions.py` foot: import `bulk_entry_end`.
- `games/views/library_list.py:158`: `tray_actions(ENTRY_END.name,
  ENTRY_EDIT.name, REMOVE_ENTRY.name, …)`.
- Tests (`tests/test_bulk_entry_end.py`, `transaction=True`, fixtures
  modelled on `tests/test_bulk_entry_acts.py`, helpers `bulk_posts`):
  - confirmation offers the form, caution names already-ended count,
    Ended column shows the day / `–`;
  - press ends every held copy with way, day, note; event carries
    `source_metadata` bulk action;
  - default press (no way touched) states `unstated` and today;
  - an ended copy is refused with the command's sentence; an identical
    end answers already so; end before acquisition refused;
  - token posted twice acts once;
  - Undo voids each end; Undo pressed twice is already so; a copy
    resumed since, corrected since, or ended again since is refused
    with `changed_since` and keeps its state; a hand-voided copy is
    already so; a removed copy with a batch end is refused by the
    command's sentence.
  - `tests/test_library_list.py`: tray holds `entry.end` URL first.

## Task 5 — e2e

- `e2e/test_library_tab_e2e.py`: select two copies, press "I no longer
  have them…", Save, wait for the redirected list, assert both rows'
  Ended cells; press Undo on the toast, wait, assert held again.

## Gotchas

- `tests/test_bulk_act_imports.py`: no sibling act imports in
  `bulk_entry_end.py`; `bulk_access_end.py` and `bulk_endpoint_undo.py`
  must import cleanly first in a fresh interpreter.
- The guard raises `CommandRejected`; callers wrap in `answered`.
- `WayActStatement` normalises `when` in the command, not the form;
  compare via the command's outcome, not the raw value.
- Run `make ts`? No TS changes expected.
- Vale over new sentences and docstrings.
