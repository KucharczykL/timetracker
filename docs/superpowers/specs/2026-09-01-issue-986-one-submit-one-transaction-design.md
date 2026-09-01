# One submit, one transaction

Issue [#986](https://github.com/KucharczykL/timetracker/issues/986). Edit Game
writes the Game row, then the catalog graph, then the flat columns, in three
transactions with two gaps between them. A refusal in the second leaves the
first standing. This spec closes the gaps, gives the form two refusals it
cannot state today, and turns the constraint that catches the rest into a
sentence instead of a 500.

Nothing here changes what a person sees when a submit succeeds. Every change is
about what happens when one does not.

## Why it moves

#969 gave the Game form the whole catalog graph. The form now states a Game's
name, its Editions, and each Edition's Releases in one POST. The write path
underneath it still belongs to the world before that, where a Game saved on its
own and the graph did not exist.

`edit_game` reads:

```text
form.is_valid()
and graph.is_valid()
and _saved_game_or_form_error(form) is not None
and graph.save()
and record_facts_for_request(...)
```

Each `and` is a commit. `_saved_game_or_form_error` calls
`save_legacy_game_form`, which is `@transaction.atomic`; `graph.save()` calls
`write_and_mirror`, which is another. So a submit that renames a Game and
removes an Edition can rename the Game and keep the Edition, and answer with an
error about the Edition. The person sees a form that refused, and a Game that
changed anyway.

Four defects follow from that shape, and one does not:

1. **The Game row commits before the graph is written.** A refused graph leaves
   the rename standing.
2. **A removal is written after the row that wants its name.** The form lets a
   person bin an Edition and add another with the same name in one submit. The
   adds run first, and `add_edition` matches on name among the *live* Editions
   — so it hands back the very row the submit is about to remove. The Edition
   the person asked for is never created, its Releases are written onto the
   departing row, and `_remove_editions` then takes all of it. Nothing refuses.
   The same holds for a Release, where `add_release` matches on platform and
   date. When the re-added row is the marked one it is worse in a different
   way: it takes the default mark, and the removal it collided with is refused
   with `DEFAULT_EDITION_HELD` — a sentence about a row the person did not
   touch.
3. **A unique constraint reaches the person as a 500.** Every guard against one
   is a SELECT before a write, so two submits can both pass it and one still
   lose.
4. **Two things create the graph.** `save_private_game` guarantees a default
   Edition and Release; then `CatalogGraphForm` writes the set the person
   stated. On Add Game the form has to claim rows it did not make, through
   `adopt()`.

Defect 4 is the one that is not a symptom. It is why the order in defect 1
exists: the Game had to save first so the graph the coordinator diffs against
would be there. Take the second creator away and the order is free.

## The coordinator

A new module, `games/catalog_submit.py`, owns one submit of the Game form. Add
Game and Edit Game both go through it.

It is a new module rather than a home in `games/catalog_compat.py` because
`catalog_compat` is what #889 removes when the flat columns go. The
coordinator outlives them: it will still open the transaction, write the Game
row and write the graph when there is nothing left to mirror.

Three functions:

```text
save_game_columns(form) -> Game
    The Game's own columns and its wikidata reference. No graph, no mirror.

save_game_and_graph(form, graph) -> Game
    @transaction.atomic
      game = save_game_columns(form)
      graph.bind(game)
      write_and_mirror(game, graph.write_rows)
      return game

submitted_game_or_form_error(form, graph) -> Game | None
    Calls save_game_and_graph, answers a refusal onto whichever form
    stated it, and returns None. Catches IntegrityError outside the
    transaction.
```

`save_legacy_game_form` in `catalog_compat.py` is the incumbent under a name
that no longer describes it. It becomes `save_game_columns` and moves into the
coordinator, keeping the two things it does that nothing else does: it refuses
a Game whose library owner would change, and it refuses a private Game with no
library owner. It stops calling `save_private_game`, stops taking
`initial_release`, and stops calling `mirror_legacy_columns` — the mirror is
the coordinator's last step, not the Game save's.

Inside the transaction the order is fixed and each step needs the one before
it:

```text
1  the Game's columns          name, sort_name, wikidata, original_release_date
2  the wikidata reference      sync_game_wikidata, which needs the saved Game
3  the graph                   CatalogGraphForm.write_rows, which needs its pk
4  the flat mirror             mirror_legacy_columns, which reads the default
                               Release and the Game's final name
```

Step 4 last is the point. The mirror checks the legacy identity — library,
name, platform, year — and today it runs against a name that is already saved
and a graph that is not yet written. Running it once, at the end, against both
finals, means a rename can no longer collide with the platform and year of a
Release the same submit is replacing.

The PlayerGame command stays outside the transaction. `run_in_transaction`
opens the transaction it retries and refuses to nest, so `record_facts_for_request`
and `track_game_for_request` run after the commit, as they do now. Add Game's
existing fallback — if tracking refuses, take the new Game back — is unchanged
and still runs outside.

Both views lose their own saver. `_saved_game_or_form_error` and
`_added_game_or_form_error` collapse into `submitted_game_or_form_error`, and
`edit_game`'s `and`-chain becomes:

```text
if form.is_valid() and graph.is_valid():
    game = submitted_game_or_form_error(form, graph)
    if game is not None and record_facts_for_request(...):
        return redirect(...)
```

`CatalogGraphForm.write()` and `.save()` go with them: the coordinator opens
the transaction and answers the refusal, so the graph form is left with
`write_rows` — the renamed `_write` — and `answer`. `bind()` resets `_blamed`,
which `write()` used to do.

### Where a refusal lands

One `try` now covers what two covered, so the order it answers in has to be
written down. `submitted_game_or_form_error` catches `ValidationError` around
the whole call and tries three things:

1. `_game_form_refusal(form, error)`, moved out of `games/views/game.py` into
   the coordinator. It recognizes the two refusals that belong to the Game's
   own fields: a wikidata conflict, onto the `wikidata` field, and
   `LEGACY_IDENTITY_TAKEN`, as a non-field error. The mirror raises the second,
   and it is about the Game's name as much as the Release's platform and year,
   so the Game form is where it belongs. Today it can land on either form
   depending on which of the two mirrors ran; now there is one.
2. `graph.blamed`, then `graph.answer(error)`. Every verb call in `write_rows`
   runs inside `_blame`, so a refusal from the service names the row that
   caused it.
3. Otherwise re-raise. `save_game_columns`'s two guards — a Game whose library
   owner would change, a private Game with no owner — are programming errors,
   not things a person typed. They stay a 500, as they are today.

## The form is the only creator

`save_private_game` leaves the form path. The form states the whole set of
Editions and Releases, including the first one, so nothing else needs to
guarantee a default.

What goes with it:

- `CatalogGraphForm.adopt()`, which existed only to claim rows
  `save_private_game` had already made. `bind(game)` replaces it and only names
  the Game the rows belong to.
- `initial_release` and the `InitialRelease` NamedTuple, the plumbing that
  carried the Add Game form's inline Release down to `save_private_game`.
- `_default_release`'s use as an input to a save. It stays as the mirror's
  reader.

What changes inside `write_rows`: on a Game with no stored graph, the marked
Edition is created first and takes the default mark, and its marked Release is
created first and takes the default mark within it. This is what
`save_private_game` did, moved to the one place that knows which row the person
marked.

This makes the claim already in `docs/catalog.md` — "The graph is written in
one place" — true.

`save_private_game` itself stays in `games/catalog_writes.py`. Removing it is
not this issue's work: it is a public verb, #782's importer may want exactly
its guarantee, and #889 may retire it with the columns. After this change it
has no caller outside tests. That verdict goes on #986 and on the catalog epic,
not only here.

## What the form refuses that the service cannot see

Defect 2 is a gap between what the form knows and what a verb knows. The verbs
are one row each; they cannot see that the name a new Edition wants is the name
of an Edition the same submit is removing. The form can, because it holds the
whole posted set beside the stored one.

Reordering the write instead was considered and rejected. Running the removals
first would make the upsert see a departed row and create the one the person
asked for — but the removals cannot go first. `remove_edition` refuses the
default Edition and `remove_release` refuses a default with a live sibling, so
the crown has to move before either can leave, and moving the crown onto the
newly added row is the very add that has to come after. Breaking the knot means
a "park the crown" step that promotes some *stored* survivor first, using its
stored name and pair rather than its posted ones, or the promotion trips the
duplicate check itself. That is a third write order to reason about, in service
of accepting a submit whose plain reading — remove this edition, add one called
the same thing — is a person changing their mind mid-form. A validation rule is
smaller, and it says what happened.

Two rules join `_validate_names` inside `_validate_set`. Both compare a
surviving row's *stated* value against a departing row's *stored* value,
because the stored value is what still occupies the index at write time.

**An Edition name a removal is giving up.** Collect the stored names of every
removed block that has a stored Edition, stripped and casefolded. A surviving
block whose cleaned name casefolds into that set gets an error on its `name`
field:

```text
REMOVED_EDITION_NAME_IN_FORM =
    "Another edition you are removing already has this name. "
    "Rename one of them, or put the removal back."
```

An empty name is skipped on both sides. `unique_live_edition_name_per_game`
excludes the unnamed Edition and `add_edition` matches nothing on an empty
name, so two unnamed Editions never collide.

**A Release pair a removal is giving up.** Within one surviving block, collect
the stored `(platform_id, release_date)` of every removed row that has a stored
Release. A surviving row whose stated pair is in that set gets a non-field
error on that row, because the pair is two fields and neither one is at fault
alone:

```text
REMOVED_RELEASE_IN_FORM =
    "Another release you are removing already has this platform and date. "
    "Change one of them, or put the removal back."
```

The stated platform is a `Platform` instance from the row's `ModelChoiceField`
and the stored one is an id, so the comparison is on `platform_id`.
`TemporalValue` is a frozen dataclass, so the pair is hashable and a set is
fine.

Rows inside a removed block are not considered: `_remove_releases` skips them,
and a surviving row cannot be in one.

The second rule catches more than the bin-and-re-add it was written for. An
existing Release *edited* onto a departing Release's pair hits it too, which
today surfaces as an unexplained `DUPLICATE_RELEASE` from the service.

## What a constraint says

Defect 3 has no pre-check that can be made sound. `mirror_legacy_columns` reads
with a SELECT and writes with an UPDATE; between them another submit can take
the identity. `update_edition`'s duplicate-name check and `sync_game_wikidata`'s
provider-key check have the same shape, and the two default marks have no check
at all — `_clear_default_edition` stands the old one down and trusts that
nothing else is standing one up. The database is the only thing that decides,
so the answer is to read what it decided.

`submitted_game_or_form_error` catches `IntegrityError` **outside** the
`transaction.atomic` block — inside one the connection is unusable — reads
`error.__cause__.diag.constraint_name`, and looks it up in a named mapping in
`games/catalog_submit.py`:

| constraint | sentence |
| --- | --- |
| `unique_library_game_name_platform_year` | `LEGACY_IDENTITY_TAKEN` |
| `unique_library_platformless_game_name_year` | `LEGACY_IDENTITY_TAKEN` |
| `unique_live_edition_name_per_game` | `DUPLICATE_EDITION_NAME` |
| `unique_default_edition_per_game` | `RACED` |
| `unique_default_release_per_edition` | `RACED` |
| `unique_external_reference_provider_kind_key` | `WIKIDATA_CONFLICT_MESSAGE` |

```text
RACED = "Another change reached this game first. Nothing was saved; try again."
```

Only `RACED` is new. `LEGACY_IDENTITY_TAKEN`, `DUPLICATE_EDITION_NAME` and
`WIKIDATA_CONFLICT_MESSAGE` already exist, and the mapping reuses them rather
than writing a second wording for the same refusal.

An unmapped constraint is re-raised as itself. This follows `answers.py`: a
wrong sentence is worse than none, and a 500 with a traceback is what a
constraint nobody anticipated should produce.

A guard test enumerates the unique constraints declared on `Game`, `Edition`,
`Release` and the wikidata external reference, and fails unless each one is
either mapped or named in an explicit `UNREACHABLE_FROM_THE_GAME_FORM` list
with a reason. This mirrors `tests/test_command_answers.py`, and it is what
keeps the mapping honest when a migration adds a constraint.

The sentence lands where its `_game_form_refusal` twin lands: the wikidata one
on the `wikidata` field, the rest as a non-field error on the Game form. A race
names no row the person can be pointed at, and the Game form is where they are
already looking.

## Tests

One per defect, plus the guard.

**The transaction.** A submit that renames the Game and states a graph the
service refuses: the response re-renders with the refusal, and
`game.refresh_from_db()` shows the old name. Its inverse matters as much — a
submit that renames the Game and states a graph that is fine saves both — so
the rollback is not passing because nothing was written.

**The removals.** Four cases:

- Bin an Edition and add another with its name. Expect the sentence on the new
  block's `name`, and — because the defect is silent, not loud — assert the
  database too: the stored Edition still there and unremoved, and no second
  Edition made.
- The same within one Edition for a Release's platform and date pair.
- The marked block carrying the removed row's name, which today answers
  `DEFAULT_EDITION_HELD` about a row the person did not touch.
- The one that must still pass: bin an Edition, add one with a *different*
  name, and see both happen.

**The edit onto a departing pair.** An existing Release row edited onto the
platform and date of a Release the same submit removes. Today the service
answers `DUPLICATE_RELEASE`; expect the new sentence, which names the removal.

**The one creator.** Add Game with a stated Edition name and Release still
produces exactly one Edition and one Release, both default, and neither is an
unnamed leftover. A Game whose graph was never written — the state the backfill
leaves — edited to exactly one Edition, saves.

**The constraint.** The race cannot be provoked in a test, so it is proved in
two halves: the mapping is a pure unit test over constraint name to sentence,
and one integration test patches `mirror_legacy_columns`'s pre-check to pass so
the real `IntegrityError` rises, then asserts the form answers with
`LEGACY_IDENTITY_TAKEN` rather than raising. Plus the guard test over the
constraint list.

**The browser.** One case in `e2e/test_game_form_catalog_e2e.py`: bin an
Edition, give a new one its name, submit, and see the sentence on that row's
name field with the form's other values still filled in.

Every test that POSTs through these views needs
`@pytest.mark.django_db(transaction=True)`, as the existing ones do.

## Documentation

`docs/catalog.md`:

- "The graph is written in one place" becomes true, and the sentence names the
  form as that place rather than describing an intent.
- The two new refusals join "What a form refuses that the service does not",
  each with the reason the service cannot see it.
- A short section on the constraint backstop: the mapping, the guard test, and
  why an unmapped constraint is re-raised.
- The `save_private_game` verdict: no caller outside tests, kept for #782 or
  #889 to decide.

`CLAUDE.md`'s catalog bullet drops `adopt()` and the `save_private_game` half
of the Add Game sentence, and names `games/catalog_submit.py` as the one
submit.

## What waits

- **Removing `save_private_game`.** Recorded on #986 and the catalog epic.
- **`record_facts_for_request` failing after a committed graph.** It still
  leaves the graph saved and re-renders. Making the command and the graph one
  unit is impossible while `run_in_transaction` refuses to nest, and the
  failure mode — a saved catalog edit with an unsaved status change — is much
  smaller than the one this spec closes.
- **#889.** The mirror, `catalog_compat.py`, `LEGACY_IDENTITY_TAKEN` and two
  rows of the constraint table go when the flat columns do. The coordinator is
  written so that removing them is a subtraction.
