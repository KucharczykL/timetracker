# End access to many copies at once

Issue #1355, a member of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
Contract for the act; #1345 declares the device act on the same module.

## Outcome

The Library tab's selection tray offers **I no longer have them…**. The
confirmation asks one way, one day and one note, and every selected copy
ends access with that statement. The batch's Undo voids each end it
stated, where that end is still the copy's latest end act or is already
taken back.

## Decisions

### Wording (approved by the user)

| Place | Words |
|---|---|
| Tray button (`label`) | `I no longer have them…` |
| Heading (`title`) | `I no longer have this copy` / `I no longer have these {count} copies` |
| Submit (`confirm_label`) | `Save` |
| Colour | `blue` (the submit; the tray draws it gray, as `entry.edit`) |
| Caution, one | `One of these copies has already ended, so it will be left as it is.` |
| Caution, many | `{count} of these copies have already ended, so they will be left as they are.` |
| Undo, not this batch's | `That copy was not ended by this batch, so it was left as it is.` |
| Undo, changed since | `That copy has changed since this batch, so it was left as it is.` |

The form has the per-copy page's fields, labels and order: **What
happened**, **When** (initial the library's calendar today), **Note**.
The done toast is the runner's tally sentence. The preview adds an
**Ended** column beside `ENTRY_PREVIEW`'s four: the standing end's day
through `present_temporal_value` (`Unknown` for an end on no day, as
the Library tab's Ended cell), `–` for a held copy, so the caution's rows are visible.

The tray lists `entry.end`, `entry.edit`, `entry.remove` in that order:
`tray_actions` follows the row menu, which offers "I no longer have it"
first.

### One shared module (wave ruling)

`games/bulk_access_end.py` holds what both bulk end acts use. It imports
no act module, by convention: `tests/test_bulk_act_imports.py` checks the
sibling rule only over act modules, but imports every `bulk_*.py` first
in a fresh interpreter, so it reads `CHOICE_FIELD` with a local import
inside `settle`.

- The statement is `WayActStatement`, which `EndEntryAccess` and
  `EndDeviceAccess` already take. `encode_access_end(statement)` writes
  JSON `{"when": canonical | null, "way", "note"}`;
  `decode_access_end(raw, ways)` refuses a way outside `ways`, an
  unreadable day and a note that is no text, through
  `statement_unreadable`. Null `when` is the unknown day.
- `BulkAccessEndForm(PrimitiveWidgetsMixin, forms.Form)`, built with
  `ways`, `presentation` and `today`. No `UnsetFieldsForm`: nothing keeps
  a row's value. `way` is a `ChoiceField` with the native select, as on
  `EntryEndForm`, its `choices` set in `__init__` from `ways`, required.
  Where `ways` holds `EndWay.UNSTATED` it leads, so the entry form shows
  `Not said`. Where it does not (`DEVICE_WAYS`), a blank first choice
  leads, and the required field refuses it: no way is stated unseen. `ended` is a
  `TemporalFormField`; `note` cleans through `normalised_note`.
- `access_end_choice(ways) -> BulkChoice[RowT]`. `offer` builds the form
  with `date_time_presentation_for_user(library.user)` and
  `calendar_today(library)`, or answers `AsksNothing` with no rows.
  `offer` has no request, so the When widget reads the user's
  presentation, not the request's locale the preview cells read; the
  purchase bulk Edit does the same.
  `settle` decodes a carried statement or validates the posted form.

The day is a form field, not a stamped hidden value as on the run acts:
the settled statement carries it, so a posted-twice confirmation replays
one payload under one key. A refused form is drawn again from defaults,
as for every act (`_reconfirmation` calls `offer` with no post).

### The Undo guard is one function

The run acts' private `_refuse_unless_this_batch_wrote_it` moves to
`games/bulk_endpoint_undo.py` as `refuse_unless_this_batch_wrote_it(
events, endpoint_events, *, batch_id, row_description, sentences)`.
`endpoint_events` is an `EndpointEvents`, which names the family, the
stated type and the voided type. The rule, over the row's events of the
family in append order:

1. The latest is a void: pass. The void command answers `Unchanged`, or
   a reposted chunk replays its key. A second Undo press, and a person
   who voided by hand since, read as already so.
2. The batch wrote no stated event: refuse, "not this batch's".
3. The latest is not the batch's last stated event: refuse, "changed
   since". This covers a resume, a correction and a later statement.

The run acts call it and drop their unstated pre-check: an unstated run
endpoint has a void as its latest event, so rule 1 is that pre-check.
Their answers do not move; `test_an_undo_pressed_twice_is_already_so`
pins it. `UndoSentences(not_stated, changed_since)` carries each act's
wording. The guard raises `CommandRejected`; the caller wraps it in
`answered` with its own subject, because the runner counts only
`CommandFailed` and `Http404` as a refused row. A run row whose marker
is set with no family event falls to rule 2 and is refused, as today; a
test pins it.

The guard reads `aggregate_events`, the row's whole history, rather than
`latest_end_act`: rule 2 needs the batch's own event too, and one
function serves runs and copies.

### Scope

The base is `entry_scope`; resolve is `entry_resolution`. No held-only
base. `EndEntryAccess` refuses an ended copy with its own sentence, an
identical restatement answers already so, and an end before the
acquisition is refused with its sentence; the log names each. The
caution counts rows whose `copy_end(row)` is not None (the marker, so an
end on an unknown day counts); None where none ended.

### Writes

- `end_entry_access` gains `source_metadata`; the runner's Undo reads
  the act's name from the batch's first event.
- New `void_entry_access_end(actor, entry, *, correlation_id,
  idempotency_key, source_metadata)` dispatches `VoidEntryAccessEnd`
  under `answered(SUBJECT)`.

### The act

`ENTRY_END = BulkAction(name="entry.end", …)` in
`games/bulk_entry_end.py`, `undo_rows=EventRows(LibraryEntry)`,
imported at the foot of `games/bulk_actions.py`. Its inverse reads the
row through `removed_entry`, runs the guard with
`ENTRY_ACCESS_END_EVENTS`, then voids. `VoidEntryAccessEnd` answers
`Unchanged` with no end before it refuses a removed copy.

### Known consequences

- The Undo of a batch end on an Owned copy whose game purchase was
  refunded later leaves the copy held: the refund wrote no end, because
  one stood. The one-click Undo does the same.

## Follow-up issues to file

None. #1345 declares the device act; #1209 is the general fix for a
selection holding rows an act will refuse.
