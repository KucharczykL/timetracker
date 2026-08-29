# The PlayerGame read cutover

Issue [#678](https://github.com/KucharczykL/timetracker/issues/678). #671 gives
the row, #672 to #675 give its columns, #676 backfills it, and #677 writes it.
This issue makes it the read source.

A library's game list is the list of games that library tracks. Every
authenticated Game read resolves private state from `PlayerGame` and catalog
state from `Game`. The two catalog columns stop being read; #770 removes them.

The work exceeds the catalog wave's re-slice thresholds, so it ships as four
child issues on one integration branch. [The child issues](#the-child-issues)
name them.

## The join

`GameQuerySet.tracked_by(library)` joins the library's projection row.

```python
def tracked_by(self, library):
    """Every live game this library tracks, with its row aliased."""
    return (
        self.alive()
        .annotate(
            tracked=FilteredRelation(
                "player_games", condition=Q(player_games__library=library)
            )
        )
        .filter(tracked__isnull=False)
    )
```

Filter, sort and display then read `tracked__status` and `tracked__mastered`
through the alias. `tracked__archived_at` has no reader; [what this issue does
not remove](#what-this-issue-does-not-remove) says why.

`tracked_by()` does not repeat `for_library()`'s `library=library`. A shared
catalog game this library tracks belongs on the list, because a list of tracked
games is what the page claims to be. Today `TrackGame` accepts a shared game
and `for_library()` then hides it, so tracking one has no visible effect at
all. Production holds no such row — `backfill_library()` walks
`Game.objects.filter(library=library)` and never reaches a shared game — so
this widens the definition without changing a single row on the first day.

A `FilteredRelation` and not a plain path. Django opens a join per `.filter()`
call on a multi-valued relation, and the list applies its scope and its
criteria in separate calls. On a plain path the second join carries no library
condition, which is measured rather than feared:
`filter(player_games__library=mine).filter(player_games__status="played")`
returns a shared catalog game whose only played row belongs to another library.

The alias does not remove the second join. It copies its condition into every
join it opens:

```sql
INNER JOIN games_playergame tracked ON (… AND tracked.library_id   = %s)
INNER JOIN games_playergame T4      ON (… AND T4.library_id        = %s)
WHERE tracked.id IS NOT NULL AND T4.status = %s
```

Both joins are library-scoped, and `unique_library_player_game` allows at most
one row per pair, so the two cannot disagree. That pairing is the guarantee,
not the alias by itself: dropping the unique constraint would reopen the hole
with the alias still in place.

The price is one join per `tracked__` filter call — two when the quick bar sets
status and mastered. Collapsing them into a single `.filter()` call is the
remedy if a query plan ever asks for it.

`alive()` comes first, and it is what keeps a deleted game off the list. Since
#676 a game delete never removes the row: `catalog.game` is a required
reference kind, the backfill gave every game at least one event that names it,
so `tombstone_or_delete()` takes the tombstone branch every time. The catalog
row survives with `tombstoned_at` set, and the projection row survives beside
it. Without `alive()` every deleted game comes back.

The join is an inner join, so an untracked game is absent from every read.
Three sources put games in a database and each one leaves a row: the game form
dispatches `TrackGame`, migration `0033_playergame_baseline_backfill` covers
every restored dump, and `load_sample_data` calls `backfill_library()`. A test
is the fourth source and leaves none, which [the test gap](#the-test-gap)
answers.

Two places supply the annotated queryset, not one. `relation_to_q` builds each
subquery from `context.queryset_for(Game)`, so changing
`filter_query_context_for_library()` to return `tracked_by(library)` covers
every nested `GameFilter` at once — the one `stats_links` puts inside a
`PurchaseFilter` included. The top level is separate: `execute_filter` applies
the filter to the queryset its caller passes, and for games that caller is
`list_games`. Both must change together.

A `GameFilter` applied to a queryset without the annotation raises `FieldError`
— a 500, not a degraded page. Only one production site can make that mistake,
and the tests that build a `Game` queryset by hand are the ones to watch.

## What the filter layer needs

`FilterField` takes an optional `metadata_lookup`.

```python
fields = {
    "status": FilterField("tracked__status", metadata_lookup="player_games__status"),
    "mastered": FilterField(
        "tracked__mastered", metadata_lookup="player_games__mastered"
    ),
}
```

`_walk_lookup` resolves real model paths. `tracked` is an annotation alias and
resolves to nothing, and `field_metadata` treats a lookup that names no column
as a misconfigured field and raises. So this is not a cosmetic fix: without it
the games filter metadata fails on its first build. The two paths are declared
apart — the query reads the alias, and the metadata layer walks the real path
to `PlayerGame.status`. Where both are set the metadata layer prefers
`metadata_lookup`.

`_static_choices` then reports all six words, `shelved` among them, from the
field itself. No hand-written option list exists to disagree with the column.

Both fields need it, because neither carries a handler: `field_metadata` skips
column resolution only for a handler-mapped field, and these two are plain
lookups. They are also the whole list — no third game field moves to the
projection in this issue.

## The status vocabulary

A status travels as a word. The `?filter=` JSON, `GameForm.status`,
`GameStatusSelector`, the API's `GameStatusUpdate`, and the five `stats_links`
builders each hold `PlayerGameStatus` members. `Game.Status` keeps its members
and loses its readers.

`PlayerGameStatus.SHELVED` becomes reachable. It has no letter, which is why
`legacy_status_for()` raised for it, and the reverse direction of the map goes
with the reads: `legacy_status_for`, `LegacyStatus` and `UnmappedPlayerStatus`
are deleted.

The forward direction survives, and `games/playergame_status.py` survives with
it. `backfill_game()` calls `player_status_for()` twice — once per legacy
`GameStatusChange` row and once for the game's current letter — and migration
`0033_playergame_baseline_backfill` imports the backfill at run time, so every
fresh database walks this code. [The test gap](#the-test-gap) calls it too. The
module keeps its path because a historical migration names it; only the half
with no caller goes.

Nothing translates an old value. The deployed database holds zero saved filter
presets, confirmed on 2026-08-28, so no preset carries a letter and no data
migration is needed. A bookmarked `?filter=` with a letter stops matching. The
spec records the count because a preset appearing later would make this section
wrong.

Sort order does not change. Ordering by letter gives `a, f, p, r, u`; ordering
by word gives `abandoned, completed, played, retired, unplayed`. The two orders
agree, so `?sort=status` returns the same page, and `shelved` takes its place
between `retired` and `unplayed`. A parity test pins the agreement rather than
trusting it.

`GameStatus` keys its colour table on words and gains a colour for `shelved`.

## History

The detail page's History section reads `library.playergame.status_changed`
events on the game's stream. It stops reading `GameStatusChange`.

Migration `0033_playergame_baseline_backfill` recorded every legacy row as an
event, with its effective time and its source `status_change_id`. The event log
is therefore a superset of the table, the section loses no entry on the first
day, and it grows again.

Four routes retire here: `statuschange/add`, `statuschange/edit`,
`statuschange/delete` and `statuschange/list`. `GameStatusChangeForm` retires
with them. So does the `pre_save` audit signal on `Game`: since #677 the mirror
is the only writer that changes a status, so the mirror's deletion leaves the
signal nothing to record.

The table and its rows stay. #771 removes the storage. #683 returns the ability
to state a backdated transition, as a command with an effective time;
`SetPlayerGameStatus` states neither today and gaining both is that issue's
work, not this one's.

## Statistics

`stats_data.py` holds four `games__status=` predicates.
`PurchaseQuerySet.finished()`, `.abandoned()` and `.dropped()` hold three more.
A queryset method holds no library, so each becomes membership over a
library-scoped subquery, which is the idiom `relation_to_q` already uses.

```python
purchases.filter(
    games__in=Game.objects.tracked_by(library).filter(tracked__status=COMPLETED)
)
```

Behaviour is preserved exactly, quirks included, with one exception below.
`~Q(games__status="f")` over a multi-game purchase is already subtle, and a
cutover is the wrong moment to settle what it should mean. The parity suite is
the arbiter: a difference it reports is reverted to match the old result, not
argued to be an improvement.

**The exception: retired joins completed as the finished state.** Agreed with
the user during child C. Retired means done with a game that has no ending, so
a retired game is one the player is done with, but the statistics count it in
no bucket at all — `finished` selects `completed` or an ended play event,
`unfinished` drops it from the backlog, and `dropped` selects only `abandoned`
or refunded. It falls out of all three. `DONE_STATUSES` in `games/models.py`
holds the pair, and `stats_data.py` and `stats_links.py` both read it. Child C
moves the reads in one commit and changes this answer in the next, so the two
are separable. Every other predicate keeps its result.

## The write path after the mirror

`_mirror()` copies the projection row onto the catalog so the catalog reads
stay right. It goes when the last of those reads goes, which is in child D and
not before. A–C therefore run with the mirror alive: each moves one surface to
the projection while the catalog columns it leaves behind stay current for the
surfaces that have not moved yet. Deleting it earlier would leave statistics
reading frozen letters for two pull requests.

Something must still turn a `CommandRejected` into a toast and a redirect.
`games/writes/playergame.py` keeps that job, minus the mirror: it takes an
actor and not a request, which is what lets the API call it.
`games/views/playergame_writes.py` is deleted, and each view calls
`games/writes/playergame.py` and catches `PlayerGameWriteFailed`.

So one module is deleted and two are trimmed —
`games/writes/playergame.py` loses `_mirror()` and
`games/playergame_status.py` loses its reverse direction. The #677 note
forecast three deletions; the backfill and the migration keep the letter map
alive, and the request wrapper is the only module with nothing left to do.

## The test gap

117 test files call `Game.objects.create`, over 598 sites. 43 of them also
exercise a game read path, and under an inner join each of those reads an empty
list.

One autouse fixture in `tests/conftest.py` and one in `e2e/conftest.py` connect
a `post_save` receiver on `Game`. On a created game that names a library, it
writes the row directly:

```python
PlayerGame.objects.create(
    pk=uuid.uuid7(),
    library=instance.library,
    game=instance,
    tracked_at=timezone.now(),
)
```

A direct write and not `backfill_game()`. The backfill needs an actor and a run
time, opens its own transaction, and appends events — inside a `post_save` on a
`Game` a test just created, that is a second transaction and a stream the test
never asked for. The row is what the inner join wants, so the row is what the
fixture writes.

The cost is stated plainly: the fixture leaves a projection row with no event
behind it, which production never does, and test setup that diverges from
production lets a test pass where production would fail.
`tests/test_playergame_write_path.py` covers the real path, event log included,
and is the reason the divergence is affordable.

## The child issues

Each child is one bounded branch and pull request onto
`codex/playergame-read-cutover`. The branch merges to `main` once.

**A — the join and the display.** `tracked_by()`,
`FilterField.metadata_lookup`, the `filter_query_context_for_library()` wiring,
`list_games`, `view_game`, `GameStatusSelector`, `GameStatus`, `_record_played`,
`GameForm`, the autouse fixtures, and the parity suite.

**B — filters, sorts and the quick bar.** `GameFilter.status` and `.mastered`,
`GAME_SORTS["status"]`, and the six-option status widget.

**C — statistics and the API.** The four `stats_data` predicates, the three
`PurchaseQuerySet` methods, the five `stats_links` builders,
`GameStatusUpdate`, and `PATCH /api/games/{id}/status`.

**D — history and the retirement.** History from events, the four
`statuschange` routes and the audit signal, `_mirror()` and
`games/views/playergame_writes.py`, the reverse half of
`games/playergame_status.py`, and the deletion of the parity suite. The mirror
goes last because A to C each leave catalog readers behind them.

Creating the four issues is a mutating action. It follows the catalog wave's
export, diff and read-back protocol, and it happens after this spec is
approved.

## Verification

`tests/test_playergame_read_parity.py` is created by A and deleted by D. It
asserts equal id sets, old against new, over the status and mastered filters,
every `GAME_SORTS` entry, and every `stats_links` builder. Its whole purpose is
to guard the switch, so it does not outlive it.

The existing `stats_links` parity tests are re-pointed and kept.

A browser test covers the games list under the inner join: a tracked game is
listed, a game the library deleted is not, and the status a selector sets is
the status the reloaded page shows.

Each child pull request ends on a full `make check`. The merge to `main` adds
the wave's integration gate, including the rehearsal against a restored
production copy.

## What this issue does not remove

`PlayerGame.archived_at` gains no reader, and `ArchivePlayerGame` and
`RestorePlayerGame` gain no caller. The column was going to hide a game from
the list, and a delete already does that — since #676 a delete tombstones the
catalog row, `alive()` drops it, and nothing is recoverable afterwards because
`tombstone_or_delete()` runs Django's collector over everything below it.

So the project holds four disagreeing ideas of removal: a hard delete for
sessions, purchases, play events and status changes; a tombstone for games,
platforms and devices; an unwired `archived_at`; and the live projection row a
tombstoned game leaves behind, still claiming the library tracks it. Which
button means which, and what the confirmation page should say, is one decision
about the whole project. Settling it inside a read cutover would settle it in
one place and leave the other six models disagreeing, so it gets its own issue
and its own spec: [#944](https://github.com/KucharczykL/timetracker/issues/944)
makes removal one act, named remove, that destroys nothing. This one moves
reads and changes no removal behaviour.

`PlayerGame.excluded_from_unfinished` gains no reader either. #674 hands that
fact to the Purchase cutover, and the unfinished and dropped statistics keep
reading `Purchase.infinite` until then.

No legacy catalog field and no catalog adapter is removed. #770 removes
`Game.status` and `Game.mastered`; #771 removes `GameStatusChange` storage.
Both wait for the Session, access, Purchase, parity and IGDB consumers.

## No rollback plan

There is one database and it is production, so a revert is not a plan anyone
would use. Reverting the code after D would return the catalog columns at the
values the mirror last wrote and silently discard every status change made
since. The forward gates carry the risk instead: a full `make check` per child
pull request, and the rehearsal against a restored copy before the branch
merges.
