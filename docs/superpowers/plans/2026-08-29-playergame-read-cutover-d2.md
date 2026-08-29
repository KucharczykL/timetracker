# PGAME-08 D2: the mirror goes

Child D of #678, second of two pull requests. Branch
`codex/playergame-read-cutover-d2`, onto `codex/playergame-read-cutover`.

D1 moved the last read. D2 removes the **write** that kept the catalog columns
agreeing with it: `_mirror()`, the refusal that existed only to protect the
mirror, the reverse half of the status map, the three places that read
`Game.status` where no projection row exists, and the parity suite that guarded
the switch. `Game.status` and `Game.mastered` stay as columns; #770 drops them.

After D2 the projection is the only statement of a library's status and mastery.
The catalog columns hold whatever the baseline backfill read out of them, and
nothing keeps them current.

## Four behaviour changes

**Shelved becomes settable.** Six words, six options. `Shelved` had no letter, so
`_mirror()` would have raised after the event committed, and `record_facts()`
refused it before dispatch to stop exactly that. The refusal and the five-option
list go together with the mirror.

Shelved is "stopped, and might be picked up again". It is not one of
`DONE_STATUSES`, so a shelved game stays in the backlog and counts as unfinished
— which is what the word means. No statistic changes definition; a game can
simply now be given a word that says why it is sitting there.

**The catalog columns freeze.** Two commits do this in two halves, and the
halves are visible separately:

- Task 1 stops the mirror, so an **edit** and a **status PATCH** no longer touch
  `Game.status`. An add still writes it, because `GameForm.save()` writes it
  directly on the insert.
- Task 2 stops that write, so an **add** no longer sets it either. A game added
  as Completed leaves `Game.status` at its `unplayed` default.

**A game with no projection row reads as unplayed, not as its letter.** Two
places ask the catalog what the library thinks when the projection has no row.
The answer stops being a fact and becomes a leftover, so both read the
projection default instead:

- `GameForm.__init__` seeds the status select. With no row it offered the
  catalog letter; it now offers `Unplayed`, which is what tracking the game
  would create and therefore what saving the form will record.
- `_record_played` answers a session the player saved with "Set game status to
  Played if Unplayed" ticked. With no row and a catalog letter of `p` it
  recorded nothing; it now records `Played`, which tracks the game on the way
  through. This is the heal the two sibling write paths already get. An unticked
  box still records nothing, as before.

`add_game`'s rollback is the third catalog line the spec counts, and it is a
write: it reset the columns the form had written. With the form no longer
writing them there is nothing to reset.

**Nothing else.** Every read moved in A, B, C and D1. The catalog columns have
had no reader outside these three since D1.

## Two judgment calls, for review

**`games/views/playergame_writes.py` stays.** The spec's D2 bullet lists it, and
`games/writes/playergame.py` says "#678 deletes both". Both sentences were
written when the module's reason for existing was the mirror. It is not:
`record_facts()` still dispatches, still heals an untracked game, and still
translates four command failures into an answer, and the view half still turns
that answer into a toast. Deleting them would copy a `try/except
PlayerGameWriteFailed` into five views.

What D2 removes there is the promise, not the module. Both docstrings are
rewritten to say what the code does now.

**`GameForm.save()` stops writing the catalog too.** The spec names three
catalog *reads*; it does not name this write or the rollback that answers it.
Leaving them means the columns are current for an added game and stale for every
game after — a worse record than plainly stale, and one that reads as if
something still maintains them. Both go.

## Order

Each commit leaves a green tree, which fixes the order. `legacy_status_for` has
three callers — the mirror, `GameForm.save()`, and the parity suite — so it
cannot go until all three have. That puts the column writes before the status
map, and the map before the reads that no longer need `player_status_for`.

## Task 1: take the mirror out

- [ ] **Step 1: `games/writes/playergame.py`**

Delete `_mirror()`, its call at the end of `record_facts()`, and the
`PLAYER_STATUS_TO_LEGACY_STATUS` / `legacy_status_for` imports. Delete the
refusal block in `record_facts()` — the `if status not in
PLAYER_STATUS_TO_LEGACY_STATUS` raise — and keep the `PlayerGameStatus(status)`
coercion above it, which is what turns a form's `str` into the member the
command reads `.value` off.

Rewrite the module docstring. It says "State a fact, then mirror the row" and
promises its own deletion; it states a fact and translates a failure.

`_mirror()` carries a comment saying "A field save, so the audit signal still
fires." D1 deleted that signal and missed this line. It leaves with the
function.

- [ ] **Step 2: `tests/test_playergame_write_path.py`**

The module docstring says "State the fact, then mirror the row." Rewrite.

Delete `test_the_mirror_writes_the_fold_and_not_the_request` — its whole subject
is gone. Drop the catalog assertion from
`test_a_status_reaches_the_event_the_projection_and_the_catalog` (and rename it:
the event and the projection) and from `test_an_untracked_game_heals_and_records`.

Add the test that bites, in their place: record `Completed` on a tracked game
whose catalog column says `u`, and assert the row says completed **and**
`Game.status` is still `u`. Restoring the `_mirror()` call must fail it.

- [ ] **Step 3: `tests/test_playergame_status_word_setters.py`**

`test_the_form_posts_a_word` asserts `(game.status, game.mastered) == ("f",
True)` with the comment "The mirror keeps the catalog current for the surfaces A
leaves." That assertion **still passes after this task**, because `add_game`
reaches it through `GameForm.save()`, not through the mirror. Leave it; task 2
takes it, where it is the point.

`test_shelved_is_refused_before_anything_is_recorded` goes. Task 3 replaces it
with the opposite.

- [ ] **Step 4: `e2e/test_custom_elements_e2e.py`**

`test_game_status_selector_opens_and_patches` ends with `assert game.status ==
"f"` after the PATCH. That is the mirror. Delete the two lines; the test already
asserts the History entry the write produced, which is the server-rendered
evidence the write landed.

- [ ] **Step 5: Verify**

    make check-fast >/tmp/check.log 2>&1 && echo CLEAN || tail -60 /tmp/check.log
    make test-e2e ARGS="-k custom_elements" >/tmp/e2e.log 2>&1 && echo CLEAN || tail -40 /tmp/e2e.log

`check-fast` skips `e2e/`, and step 4 edits an e2e file.

- [ ] **Step 6: Commit**

    git commit -m "Stop copying the row onto the catalog"

## Task 2: stop writing the columns

- [ ] **Step 1: `games/forms.py`**

Delete the `if game._state.adding:` block in `GameForm.save()` that sets
`game.status` and `game.mastered`, and the `legacy_status_for` import. The
comment above the two declared fields — "Plain fields, so form.save() writes
neither column" — becomes true of every save rather than of edits alone.

- [ ] **Step 2: `games/views/game.py`**

In `add_game`, delete the `Game.objects.filter(pk=game.pk).update(...)` rollback
and its comment. The form no longer writes those columns, so a failed
`record_facts()` leaves nothing to undo. Keep the redirect — re-rendering would
still invite a second game — and keep that surviving reason as the comment.

- [ ] **Step 3: `tests/test_playergame_status_word_setters.py`**

`test_the_form_posts_a_word` now asserts the opposite: the row says completed
and mastered, and `Game.status` is still `u`. That is this task's bite test;
restoring either write fails it.

- [ ] **Step 4: Verify**

Grep first, and expect nothing outside `games/backfill/`:

    grep -rn "game.status = \|status=Game.Status\|\.mastered = " --include=*.py games/ common/

    make check-fast >/tmp/check.log 2>&1 && echo CLEAN || tail -60 /tmp/check.log

- [ ] **Step 5: Commit**

    git commit -m "Leave the columns to the migration that drops them"

## Task 3: let a game be shelved

- [ ] **Step 1: `tests/test_playergame_read_parity.py`**

Delete it whole, first, because it is the last caller of `legacy_status_for`.
Its own docstring says so: "Created by #678 A and deleted by #678 D. Its whole
purpose is to guard the switch, so it does not outlive it."

- [ ] **Step 2: `games/playergame_status.py`**

Delete the reverse half: `PLAYER_STATUS_TO_LEGACY_STATUS`, `legacy_status_for`,
`UnmappedPlayerStatus`, `SETTABLE_PLAYER_STATUSES` and the `LabeledStatus` alias
that exists for it. Keep `LEGACY_STATUS_TO_PLAYER_STATUS`, `player_status_for`,
`UnmappedLegacyStatus` and `LegacyStatus`: the baseline backfill reads catalog
letters, and so do the autouse fixtures in `tests/conftest.py` and
`e2e/conftest.py`.

Rewrite the module docstring — one direction now, letter to word — and the
comment on the surviving map, which says `SHELVED` is absent. It is absent
because no letter states it, which is a fact about the letters, not a
restriction any more.

- [ ] **Step 3: the three call sites take `PlayerGameStatus.choices`**

`games/views/game.py` (two `GameStatusSelector` calls, the list row and the
detail meta row) and `games/forms.py` (`status = forms.ChoiceField(choices=…)`).
`TextChoices.choices` is already `list[tuple[str, str]]`, so no constant
replaces the deleted one; the enum is the list.

- [ ] **Step 4: `games/api.py`**

`GameStatusUpdate` carries a comment saying `SHELVED` "reaches record_facts(),
which answers 409 while the mirror still needs a letter". Delete that sentence.
The one before it — the enum, so Ninja refuses unknown members — is still true
and still worth saying.

- [ ] **Step 5: the tests**

`tests/test_playergame_status_map.py` loses the two reverse-direction cases
(`legacy_status_for` round trip, `UnmappedPlayerStatus` on `SHELVED`). Keep the
forward ones.

`tests/test_playergame_status_word_setters.py`:
`test_only_the_words_a_letter_holds_are_settable` becomes every word is
settable, listing all six in `PlayerGameStatus` order, and gets a name that says
so. Add the bite test: PATCH `shelved` through `/api/games/{id}/status` and
assert the row says shelved.

`tests/test_game_status_component.py` imports `SETTABLE_PLAYER_STATUSES`. Point
it at `PlayerGameStatus.choices`; while there, assert the selector renders six
options, so a shortened list fails here as well as in the setter test.

- [ ] **Step 6: Verify and commit**

    make check-fast >/tmp/check.log 2>&1 && echo CLEAN || tail -60 /tmp/check.log
    git commit -m "Offer the sixth word the projection already holds"

## Task 4: stop asking the catalog what the library thinks

- [ ] **Step 1: `games/forms.py`**

In `GameForm.__init__`, delete the `else` branch that seeds `status` and
`mastered` from `self.instance`. With no projection row the form offers the
select's first option, `Unplayed`, which is the status `TrackGame` creates and
therefore the status saving the form records. Drop the `player_status_for`
import.

- [ ] **Step 2: `games/views/session.py`**

In `_record_played`, drop the catalog arm:

    if tracked is not None and tracked.status != PlayerGameStatus.UNPLAYED:
        return

Drop the `player_status_for` import. Rewrite the comment: a missing row states
nothing, and `record_facts()` tracks the game on the way through.

- [ ] **Step 3: the tests**

`tests/test_playergame_game_views.py::test_the_edit_form_falls_back_to_the_catalog_with_no_row`
asserts the branch just deleted. Turn it round: with no row and a catalog letter
of `f`, the form offers `Unplayed` and an unchecked mastery. Rename it to say
that.

Add the session case: an untracked game whose catalog column says `p`, a POST to
`add_session` with `mark_as_played` ticked, and the assertion that the library
now tracks it at `Played`. Before this task it recorded nothing.

No test covers the unticked box on either side of this change. Add that one
too, since the task widens what a ticked box does: an unticked box records
nothing and tracks nothing.

- [ ] **Step 4: Verify and commit**

    make check-fast >/tmp/check.log 2>&1 && echo CLEAN || tail -60 /tmp/check.log
    git commit -m "Read no fact out of a column nothing maintains"

## Task 5: read back what the parity suite covered

- [ ] **Step 1: the hole check**

The suite asserted id sets over the status and mastered filters, every
`GAME_SORTS` entry, and every `stats_links` builder. Confirm each of those has a
test of its own now, and that nothing else says "parity" about this switch:

    grep -rn "parity" --include=*.py tests/ e2e/

A surface the suite was the only cover for is a hole it was hiding. It gets a
test here, not a note.

- [ ] **Step 2: the dead audit seed**

`e2e/test_table_width_e2e.py`'s `populated` fixture creates a `GameStatusChange`.
No page under test renders one — the six list pages never did, and D1 took the
route that would have. Delete the line and the import, so #771 does not have to.

- [ ] **Step 3: Verify and commit**

    make check-fast >/tmp/check.log 2>&1 && echo CLEAN || tail -60 /tmp/check.log
    make test-e2e ARGS="-k table_width" >/tmp/e2e.log 2>&1 && echo CLEAN || tail -40 /tmp/e2e.log
    git commit -m "Cover what the retired suite was covering"

## Task 6: say what is true now

- [ ] **Step 1: `CLAUDE.md`**

The command bullet ends "The catalog columns are a mirror of the projection
until #678 moves the reads." They are not, from this pull request. Say that
nothing maintains them and that #770 drops them, and keep the rule itself — a
fact is stated as a command — which is now the only way to state one.

- [ ] **Step 2: `docs/STATUSES.md`**

One paragraph calls `Game.status` a "five-letter mirror… kept current by
`games/writes/playergame.py`" and says `shelved` cannot be set until the mirror
goes. Both halves are now wrong. The six-word table needs nothing: it already
describes Shelved correctly, which is why the word was worth keeping unreachable
rather than deleting.

- [ ] **Step 3: the spec**

`docs/superpowers/specs/2026-08-28-issue-678-playergame-read-cutover-design.md`.
Record the two judgment calls above and that D2 landed. #770 reads this document
next.

- [ ] **Step 4: Lint the prose**

    make vale >/tmp/vale.log 2>&1 && echo CLEAN || cat /tmp/vale.log

- [ ] **Step 5: Run the gate**

    make check >/tmp/check.log 2>&1 && echo CLEAN || tail -80 /tmp/check.log

The full aggregate, `e2e/` included. Two wall-clock failures are filed as #949
and are unrelated: `test_navbar_playtime_is_scoped_to_the_authenticated_library`
and `test_date_dropdown_facet_preset_flow`. Confirm any failure is one of those
by stashing and re-running it; never assume.

- [ ] **Step 6: Commit**

    git commit -m "Say that nothing maintains the columns"

## After the tasks

1. **Docs sweep.** Every comment and docstring D2 adds, cut to seven words.
   Plead an exception only where a plausible edit breaks quietly, and list the
   pleas in the pull request. Delete this plan document in the same commit.
2. **Open the pull request** against `codex/playergame-read-cutover`. Lead with
   the two judgment calls, since they are the parts a reviewer cannot derive
   from the diff.
3. **File the issue and close it**, as D1's #953 was.
4. **Then merge the integration branch**, which closes #678, and decide whether
   #770 follows straight away.

## What D2 does not touch

- The `Game.status` and `Game.mastered` columns themselves. **#770.**
- The `GameStatusChange` table and its rows, and the baseline backfill that
  reads them. **#771.**
- `player_status_for` and the forward map. The backfill and the two conftest
  fixtures read catalog letters, and will until #770.
- Stating a backdated transition. **#683.**
- `TrackGame` carrying an opening status, which would spare a game added at a
  status its "Unplayed →" first entry. A write-path change, not a mirror
  removal.
