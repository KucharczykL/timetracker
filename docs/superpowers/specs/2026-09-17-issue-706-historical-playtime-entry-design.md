# Record and restate historical playtime from Game detail

Issue: [#706](https://github.com/KucharczykL/timetracker/issues/706).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Aggregate: [#705](2026-09-17-issue-705-historical-playtime-aggregate-design.md).

## Purpose

A person records, corrects, removes and restores a historical playtime
record from the game it belongs to. The four commands exist (#705). This
issue adds the screens that dispatch them.

#709 (reads and statistics) and #1097 (the Playtime page) are built at the
same time in other worktrees. This issue does not create a module either of
them will want, and it changes shared files only by small additions.

## Boundary

In scope:

- a "Historical playtime" section on Game detail;
- one form page for Add and Edit;
- Remove through the confirm page, with Undo.

Out of scope:

- the list page and its filter (#1097);
- any playtime sum or statistic (#709);
- the split presentation (#710);
- reclassification of sessions (#1098).

### Deviation: no total in the section header

The issue says the section header shows the plain total until #710. A
total is a playtime read, and playtime reads are #709's module
(`games/reads/historical_playtime.py`, `game_historical_playtime`). #709 is
not merged when this issue is built. So the header shows a count badge,
as every other section on Game detail does. #710 puts the `PlaytimeSplit`
in this header; its issue is told so.

## Modules

New modules. Neither sibling issue uses these names.

| module | contents |
|---|---|
| `games/reads/historical_playtime_records.py` | `game_records(library, game)`, `library_record(library, record_id)`, `any_library_record(library, record_id)` |
| `games/writes/historical_playtime.py` | `record_historical_playtime`, `restate_historical_playtime`, `remove_historical_playtime`, `restore_historical_playtime` |
| `games/views/historical_playtime_entry.py` | `add_historical_playtime`, `edit_historical_playtime`, `remove_historical_playtime`, `restore_historical_playtime` |

The view module is not `historical_playtime.py`: #1097's list view will
probably want that name.

Changed files:

- `games/forms.py`: `HoursMinutesField`, `HistoricalPlaytimeForm`.
- `games/urls.py`: four routes.
- `games/views/returns.py`: four names in `ORIGIN_AWARE`.
- `games/views/game.py`: the section, and an `add_url` argument on
  `_game_section`.
- `CLAUDE.md`: the HistoricalPlaytime entry says that Game detail writes
  records.

Each change is an addition. If a sibling merges first, the conflict is
small and the second branch resolves it.

## Reads

`game_records(library, game)` returns the live records of the library's
tracked row for the game:

- scope: `HistoricalPlaytime.objects.alive()`, `library=library`,
  `player_game__game=game`;
- `select_related("device")`;
- the join rows prefetched, with each run numbered by `numbered_for`, so
  `display_name` works without a fallback;
- order: `when_lower` descending with nulls last, then `created_at`
  descending, then `id`.

A record naming a removed run is still live, so it is listed. The removed
run has no number; its name is "Removed playthrough".

`library_record` resolves one live record in the library for Edit and
Remove. `any_library_record` resolves one record, removed or not, for
Restore. Both answer `Http404` through `owned_or_404` for a missing row or
another library's row.

## Writes

Each function dispatches one command under `answered("historical
playtime")`, with a fresh idempotency key and the caller's correlation id,
as `games/writes/playersession.py` does. `record_historical_playtime`
returns the new record's id.

## Form

`HistoricalPlaytimeForm(library, game, presentation, record=None)` is a
plain `Form`. It parses types only. Every domain rule is the command's, so
a refusal shows the command's sentence.

| field | control | notes |
|---|---|---|
| `playthroughs` | `ModelMultipleChoiceField`, checkboxes | Choices are `live_ordinary_runs(library, tracked)`, each labelled `display_name`. `required=False`: zero runs goes to the command, which refuses with `AT_LEAST_ONE_RUN`. Add checks `latest_ordinary_run`. Edit checks the record's runs. |
| `duration` | `HoursMinutesField` | Two number inputs: hours (0 or more, no maximum) and minutes (0 to 59). Blank cleans to zero, which the command refuses with `AT_LEAST_A_SECOND`. |
| `when` | `TemporalFormField` | Default unknown. A parse error is put on the field as `when_sentence(error)`, the command's sentence. |
| `provenance` | radio buttons | Add offers Estimated and Manually entered; Estimated is the default. Edit also offers Externally measured, but only if the record holds it. |
| `device` | `SearchSelectWidget` | The session form's resolver. No default: historical hours often come from another device. |
| `emulated` | checkbox | |
| `note` | textarea | |

`statement()` returns a `HistoricalPlaytimeStatement`.

**Seconds are kept.** Records written by #1098 or by an importer can hold
seconds. On Edit, if the posted hours and minutes equal the stored
duration with its seconds removed, the statement carries the stored
duration. An unchanged submit then gets `Unchanged` from the command. If
either number changes, the duration is the posted whole minutes.

`HoursMinutesField` is a `MultiValueField` with a `MultiWidget`. It does
not use Alpine: CLAUDE.md allows no new `x-mask` input.

## Views and routes

| route | name | method |
|---|---|---|
| `game/<uuidv7:game_id>/historical-playtime/add` | `add_historical_playtime` | GET, POST |
| `historical-playtime/<uuidv7:record_id>/edit` | `edit_historical_playtime` | GET, POST |
| `historical-playtime/<uuidv7:record_id>/remove` | `remove_historical_playtime` | GET confirms, POST removes |
| `historical-playtime/<uuidv7:record_id>/restore` | `restore_historical_playtime` | POST |

All four are in `ORIGIN_AWARE`. Every redirect is
`return_url(request, fallback="games:view_game", fallback_args=[game.pk,
game.url_slug])`.

- **Add.** The game is resolved with
  `owned_or_404(Game.objects.tracked_by(library), …)`. A valid POST calls
  `record_historical_playtime`, then shows "Historical playtime recorded."
  and redirects.
- **Edit.** A valid POST calls `restate_historical_playtime`. A change and
  `Unchanged` both show "Historical playtime saved." and redirect.
  `Unchanged` appends no event.
- **Refusal.** `CommandFailed` becomes `messages.error(failure.message)`,
  and the form is shown again with the posted values, as the session form
  does. A defect answer from `answered()` takes the same path.
- **Remove.** `confirm_and_apply` with the message "Remove this historical
  playtime record of <game>?" and
  `UndoOffer("Historical playtime removed.",
  "games:restore_historical_playtime", [record.pk])`. A refusal shows on
  the confirm page.
- **Restore.** `restore_and_return(restored="Historical playtime
  restored.")`. A refusal is an error toast.
- **Scripts.** Widgets render to text, so their `Media` does not reach the
  page. The form view passes
  `scripts=ModuleScript("dist/elements/temporal-field.js")` and
  `ModuleScript("dist/elements/search-select.js")`.

## Game detail section

`_historical_playtime_section` is placed between the Sessions and the
Playthroughs sections.

- Header: "Historical playtime", a count badge, an Add button
  (`action_url("games:add_historical_playtime", game.pk, origin=origin)`).
  `_game_section` gets an optional `add_url`. The Add button shows when
  the section is empty too.
- Columns: When (`TemporalText`; an unknown when shows "Unknown"),
  Duration (`Duration`), Provenance (`Pill` with the choice label),
  Playthroughs (display names, separated by commas), Device (name, or "No
  device"), Actions (Edit and Remove in a `ButtonGroup`, with the origin).
- Every record is shown. There is no "View all" link, because the list
  page is #1097's.
- Empty: "No historical playtime."

## Testing

- `tests/test_historical_playtime_form.py`: hours and minutes clean to a
  `timedelta`; a blank duration reaches the command; stored seconds are
  kept when hours and minutes are unchanged, and dropped when either
  changes; Externally measured is offered only on a record that holds it;
  a `when` parse error shows `when_sentence`; unknown cleans to `None`;
  Add checks the latest run; the choices exclude the bucket and removed
  runs.
- `tests/test_historical_playtime_views.py`
  (`django_db(transaction=True)`, because the views dispatch):
  - acceptance: record with two runs, restate to one run, remove, restore,
    all through the Game detail routes, checking the record row and its
    join rows after each step;
  - an unchanged Edit shows the toast and appends no event;
  - refusals show the command's sentence: no runs, zero duration, a
    removed run;
  - another library's record answers 404 on all four routes;
  - the Undo route in the removal toast restores the record;
  - redirects go to the origin, else to Game detail.
- `tests/test_game_detail_historical_playtime.py`: rows, order, count
  badge, empty state, run names, a removed run's name, links with the
  origin.
- Existing guards: `tests/test_returns_classification.py` (new names) and
  `tests/test_paths_return_200.py` (the Add and Edit pages).
- `e2e/test_historical_playtime_entry_e2e.py`: from Game detail, Add with
  a `temporal-field` value and two runs; the row shows; Edit; Remove; Undo
  from the toast shows the row again. Each ORM read waits on the
  server-rendered section first.
- Full `make check` passes before the pull request.

## Follow-ups

- #710: put `PlaytimeSplit` in this section's header. Comment on #710.
- #1097 or #710: a "View all" link from this section to the list, narrowed
  to the game. Comment on #1097.
- Comment on #706 and #601: the header deviation above.
