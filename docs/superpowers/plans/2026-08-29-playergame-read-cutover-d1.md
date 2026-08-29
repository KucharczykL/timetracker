# PGAME-08 D1: history from events

Child D of #678, first of two pull requests. Branch
`codex/playergame-read-cutover-d1`, onto `codex/playergame-read-cutover`.

D1 moves the last **read**: the detail page's History section stops reading
`GameStatusChange` and reads `library.playergame.status_changed` events. The
four `statuschange` routes, `GameStatusChangeForm` and the `pre_save` audit
signal retire with it. The table and its rows stay; #771 removes the storage.

D2 takes the mirror: `_mirror()`, `games/views/playergame_writes.py`, the
reverse half of `games/playergame_status.py`, the three catalog fallbacks,
`shelved` becoming settable, and the deletion of the parity suite. Splitting
there gives the irreversible step a bisect point of its own.

## Three behaviour changes

**History becomes library-scoped.** `_history_section` reads
`game.status_changes.all()`, which is not scoped. `view_game` scopes every
other section by hand, with a comment saying why:

> Scoped, not `game.sessions` and friends: tracked_by() admits a shared catalog
> game, and a shared game's reverse accessors reach every library that ever
> wrote against it.

History was left out. Reading the library's own event stream fixes it, because
a stream belongs to one library. Unreachable today — no path creates a shared
game — and it is the same latent hazard recorded on #950.

**The transition chain becomes the record.** A `GameStatusChange` row carries
`old_status` and `new_status`. An event carries only the new status, because
the projector sets a value rather than applying a delta; the backfill says so
where it ignores `old_status`: "a broken chain changes nothing". So the
previous status is the previous event's status, and the first change follows
`unplayed`.

Where a legacy row's `old_status` disagreed with the row before it, history
showed the disagreement and will now show the chain. It cannot show `-` for an
unknown previous status any more, because there is no such thing in a chain.
Both are strictly better records; neither is a regression to argue about.

**A game added at a status gains one entry.** `PLAYERGAME_CREATED` carries only
the catalog reference, and `PlayerGame.status` defaults to `unplayed`, so adding
a game as completed appends `created` and then `status_changed`. The audit
signal skipped a first save, so today that game's history is empty;
`tests/test_playergame_view_cutover.py:50` pins exactly that. From D1 the
history shows "Unplayed → Completed" at the add time.

**Show it.** It is what the stream records, and suppressing it means
special-casing the first `status_changed` behind a `created` — a rule that
would also hide a real change made a second after adding. The alternative, if
the noise is unwanted, is for `TrackGame` to carry the opening status in its
own event, which is a write-path change and belongs in D2 or later, not here.

## What time an entry shows

This is the one part that needs a rule rather than a translation.

Today the signal writes `timestamp=now()`, so a live entry shows when the change
was recorded, and a legacy row with a null timestamp renders "At some point
changed". Two event fields are candidates and each is wrong alone:

| Field | Live event | Backfilled, legacy timestamp | Backfilled, null timestamp |
|---|---|---|---|
| `recorded_at` | append time ✅ | the legacy timestamp ✅ | `game.created_at` ❌ invented |
| `effective_time` | unknown ❌ | that day, no time ❌ lossy | unknown ✅ |

Migration `0033` set `recorded_at=change.timestamp or game.created_at`, so
`recorded_at` reproduces today's display exactly except in the last column,
where it substitutes a time the original never claimed.

**The rule: show `recorded_at`, unless the event is backfilled and its effective
time is unknown, which renders "At some point changed".** Backfilled means
`source_metadata` carries a `status_change_id`; the backfill puts it there.
Live events also have an unknown effective time, so `is_unknown` alone does not
separate the two.

Nothing is lost and nothing is invented. #683 gives the command an effective
time of its own, and this rule collapses to reading it.

---

## Task 1: An entry per status event

**Files:**
- Create: `games/reads/playergame_history.py`
- Create: `games/reads/__init__.py`
- Test: `tests/test_playergame_history_read.py`

**Interfaces produced:** `StatusEntry`, `status_history(library, game)`.

A pure read, apart from the view, so the chain arithmetic and the time rule are
tested without rendering a page. `games/reads/` mirrors `games/writes/`, which
is the package this one is the counterpart of. If a reviewer objects to a
package for one module, `games/reads.py` is the same code.

- [ ] **Step 1: The entry**

A `NamedTuple`, so the view destructures it and mypy names the parts:

    class StatusEntry(NamedTuple):
        recorded_at: datetime | None
        previous: PlayerGameStatus
        current: PlayerGameStatus

`recorded_at` of `None` is the "At some point" case. The view formats; the read
decides.

- [ ] **Step 2: The query**

Select the library's own events for this game's tracked row:

    tracked = PlayerGame.objects.filter(library=library, game=game).first()
    if tracked is None:
        return []
    events = LibraryEvent.objects.filter(
        library=library,
        aggregate_id=tracked.pk,
        event_type=PLAYERGAME_STATUS_CHANGED.event_type,
    ).order_by("sequence")

`aggregate_id` is the `PlayerGame` pk — both `UUIDv7Field` defaults are opted
out for exactly this. Order by `sequence`, never `recorded_at`: the backfill
writes an older `recorded_at` than the events already on the stream, and the
chain is only a chain in sequence order.

- [ ] **Step 3: Walk the chain**

Carry the previous status forward, starting at `unplayed`. Read the new status
out of `payload["status"]`. Apply the time rule from above:
`event.effective_time.is_unknown and "status_change_id" in event.source_metadata`
gives `recorded_at=None`, everything else gives `event.recorded_at`.

Return newest first, matching `GameStatusChange.Meta.ordering = ["-timestamp"]`,
so the page order does not change. Reverse the walked list rather than sorting;
the chain is built oldest-first and its order is already right.

- [ ] **Step 4: Write the tests**

`tests/test_playergame_history_read.py`, one test per decision:

- A tracked game with no status event gives no entries.
- Three status commands give three entries, newest first, each `previous`
  equal to the one before it and the first `previous` `unplayed`.
- An event whose `source_metadata` names a `status_change_id` and whose
  effective time is unknown gives `recorded_at=None`.
- The same event with a known effective time gives its `recorded_at`.
- A live event, no `status_change_id`, unknown effective time, gives its
  `recorded_at`. **This is the test that fails if the rule is written as
  `is_unknown` alone.**
- Another library tracking the same game sees only its own entries.

Build events through `record_facts()` where a live event is wanted, and
`LibraryEvent.objects.create` is not available — use the append path, or the
backfill, so a test cannot record an event the writer could not.

- [ ] **Step 5: Run it**

    make test ARGS="tests/test_playergame_history_read.py" PYTEST_WORKERS=0

- [ ] **Step 6: Commit**

    git commit -m "Read the status history off the library's own stream"

---

## Task 2: The detail page renders the entries

**Files:**
- Modify: `games/views/game.py` (`_game_history`, `_history_section`)
- Test: `tests/test_rendered_pages.py`, `tests/test_playergame_history_read.py`

**Interfaces:** none produced.

- [ ] **Step 1: Repoint the section**

`_history_section` calls `status_history(library, game)` instead of
`game.status_changes.all()`, so it needs the library. `view_game` already holds
it. `count` is `len(entries)`; the list is short and already in memory, so no
second query.

- [ ] **Step 2: Repoint the renderer**

`_game_history` takes `list[StatusEntry]`. Per entry:

- `entry.recorded_at` is `None` → the prefix stays "At some point changed",
  otherwise `presentation.format(entry.recorded_at, "datetime")`, unchanged.
- Both `GameStatus` calls take a `PlayerGameStatus` directly. `player_status_for`
  and `get_old_status_display()` go: the entry already holds words, and the
  label comes off the enum.

- [ ] **Step 3: Drop the two links**

The Edit and Delete links named `edit_statuschange` and `delete_statuschange`
by row id. An entry has no row id, and Task 3 deletes the routes. Remove them
and the trailing "(", ", ", ")" furniture with them. `origin` becomes unused in
`_game_history`; drop the parameter rather than leaving it.

A history entry stops being editable here. #683 returns the ability to state a
backdated transition, as a command.

- [ ] **Step 4: Fix what this breaks**

**`e2e/test_custom_elements_e2e.py:25-70` is the one that matters**, and it is
the end-to-end proof that D1 works. It opens the status dropdown, picks
`completed`, waits for both the PATCH and the htmx refresh, and asserts one
history entry reading "Changed status from" / "Unplayed" / "Finished". That
whole path already goes through `record_facts()`, so the event exists; only the
**label changes**, because the entry now names `PlayerGameStatus.COMPLETED`
— "Completed", the word the user gave — where the five-letter mirror said
"Finished". Change that one string and nothing else. Its trailing
`assert game.status == "f"` still holds: D2 removes the mirror, not D1.

Fixing this test by weakening the assertion to the count alone would throw away
the only proof the read works from a browser. Keep both words.

`tests/test_rendered_pages.py:361-367` asserts `id="history-container"` and the
heading. Both survive. `tests/test_rendered_pages.py:486` is the statuschange
**list** page, not this section — Task 3 deletes it.

- [ ] **Step 5: Run the page tests**

    make test ARGS="tests/test_rendered_pages.py tests/test_playergame_history_read.py e2e/test_custom_elements_e2e.py" PYTEST_WORKERS=0

- [ ] **Step 6: Commit**

    git commit -m "Show the history the stream records"

---

## Task 3: The four routes and the form retire

**Files:**
- Delete: `games/views/statuschange.py`
- Modify: `games/urls.py`, `games/views/returns.py`, `games/forms.py`
- Test: several, listed below

**Interfaces:** none produced.

Nothing links to them. `add_statuschange` was already unreachable from the UI,
and Task 2 removed the only links to `edit` and `delete`. The list page was
reachable by typing the URL.

- [ ] **Step 1: Delete the views and the form**

`games/views/statuschange.py` entirely, `GameStatusChangeForm` from
`games/forms.py`, and the four `path()` entries plus the `statuschange` import
from `games/urls.py`.

- [ ] **Step 2: Unclassify the routes**

`games/views/returns.py` classifies all four: `list_statuschanges` at line 30,
`add_statuschange` at 52, `delete_statuschange` at 59, `edit_statuschange` at
66. All four go. The completeness guard fails on a route table and a
classification that disagree, in either direction, so this is not optional.

- [ ] **Step 3: Fix what this breaks**

Fifteen files, and the count is the reason this task is its own commit. They
fall into three kinds, and the kind decides the fix.

**A row in a table over every list page.** Delete the row. The property each
file tests is held by the six other pages in the same table, so nothing stops
being covered:

- `tests/test_table_width_policy.py:43` and `e2e/test_table_width_e2e.py:142`
- `e2e/test_responsive_table_e2e.py:146` (also builds a row at `:93`)
- `tests/test_action_origin_parity.py:75`
- `tests/test_library_reconciliation.py:243`
- `tests/test_date_time_rendering_paths.py:155` (also seeds at `:115`) — the
  statuschange list is the source of `"2022.23.09"`. Check before deleting that
  a date-only value survives in the dict; `games:list_playevents` renders three,
  so it does.

**A row in a table over every route or form.** Same treatment:

- `tests/test_view_authentication.py:46,60` — `statuschange_id`, and `:60`
  assigns it to `pk`, so read both before cutting
- `tests/test_session_playhistory_runtime_identity.py:26,27,86,216`
- `tests/test_library_page_isolation.py:158,164,182,231,232,261,262,280,303` —
  the widest single file
- `tests/test_deletion_confirmation.py:87,114`
- `tests/test_library_form_isolation.py:15,84,93,258,268`

**The deleted page is the subject.** Delete the test:

- `tests/test_rendered_pages.py:484-497` — `test_statuschange_list_and_delete`,
  which renders the list page and the delete confirmation. Both routes are gone.
- `tests/test_date_time_picker.py:31,278-301` — two cases
- `tests/test_datetime_field_binding.py:25,143,238`
- `tests/test_session_playhistory_identity.py:12,222-223` — asserts the form
  has no `uuid` field

Do not keep a test alive by pointing it at a different form.
`test_datetime_field_binding.py:238` exists because the status form is the one
with **no** zone rows; with `SessionForm` the only form left, the assertion has
no contrast and the test should go. `test_datetime_field_binding.py`'s module
docstring names both forms and needs the same edit.

`tests/test_playhistory_fk_uuid.py`, `test_session_playhistory_uuid_primary_key.py`,
`test_catalog_hierarchy_migration.py`, `test_external_reference_migration.py`,
`test_uuid_identity_audit.py`, `test_library_models.py`,
`test_session_timezones.py`, `test_playergame_backfill.py` and
`tests/test_filters.py:5537` all name the **model**, not a route or the form.
They stay: the table is still there, and #771 is the issue that takes them.

`grep -rn "statuschange\|GameStatusChangeForm" tests/ e2e/ --include=*.py`
before declaring the list complete.

- [ ] **Step 4: Run the gate's fast half**

    make check-fast

- [ ] **Step 5: Commit**

    git commit -m "Retire the four routes nothing reaches"

---

## Task 4: The audit signal stops writing

**Files:**
- Modify: `games/signals.py`
- Test: `tests/test_signals.py`, `tests/test_playergame_view_cutover.py`

**Interfaces:** none produced.

Since #677 the mirror is the only writer that changes a status, so with nothing
reading the table the signal records for no one. It also costs a `SELECT` per
`Game.save()`.

- [ ] **Step 1: Delete the receiver**

`game_status_changed` at `games/signals.py:135`, its `pre_save` registration,
and the `GameStatusChange` import if nothing else in the file uses it.

- [ ] **Step 2: Fix what this breaks**

Four tests, and each one wants a different fix:

- `tests/test_signals.py:88-100` — `test_status_in_a_fixture_is_not_an_audited
  _transition`. Its whole subject is the signal skipping a `raw` save. **Delete
  the test.** Keep the `Game.objects.get(pk=game.pk).status == "f"` line only if
  no other test covers loaddata writing a status; check before assuming.
- `tests/test_playergame_view_cutover.py:50-58` —
  `test_a_game_created_as_finished_records_no_status_change`. Also about the
  signal skipping a first save. **Delete it**, and note in the commit that the
  behaviour it pinned is the third change above.
- `:74-89` — `test_editing_a_games_status_records_the_event_and_the_audit_row`.
  A real cutover test. **Drop the last assertion and the `_and_the_audit_row`
  from its name**; the event and projection assertions above it stay.
- `:383-390` — the failed-reset test. **Drop the two-line comment and the
  `GameStatusChange.objects.count() == 0` assertion.** The catalog and
  projection assertions above it are the point.

- [ ] **Step 3: Confirm the table is now write-only-by-history**

    grep -rn "GameStatusChange" --include=*.py games/ | grep -v migrations

Expected survivors, all legitimate: `games/models.py` (the model and its
queryset), `games/backfill/playergame.py` (reads legacy rows),
`games/events/playergame.py` (a comment), `anonymize_sample`,
`load_sample_data`, `audit_library_ownership`, `identity_audit`. **Nothing in
`games/views/`, `games/forms.py` or `games/signals.py`** — the run before D1
lists all three, and `games/views/statuschange.py` besides.

- [ ] **Step 4: Commit**

    git commit -m "Stop recording an audit nothing reads"

---

## Task 5: Documentation and the gate

**Files:**
- Modify: `docs/STATUSES.md`, `docs/superpowers/specs/2026-08-28-issue-678-playergame-read-cutover-design.md`

**Interfaces:** none produced.

- [ ] **Step 1: `docs/STATUSES.md`**

C left one line forward-dated:

> `GameStatusChange` still records each change, but the events are the record
> from #678 D onwards; where that audit table is stored is #771

It is now true, so say it in the present: the events are the record, the table
keeps its rows until #771, and nothing reads or writes it.

- [ ] **Step 2: The spec**

The History section describes D as one change. Say that D1 did the reads and the
retirement and D2 takes the mirror, and record the two behaviour changes above —
D2 reads this document.

- [ ] **Step 3: Lint the prose**

    make vale >/tmp/vale.log 2>&1 && echo CLEAN || cat /tmp/vale.log

- [ ] **Step 4: Run the gate**

    make check >/tmp/check.log 2>&1 && echo CLEAN || tail -80 /tmp/check.log

The full aggregate, `e2e/` included, about six and a half minutes serially. Run
it in the background and poll. Two wall-clock failures are filed as #949 and are
unrelated: `tests/test_library_page_isolation.py::test_navbar_playtime_is_scoped_to_the_authenticated_library`
and `e2e/test_quick_filter_e2e.py::test_date_dropdown_facet_preset_flow`. Both
passed on C's run. Confirm any failure is one of those by stashing and
re-running it; never assume.

- [ ] **Step 5: Commit**

    git commit -m "Say that the events are the record"

---

## After the tasks

1. **Docs sweep.** Every comment and docstring D1 adds, cut to seven words.
   Plead an exception only where a plausible edit breaks quietly, and list the
   pleas in the pull request. Delete this plan document in the same commit; the
   #678 spec stays, because D2 reads it.
2. **Open the pull request** against `codex/playergame-read-cutover`. Lead with
   the time rule, since it is the only part a reviewer cannot derive from the
   diff.
3. **File the issue and close it**, as C's #951 was, unless asked otherwise.
4. **Then plan D2.**

## What D1 does not touch

- `_mirror()`, `games/views/playergame_writes.py`, the reverse half of
  `games/playergame_status.py`, `SETTABLE_PLAYER_STATUSES`. **D2.**
- The three catalog fallbacks that read `Game.status` when no row exists:
  `games/forms.py:834`, `games/views/game.py:276`,
  `games/views/session.py:200`. They are correct while the mirror lives. **D2.**
- `tests/test_playergame_read_parity.py`. **D2** deletes it.
- The `GameStatusChange` table and its rows. **#771.**
- Stating a backdated transition. **#683.**
