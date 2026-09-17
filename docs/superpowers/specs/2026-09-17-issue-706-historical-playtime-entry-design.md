# Historical playtime entry

Issue: [#706](https://github.com/KucharczykL/timetracker/issues/706).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Shared surface: [review of the parallel specs](../../review/2026-09-17-historical-playtime-parallel-specs.md).

## Purpose

A person records, restates, removes and restores a historical playtime
record from the game it belongs to.

## Reads

`games/reads/historical_playtime_records.py` is the shared record scope.
`library_records` states five conditions: the library on the record and on
its `PlayerGame`, and the marks of the record, the `PlayerGame` and the
catalog game. `alive()` does not read the catalog game's mark.
`RECORD_ORDER` puts the newest `when` first and an unknown `when` last.

Run names come from `numbered_for`. A live record names only live runs,
because `RemovePlaythrough` refuses a run a live record names.

## Form

`HistoricalPlaytimeForm` parses types and narrows the offered provenances
and devices. The command makes every other decision, so its refusals show
the command's sentence, at the command's status.

- `playthroughs` shows the game's numbered runs as checkboxes. It accepts
  any run of the library, so the command refuses a removed run, the bucket
  and another game's run.
- `duration` is two number inputs: hours to 99,999 and minutes to 59. Blank
  is zero, which the command refuses.
- `when` shows `when_sentence` for a date the grammar refuses.
- `provenance` offers Estimated and Manually entered. Externally measured
  shows only on a record that holds it.
- `device` also accepts the record's own device, removed or not.

Add renders a fresh `submission` key and dispatches Record under it, so a
repeated submit replays instead of recording twice. An unchanged Edit
states nothing. The form keeps the stored seconds when
both duration inputs match the stored hours and minutes. It changes CRLF to
LF in the note.

The checkbox and radio lists and the duration inputs render in a
`<fieldset>` that the row's label names through `field_label_id`.

## Routes

| route | act |
|---|---|
| `add_historical_playtime` | GET form, POST `Record` |
| `edit_historical_playtime` | GET form, POST `Restate` |
| `remove_historical_playtime` | GET confirm, POST `Remove`, with Undo |
| `restore_historical_playtime` | POST `Restore` |

Remove and Restore resolve removed records too, so a second Remove is a
no-op. Every redirect goes to the origin, else to Game detail.

## Game detail

A section between Sessions and Playthroughs shows every live record: when,
duration, provenance, runs, device, Edit and Remove. It reads rows and run
names through `games/reads/historical_playtime_page.py`, as the Historical
list does. The header shows Add; with records, also a count badge and View all,
which opens the list narrowed to the game. The header shows no total: the page
headline states the game's playtime.

## Historical list

Each row of the Historical list has Edit and Remove, through
`record_actions`. Both links carry the list page as the origin. The
Actions column has priority 4, above every other column.

## Tests

- `tests/test_historical_playtime_records.py`: the scope and the order.
- `tests/test_historical_playtime_form.py`: parsing, choices, seconds,
  device, note.
- `tests/test_historical_playtime_views.py`: every act, every refusal,
  foreign rows.
- `tests/test_game_detail_historical_playtime.py`: the section.
- `tests/test_playtime_page.py`: the list's row actions.
- `e2e/test_historical_playtime_entry_e2e.py`: every act in a browser.
- `tests/historical_playtime_rows.py` writes rows by hand;
  `tests/historical_playtime_posts.py` builds a submit.
