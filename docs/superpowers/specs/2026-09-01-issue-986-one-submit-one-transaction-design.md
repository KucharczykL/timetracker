# One submit, one statement

Issue [#986](https://github.com/KucharczykL/timetracker/issues/986). Edit Game
presents one page and one Submit, and writes it as a Game save, then six row
verbs in a sequence, then a mirror, across three transactions. This spec makes
one submit one statement: one transaction, and one service call that states the
whole graph.

The issue lists four defects. Two of them — the removal that eats a re-add, and
the second creator — are not fixed here. They stop being expressible.

## Why the row verbs are the wrong grain

`games/catalog_writes.py` offers six verbs, one row each. Every one opens its
own transaction and checks the Game's whole invariants — one default Edition,
one default Release per Edition, unique live names, a Game keeps an Edition —
against the state standing at that moment.

`CatalogGraphForm` states a set. It holds every Edition and every Release a
person posted, beside the stored graph, and turns them into an ordered sequence
of verb calls. Because each call re-checks the invariants against an
intermediate state, the order is a puzzle, and `_write` is five named steps of
solving it: promote the marked Edition first so the old default steps down,
write the other Editions second so none reads as demoted, write each block's
winner before its siblings, remove Releases fourth, remove Editions last.

The puzzle has no solution. Bin the (Amiga, 1984) Release and add a fresh row
stating Amiga and 1984 in the same submit: the adds run before the removals,
`add_release` matches on that pair among the *live* Releases, and it hands back
the row about to be removed. Step 4 stamps it. The submit reports success and
the row is gone. Reordering does not help — `remove_edition` refuses the
default Edition and `remove_release` refuses a default with a live sibling, so
the crown must move before either can leave, and the add that moves it is the
one that has to come after.

Five of the service's eleven refusals exist only because a row verb cannot see
the row that answers it:

| refusal | what it is really saying |
| --- | --- |
| `DEFAULT_EDITION_HELD` | you did not tell me which sibling takes the mark |
| `DEFAULT_RELEASE_HELD` | the same, one level down |
| `DEMOTED_EDITION` | you did not tell me who is default instead |
| `DEMOTED_RELEASE` | the same, one level down |
| `DUPLICATE_RELEASE` | I cannot see that the holder is leaving |

A caller that states the whole set answers all five in the statement. So the
service gains a verb at the grain its one caller uses, and loses the five.

## The upsert has no consumer

`add_edition` matches an existing Edition by name and `add_release` matches by
`(platform, release_date)`. `docs/catalog.md` calls this "Repeating a write"
and justifies it as idempotency for #782's bulk importer. That justification is
already retired, by #782 itself:

> It is not a prerequisite of idempotency either, because `ExternalReference`
> already accepts `entity_kind="release"` and each Release keys on IGDB's own
> `release_dates.id`.

`ExternalReference` has `edition` and `release` entity kinds, a unique
`(provider, entity_kind, provider_key)` and a check constraint pairing kind to
target. It was built to be the importer's identity. Name-matching is a second,
weaker mechanism for a consumer that documented it wants the first.

Three more things say the same:

- **The only production caller of all six verbs is `games/catalog_form.py`.**
  Every other call site is a test. There is no second consumer to preserve the
  semantics for.
- **There is no database constraint on `(edition, platform, release_date)`** —
  `Release` carries only `unique_default_release_per_edition`. The pair is a
  service convention, so retiring it costs the schema nothing. #782 also notes
  the pair "becomes a triple" if region lands: an identity already known to be
  temporary.
- The rule does not hold for the common shape anyway. `docs/catalog.md:165`:
  "An unnamed Edition matches nothing, and each unnamed add makes one." On 858
  Games holding one unnamed Edition each, the upsert never fires.

So identity comes from the id the caller names, and nothing else. A row the
caller names is that row; a row it does not name is new.

## The verb

`games/catalog_writes.py` keeps its name and its sentences, and its public
surface becomes one verb.

```text
state_catalog_graph(*, game, library, editions) -> WrittenGraph
```

`editions` is the whole desired graph of one Game, in the order it should read.

```text
type RowKey = str

EditionState
    key           RowKey        the caller's name for this row, handed back on a refusal
    edition       Edition|None  None states a row that does not exist yet
    name          EditionName
    removed       bool
    is_default    bool
    releases      tuple[ReleaseState, ...]

ReleaseState
    key           RowKey
    release       Release|None
    platform      Platform|None
    release_date  TemporalValue|None
    removed       bool
    is_default    bool

WrittenGraph
    game          Game
    editions      tuple[WrittenEdition, ...]   parallel to the surviving input

WrittenEdition
    key           RowKey
    edition       Edition
    releases      tuple[tuple[RowKey, Release], ...]
```

`key` is opaque to the service. The form passes the prefix it already has —
`editions-0`, `editions-0-releases-1` — and a refusal hands it back, so the
sentence reaches the row that caused it without the service knowing what a form
is.

**A row the caller does not mention is left alone.** Removal is stated by
`removed=True` on the row. The form always posts its whole set and sees no
difference; a partial writer such as #782's importer can state the two Editions
it knows about without removing the three a person added by hand. Absence
meaning removal would make one importer bug take somebody's catalog.

### What it refuses

Every refusal is checked against the **desired end state**, before anything is
written, and each carries the `key` of the row that caused it.

| refusal | when |
| --- | --- |
| `SHARED_GAME`, `FOREIGN_GAME`, `REMOVED_GAME` | the Game, as today |
| `REMOVED_EDITION`, `REMOVED_RELEASE` | a named row is not live, read under the lock |
| `FOREIGN_PLATFORM` | a stated Platform belongs to another library |
| `DUPLICATE_EDITION_NAME` | two surviving Editions state one name |
| `LAST_EDITION` | no Edition survives |
| `TWO_DEFAULT_EDITIONS` | two surviving Editions state the mark |
| `TWO_DEFAULT_RELEASES` | two surviving Releases of one Edition state the mark |
| `FOREIGN_ROW` | a named row belongs to another Game or Edition |

Three sentences are new:

```text
TWO_DEFAULT_EDITIONS = "A game keeps one default edition, and this states two."
TWO_DEFAULT_RELEASES = "An edition keeps one default release, and this states two."
FOREIGN_ROW = "This row belongs to another game."
```

`DEFAULT_EDITION_HELD`, `DEFAULT_RELEASE_HELD`, `DEMOTED_EDITION`,
`DEMOTED_RELEASE` and `DUPLICATE_RELEASE` go. The statement answers each one.

If no surviving Edition states the mark, the first one takes it; the same one
level down, per Edition. This is today's rule — "the first live child a Game or
an Edition gets becomes the default" — stated once instead of derived from the
order of six calls.

**A named row is re-read under the lock.** The `Edition` and `Release` the
caller passes are identity only; the verb resolves each against storage after
`select_for_update()` on the Game and refuses one that is removed, or that
hangs from another Game or Edition. A caller holding a row read before the lock
— which every caller does — cannot act on a stale one.

### The write order is now private

Because one writer sees the whole desired state, the order is an implementation
detail rather than a contract. It is:

```text
1  stand every live default down    UPDATE is_default=False, both levels
2  stamp the removals               Releases, then Editions
3  free the names being given up    UPDATE name="" on a surviving Edition
                                    whose name changes
4  write the surviving stored rows  name, platform, date
5  create the new rows
6  set the two marks                one UPDATE each
```

Step 1 is what makes the rest free, and it is legal as it stands: both default
constraints are `UniqueConstraint`s, so they permit *at most* one live default
— zero is fine for the length of a transaction. **No migration is needed.**

A removed Edition's Releases are not touched, at step 2 or anywhere. They stay
live and hidden, because each read tests its ancestors' marks as well as its
own, and that is what lets restoring the Edition bring back exactly the rows
nobody removed. This is today's `remove_edition` behaviour, kept.

The alternative was deferring the constraints to end-of-transaction. That is
not available: all three are partial (`condition=`), Postgres can only defer a
non-partial unique constraint, and Django rejects `condition` with
`deferrable` outright. It would mean re-expressing live-ness as generated key
columns that go null when removed. Standing the marks down costs one UPDATE
and needs none of it.

Step 3 handles the rename swap — Edition A takes B's name and B takes A's.
Today `update_edition`'s pre-check refuses it. Parking to `""` first works
because `unique_live_edition_name_per_game` excludes the empty name, so a
parked row claims no slot. Releases need no such step: the pair carries no
constraint, and the service rule that stood in for one is gone.

### What the other verbs become

`add_edition`, `update_edition`, `remove_edition`, `add_release`,
`update_release`, `remove_release` and `save_private_game` are removed. They
have no production caller but the form, and a wrapper would only invite a
future caller back into the grain this spec is leaving.

`save_private_game`'s guarantee — a Game gets a default Edition holding a
default Release — is one `state_catalog_graph` call, and the form makes it.
This is defect 4: two things created the graph, so Add Game had to claim rows
it did not ask for through `adopt()`. One creator, and there is nothing to
claim.

## The coordinator

A new module, `games/catalog_submit.py`, owns one submit of the Game form. Add
Game and Edit Game both go through it. It is a new module rather than a home in
`games/catalog_compat.py` because #889 removes that file with the flat columns,
and the coordinator outlives them.

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
    Calls save_game_and_graph, answers a refusal onto the row that
    stated it, and returns None. Catches IntegrityError outside the
    transaction.
```

`save_legacy_game_form` in `catalog_compat.py` is the incumbent under a name
that stopped describing it. It becomes `save_game_columns` and moves here,
keeping the two things it does that nothing else does: it refuses a Game whose
library owner would change, and a private Game with no library owner. It stops
calling `save_private_game`, stops taking `initial_release`, and stops calling
the mirror.

Inside the transaction, each step needs the one before it:

```text
1  the Game's columns    name, sort_name, wikidata, original_release_date
2  the wikidata reference sync_game_wikidata, which needs the saved Game
3  the graph             one state_catalog_graph call, which needs its pk
4  the flat mirror       mirror_legacy_columns, which reads the default
                         Release and the Game's final name
```

Step 4 last is the point of defect 1's second half. The mirror checks the
legacy identity — library, name, platform, year — and today it runs twice,
each time against one half of a finished submit: once against a new name and
the old graph, once against the new graph. Running it once, at the end, means a
rename can no longer collide with the platform and year of a Release the same
submit is replacing.

The PlayerGame command stays outside the transaction. `run_in_transaction`
opens the transaction it retries and refuses to nest, so
`record_facts_for_request` and `track_game_for_request` run after the commit,
as they do now. Add Game's fallback — if tracking refuses, take the new Game
back — is unchanged and still runs outside.

`edit_game`'s `and`-chain, where each `and` is a commit, becomes:

```text
if form.is_valid() and graph.is_valid():
    game = submitted_game_or_form_error(form, graph)
    if game is not None and record_facts_for_request(...):
        return redirect(...)
```

`_saved_game_or_form_error` and `_added_game_or_form_error` collapse into
`submitted_game_or_form_error`.

### Where a refusal lands

One `try` now covers what two covered, so the order it answers in is written
down. `submitted_game_or_form_error` catches `ValidationError` and tries three
things:

1. `_game_form_refusal(form, error)`, moved out of `games/views/game.py`. It
   recognizes the two refusals belonging to the Game's own fields: a wikidata
   conflict, onto the `wikidata` field, and `LEGACY_IDENTITY_TAKEN`, as a
   non-field error. The mirror raises the second, and it is as much about the
   Game's name as about the Release's platform and year.
2. The refusal carries a `key`, so `graph.answer(error)` puts the sentence on
   that row.
3. Otherwise re-raise. `save_game_columns`'s two guards are programming errors,
   not things a person typed, and stay a 500 as they are today.

## What the form becomes

`CatalogGraphForm` keeps its validation and loses its write order.
`_promote_marked_edition`, `_write_other_editions`, `_winner`,
`_write_releases`, `_write_release`, `_write_edition`, `_remove_releases`,
`_remove_editions` and the `_blame` context manager all go. In their place,
`write_rows` builds the states and makes one call:

```text
write_rows()
    editions = [EditionState(...) for every block, in page order]
    written = state_catalog_graph(game=..., library=..., editions=editions)
    map each WrittenEdition back onto its block by key
```

The mark becomes `is_default=True` on one Edition state and one Release state,
which is what the single `in_library` radio already means.

`adopt()` and `initial_release` go, and `bind(game)` replaces them: it names
the Game and resets the blame. `InitialRelease` in `catalog_compat.py` goes
with them.

Defect 4's stale photograph also goes. `__init__` reads `game_hierarchy` at
request start, and today `save_private_game` creates rows behind that read
mid-request, so a posted row that storage now holds is treated as new and the
Game ends with two Editions. Nothing writes the graph but the form now, and the
verb re-resolves every named row under the Game lock, so the read decides only
which posted ids are recognized.

### One refusal the form keeps making

`DUPLICATE_RELEASE` leaves the service, and it should not leave the page: two
surviving Releases of one Edition stating the same platform and date show a
person two rows they cannot tell apart. `_validate_set` refuses it, beside the
`UNNAMED_SIBLING_EDITION` rule that is already there for the same reason.

It is a rule about the *surviving* set, so the case that started this spec —
bin one row, add another stating its platform and date — passes it and is
written correctly.

```text
DUPLICATE_RELEASE_IN_FORM =
    "Another release of this edition already states this platform and date."
```

`docs/catalog.md`'s "What a form refuses that the service does not" gains it,
with the reason: the service allows two, because #782 needs two regions on one
date to be two rows.

## What a constraint says

The races remain, and no pre-check can win them. `mirror_legacy_columns` reads
with a SELECT and writes with an UPDATE; `sync_game_wikidata` has the same
shape; the two default marks are now set by the verb without a pre-check at
all. The database is the only thing that decides, so the answer is to read what
it decided.

`submitted_game_or_form_error` catches `IntegrityError` **outside** the
`transaction.atomic` block — inside one, the connection is unusable — reads
`error.__cause__.diag.constraint_name`, and looks it up in a named mapping:

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

Only `RACED` is new; the mapping reuses the three sentences that exist rather
than writing a second wording for the same refusal. An unmapped constraint is
re-raised as itself, following `answers.py`: a wrong sentence is worse than
none.

A guard test enumerates the unique constraints declared on `Game`, `Edition`,
`Release` and `ExternalReference`, and fails unless each is either mapped or
named in an explicit `UNREACHABLE_FROM_THE_GAME_FORM` list with a reason. This
mirrors `tests/test_command_answers.py` and is what keeps the mapping honest
when a migration adds a constraint.

Each sentence lands where its `_game_form_refusal` twin lands: wikidata on the
`wikidata` field, the rest as a non-field error on the Game form. A race names
no row a person can be pointed at.

## Tests

`tests/test_catalog_graph_writes.py` is rewritten against the one verb. Most of
its 41 tests survive as cases — the permission refusals, the removal rules, the
name rules — each stating a graph rather than calling a verb. The five retired
refusals become their opposite: a test that the statement *accepts* what the
row verb refused.

New to the service:

- **Bin and re-add.** State a graph removing the (Amiga, 1984) Release and
  adding one stating Amiga and 1984. One live Release, the new one, and the old
  one stamped. The Edition twin: remove one and add another with its name.
- **The rename swap.** Two Editions exchange names in one statement.
- **The crown moves and its holder leaves.** Remove the default Edition and
  mark a sibling in the same statement — today `DEFAULT_EDITION_HELD`, now
  written. The Release twin.
- **Every named row is re-read.** A statement naming an Edition removed after
  the caller read it answers `REMOVED_EDITION`; one naming another Game's
  Edition answers `FOREIGN_ROW`.
- **A row nobody mentions is left alone.** State two of three Editions; the
  third is untouched and still live.
- **Both marks are total.** No stated default gives the first surviving row the
  mark, at both levels; two stated defaults are refused.
- **The key comes back.** Each refusal above carries the `key` of the row that
  caused it.

At the form and view level:

- **One transaction.** A submit that renames the Game and states a refused
  graph re-renders with the refusal, and `refresh_from_db()` shows the old
  name. Its inverse — rename plus a graph that is fine — saves both, so the
  rollback is not passing because nothing was written.
- **One creator.** Add Game with a stated Edition name and Release leaves
  exactly one Edition and one Release, both default, no unnamed leftover. A
  Game whose graph was never written — what the backfill leaves — edited to one
  Edition, saves.
- **The form's own duplicate rule** refuses two identical surviving Releases
  and permits the bin-and-re-add pair.
- **The constraint mapping** as a pure unit test, plus one integration test
  patching the mirror's pre-check so a real `IntegrityError` rises and the form
  answers `LEGACY_IDENTITY_TAKEN` rather than raising, plus the guard test.

One case in `e2e/test_game_form_catalog_e2e.py`: bin a Release, add one stating
its platform and date, submit, and see one row afterwards — the new one.

Every test POSTing through these views needs
`@pytest.mark.django_db(transaction=True)`, as the existing ones do.

## Documentation

`docs/catalog.md` is the contract, and three of its sections change shape:

- **"Repeating a write" goes.** Identity is the id the caller names. In its
  place, a short section on stating a graph: what a row that names nothing
  means, what an unmentioned row means, and why absence is not removal.
- **"What a removal refuses" shrinks to one rule** — a Game keeps an Edition.
  The other three were about a mark the statement now carries.
- **"The graph is written in one place"** becomes true, and names
  `state_catalog_graph` as that place.
- "What a form refuses that the service does not" gains the duplicate-Release
  rule; the constraint backstop gets its own short section.

`CLAUDE.md`'s catalog bullet names one verb instead of six, drops `adopt()` and
`save_private_game`, and names `games/catalog_submit.py` as the one submit.

An issue comment on #782 records that the importer's identity is
`ExternalReference` and that name-matching is gone, since that issue's own
words are the argument for removing it.

## What waits

- **Region on a Release.** #782 decides it. The pair identity that would have
  had to become a triple no longer exists, so the column is now purely
  additive.
- **`record_facts_for_request` failing after a committed graph.** It leaves the
  graph saved and re-renders. The command and the graph cannot share a
  transaction while `run_in_transaction` refuses to nest, and a saved catalog
  edit beside an unsaved status change is much smaller than what this spec
  closes.
- **#889.** The mirror, `catalog_compat.py`, `LEGACY_IDENTITY_TAKEN` and two
  rows of the constraint table go when the flat columns do. The coordinator is
  written so that removing them is a subtraction.
