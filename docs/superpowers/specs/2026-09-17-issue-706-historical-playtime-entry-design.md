# Record and restate historical playtime from Game detail

Issue: [#706](https://github.com/KucharczykL/timetracker/issues/706).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Aggregate: [#705](2026-09-17-issue-705-historical-playtime-aggregate-design.md).

## Purpose

A person records, corrects, removes and restores a historical playtime
record from the game it belongs to. The four commands exist (#705). This
issue adds the screens that dispatch them.

#709 (reads and statistics) and #1097 (the Playtime page) are built at the
same time in other worktrees. The shared surface is settled by
[the review of the three parallel specs](../../review/2026-09-17-historical-playtime-parallel-specs.md)
(decisions D1 to D6). This spec follows it.

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
in this header. #709 tells #710 so (review D6).

## Modules

| module | owner | contents |
|---|---|---|
| `games/reads/historical_playtime_records.py` | shared (review D1) | `RECORD_ORDER`, `library_records`, `readable_records`, `game_records` |
| `games/writes/historical_playtime.py` | #706 | `record_historical_playtime`, `restate_historical_playtime`, `remove_historical_playtime`, `restore_historical_playtime` |
| `games/views/historical_playtime_entry.py` | #706 | the four views, and the private resolvers `_library_record` and `_any_library_record` |

The shared module is the text in review D1, copied exactly. This issue adds
nothing to it. If #709 or #1097 merges first, this branch takes `main`'s
copy when it rebases.

`games/views/historical_playtime.py` is #1097's list view.
`games/reads/historical_playtime.py` and `game_historical_playtime` are
#709's; this issue does not use them.

Changed files:

- `games/forms.py`: `HoursMinutesField`, `HistoricalPlaytimeForm`.
- `games/urls.py`: four routes.
- `games/views/returns.py`: four names in `ORIGIN_AWARE`.
- `games/views/game.py`: the section, and an `add_url` argument on
  `_game_section`.
- `CLAUDE.md`: in the HistoricalPlaytime entry, the sentence "Nothing reads
  or writes it from a page yet." is replaced by one sentence saying that
  Game detail records, restates, removes and restores records. If a sibling
  merged first, keep `main`'s sentence and add this one after it (review
  D5). Nothing else in the entry changes.

Each change is an addition. If a sibling merges first, the conflict is
small and the second branch resolves it.

## Reads

The scope is `library_records(library)` (review D1, D2). It states five
conditions: the library on the record and on its `PlayerGame`, and the
marks of the record, the `PlayerGame` and the catalog game.
`HistoricalPlaytime.objects.alive()` is not enough, because it does not
read the catalog game's mark.

The section reads
`readable_records(library).filter(player_game__game=game).order_by(*RECORD_ORDER)`.
The join rows are prefetched.

Run names: the section and the form get the game's runs from
`numbered_for(library, [tracked.pk])` and match them to join rows in
Python. `live_ordinary_runs` is not used for names: it has no
`display_number`, so `display_name` raises `UnnumberedPlaythrough` for a
run with a blank name.

Every run of a live record is live and numbered.
`HistoricalPlaytimeRun.playthrough` is in `BLOCKING_REFERRERS`, so
`RemovePlaythrough` refuses a run that a live record names. The section
needs no fallback name.

The view resolvers are private to the view module, as `_library_session`
is in `games/views/session.py`:

- `_library_record(library, record_id)`: one record in
  `readable_records(library)`, for Edit;
- `_any_library_record(library, record_id)`: one record in
  `HistoricalPlaytime.objects.filter(library=library)`, removed or not, for
  Remove and Restore. A second Remove POST (from another tab, say) then
  gets `Unchanged` and redirects, not a 404.

Both answer `Http404` through `owned_or_404` for a missing row or another
library's row.

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
| `playthroughs` | `ModelMultipleChoiceField`, `CheckboxListWidget` | Shown choices are `numbered_for(library, [tracked.pk])`, each labelled `display_name`. The field validates against `Playthrough.objects.filter(library=library)`, so a posted removed run, bucket or other game's run reaches the command and gets its sentence. `SessionForm` sets `queryset` and `choices` apart in the same way. `required=False`: zero runs goes to the command, which refuses with `AT_LEAST_ONE_RUN`. Add checks `latest_ordinary_run`. Edit checks the record's runs. |
| `duration` | `HoursMinutesField` | Two number inputs, each with its own visible label: hours (0 to 99,999) and minutes (0 to 59). The maximum keeps `timedelta` from overflowing. Blank cleans to zero, which the command refuses with `AT_LEAST_A_SECOND`. |
| `when` | `HistoricalWhenField` | A `TemporalFormField` subclass. Default unknown. It catches the parse error and puts `when_sentence(error)` on the field, the command's sentence. A `clean_when` method cannot do this: the parent field's `clean` fails first. |
| `provenance` | `ChoiceField`, `RadioListWidget` | Add offers Estimated and Manually entered; Estimated is the default. Edit also offers Externally measured, but only if the record holds it. |
| `device` | `SearchSelectWidget` | Live devices of the library, plus the record's held device. No default: historical hours often come from another device. |
| `emulated` | checkbox | |
| `note` | textarea | Line endings are changed from CRLF to LF. Browsers post CRLF, and a note stored with LF would otherwise differ on every Edit. |

`statement()` returns a `HistoricalPlaytimeStatement`.

**Seconds are kept.** Records written by #1098 or by an importer can hold
seconds. On Edit, if both inputs are filled and the posted hours and
minutes equal the stored duration with its seconds removed, the statement
carries the stored duration. An unchanged submit then gets `Unchanged` from
the command. If either number changes, the duration is the posted whole
minutes. If both inputs are blank, the duration is zero and the command
refuses it, even for a stored duration under one minute.

**Choice widgets.** No radio-list or checkbox-list widget exists.
`apply_primitive_widget_classes` gives `INPUT_CLASS` to every widget that
is not a `Select` or a `Textarea`, and `RadioSelect` and
`CheckboxSelectMultiple` are neither. This issue adds `RadioListWidget` and
`CheckboxListWidget` to `games/forms.py`. Each renders a `<fieldset>` whose
`aria-labelledby` names the row's label through `field_label_id`, as the
temporal field does, and one `Radio()` or `Checkbox()` primitive per
choice. The label stays the group's one name source. Both are added to the exemption list in
`apply_primitive_widget_classes`. `HoursMinutesWidget` stamps its own
classes on its two inputs, with no `w-full`, and is exempt too.

**A held device is kept.** `RestateHistoricalPlaytime` keeps a removed
device only when the posted device equals the row's. The session form's
device field cannot post a removed device: its queryset is
`Device.objects.for_library(library)`, which is live devices only, and its
resolver uses the same scope, so the removed device is not shown as
selected. The form therefore adds the record's `device_id` to both the
field's queryset and the resolver's lookup, through
`Device.objects.filter(library=library, pk=record.device_id)`. The held
device is shown as selected, and a submit posts it again. Any other
removed device is still refused by the field.

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
- **Names.** The view module imports the write functions under aliases
  (`remove_record`, `restore_record`), because the views have the same
  names, as `session.py` does with `remove_session_row`.
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
- Every record is shown.
- Empty: "No historical playtime."

### Work for the second merge (review D4)

The list page is #1097's. Of #706 and #1097, the branch that merges second
adds both of these in its own pull request:

- the Actions column on the Historical list: Edit and Remove, through
  `action_url` with the origin;
- a "View all" link from this section to the list, narrowed to the game,
  through `_game_section`'s `view_all_url`.

If #1097 is on `main` when this branch rebases, this branch adds them. If
not, #1097 adds them.

## Testing

- `tests/test_historical_playtime_form.py`: hours and minutes clean to a
  `timedelta`; a blank duration reaches the command; stored seconds are
  kept when hours and minutes are unchanged, and dropped when either
  changes; Externally measured is offered only on a record that holds it;
  a `when` parse error shows `when_sentence`; unknown cleans to `None`;
  Add checks the latest run; the choices exclude the bucket and removed
  runs; a run with a blank name is labelled "Playthrough N"; Edit shows a
  held removed device as selected, and accepts it when it is posted again;
  another removed device is refused; minutes above 59, negative numbers
  and hours above 99,999 are refused; blank inputs on a record under one
  minute clean to zero; a CRLF note cleans to LF; each choice widget
  renders a fieldset named by the row's label and one primitive per
  choice.
- `tests/test_historical_playtime_views.py`
  (`django_db(transaction=True)`, because the views dispatch):
  - acceptance: record with two runs, restate to one run, remove, restore,
    all through the Game detail routes, checking the record row and its
    join rows after each step;
  - an unchanged Edit shows the toast and appends no event;
  - an Edit of a record that names a removed device keeps the device and
    appends no event;
  - refusals show the command's sentence: no runs, zero duration, a
    removed run, the bucket, a run of another game;
  - an Edit that posts the stored note with CRLF appends no event;
  - a second Remove POST redirects with no new event;
  - another library's record answers 404 on all four routes;
  - the Undo route in the removal toast restores the record;
  - redirects go to the origin, else to Game detail.
- `tests/test_game_detail_historical_playtime.py`: rows, order
  (`RECORD_ORDER`, with an unknown `when` last), count badge, empty state,
  run names, links with the origin. A removed catalog game is tested on
  `readable_records` directly, because Game detail answers 404 for one.
- `tests/test_historical_playtime_records.py`: the five scope conditions
  and `RECORD_ORDER`.
- Existing guards:
  - `tests/test_returns_classification.py`: the new names;
  - `tests/test_paths_return_200.py`: the Add and Edit pages;
  - `tests/test_view_authentication.py`: `world` gains `record_id`, because
    the test needs a sample value for every URL argument;
  - `tests/test_restore_routes.py`: a `ROUTES` row for
    `games:restore_historical_playtime`.
- Test runs are made with `tests/stated_runs.another_run`, which e2e can
  import too.
- `e2e/test_historical_playtime_entry_e2e.py`: from Game detail, Add with
  a `temporal-field` value and two runs; the row shows; Edit; Remove; Undo
  from the toast shows the row again. Each ORM read waits on the
  server-rendered section first.
- Full `make check` passes before the pull request.

## Coordination

- One comment on #706 links the review and states the header deviation.
- #709 comments on #710 about `PlaytimeSplit` in this header (review D6).
  This issue does not.
- No follow-up issue: the "View all" link is review D4 work, not a new
  issue.
- Found in the session form while writing this spec, and left out of this
  issue:
  - Editing a session whose device was removed clears the device.
    `_device_options` resolves live devices only, so the form posts no
    device.
  - `restate_session` compares a CRLF note with the stored note.
  Both go to one follow-up issue.
