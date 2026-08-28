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
    return self.annotate(
        tracked=FilteredRelation(
            "player_games", condition=Q(player_games__library=library)
        )
    ).filter(tracked__isnull=False)
```

A `FilteredRelation` and not a plain path. Django opens a second join for each
`.filter()` call on a multi-valued relation, and the list applies its scope and
its criteria in two calls. Two joins on a shared catalog game let one library
match on another library's row. One alias refuses that, and filter, sort and
display then read `tracked__status`, `tracked__mastered` and
`tracked__archived_at` through it.

The join is an inner join, and an untracked game is therefore absent from every
read. Three sources put games in a database and each one leaves a row: the game
form dispatches `TrackGame`, migration `0033_playergame_baseline_backfill`
covers every restored dump, and `load_sample_data` calls `backfill_library()`.
A test is the fourth source and leaves none, which [the test
gap](#the-test-gap) answers.

`tracked_by()` joins and hides nothing. [Archive and
restore](#archive-and-restore) states who hides an archived game.

Nested filters take the alias from one place. `relation_to_q` builds each
subquery from `context.queryset_for(Game)`, so
`filter_query_context_for_library()` returns `tracked_by(library)` for `Game`
and every nested `GameFilter` inherits the alias. The `GameFilter` that
`stats_links` nests inside a `PurchaseFilter` is one of these.

## What the filter layer needs

`FilterField` takes an optional `metadata_lookup`.

```python
fields = {
    "status": FilterField("tracked__status", metadata_lookup="player_games__status"),
}
```

`_walk_lookup` resolves real model paths. `tracked` is an annotation alias, so
it resolves to nothing, and a field that resolves to nothing renders a widget
with no options. The two paths are therefore declared apart: the query reads the
alias, and the metadata layer walks the real path to `PlayerGame.status`.

`_static_choices` then reports all six words, `shelved` among them, from the
field itself. No hand-written option list exists to disagree with the column.

## The status vocabulary

A status travels as a word. The `?filter=` JSON, `GameForm.status`,
`GameStatusSelector`, the API's `GameStatusUpdate`, and the five `stats_links`
builders each hold `PlayerGameStatus` members. `Game.Status` keeps its members
and loses its readers.

`PlayerGameStatus.SHELVED` becomes reachable. It has no letter, which is why
`legacy_status_for()` raised for it, and the whole map goes with the letters:
`games/playergame_status.py` is deleted.

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

## Archive and restore

An archived game is one the library keeps and does not want listed. It is not a
status: the row keeps the status it had, which is what makes a restore return
the game the library archived.

| Surface | An archived game |
| --- | --- |
| Games list | Hidden, unless the `Archived` facet asks for it |
| Game detail by direct URL | Resolves, renders, offers Restore |
| Game picker on a session or purchase form | Hidden |
| Statistics | Counted |
| Sessions and purchases lists | Unaffected |

Statistics count it because the sessions happened. Archiving states a
preference about a list and denies no history.

`list_games` applies the default and `tracked_by()` does not. A scope that hid
archived rows would leave the facet no way to ask for them. A request with no
`archived` criterion reads live games; an explicit criterion wins.

`GameFilter.archived` is a `BoolCriterion` over the presence of
`tracked__archived_at`, through the existing `bool_isnull_handler`. The quick
bar carries it as a facet.

Archive is a row action and a button on the detail page. Restore takes the same
two places on an archived game. Both dispatch the commands #675 built and #677
left without a caller.

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

Behaviour is preserved exactly, quirks included. `~Q(games__status="f")` over a
multi-game purchase is already subtle, and a cutover is the wrong moment to
settle what it should mean. The parity suite is the arbiter: a difference it
reports is reverted to match the old result, not argued to be an improvement.

## The write path after the mirror

Three modules exist because the reads were on the catalog. Two have no reason
to survive this issue. The third has a job that outlives it.

`games/playergame_status.py` is deleted with the letters. `_mirror()` is deleted
with the reads, and `games/writes/playergame.py` loses it.

Something must still turn a `CommandRejected` into a toast and a redirect, and
must now dispatch archive and restore. `games/writes/playergame.py` keeps that
job: it takes an actor and not a request, which is what lets the API call it.
`games/views/playergame_writes.py` is deleted, and each view calls the facade
and catches `PlayerGameWriteFailed`.

Three modules thus become one, and no file survives for a reason that expired.

## The test gap

117 test files call `Game.objects.create`, over 598 sites. 43 of them also
exercise a game read path, and under an inner join each of those reads an empty
list.

One autouse fixture in `tests/conftest.py` and one in `e2e/conftest.py` connect
a `post_save` receiver on `Game` that calls `backfill_game()`. A test-created
game then gets its row the way a migration-created game does, and no call site
is rewritten.

The cost is stated plainly: test setup diverges from production, so a test can
pass where production would fail. `tests/test_playergame_write_path.py` covers
the real path and is the reason the divergence is affordable.

## The child issues

Each child is one bounded branch and pull request onto
`codex/playergame-read-cutover`. The branch merges to `main` once.

**A — the join and the display.** `tracked_by()`,
`FilterField.metadata_lookup`, the `filter_query_context_for_library()` wiring,
`list_games`, `view_game`, `GameStatusSelector`, `GameStatus`, `_record_played`,
`GameForm`, the autouse fixtures, and the parity suite.

**B — filters, sorts and the quick bar.** `GameFilter.status`, `.mastered` and
`.archived`, `GAME_SORTS["status"]`, the `Archived` facet, and the six-option
status widget.

**C — statistics and the API.** The four `stats_data` predicates, the three
`PurchaseQuerySet` methods, the five `stats_links` builders,
`GameStatusUpdate`, `PATCH /api/games/{id}/status`, and archived games hidden
from `search_games`.

**D — archive, restore and the retirement.** The Archive and Restore controls,
History from events, the four `statuschange` routes and the audit signal, the
module collapse, and the deletion of the parity suite.

Creating the four issues is a mutating action. It follows the catalog wave's
export, diff and read-back protocol, and it happens after this spec is
approved.

## Verification

`tests/test_playergame_read_parity.py` is created by A and deleted by D. It
asserts equal id sets, old against new, over the status and mastered filters,
every `GAME_SORTS` entry, and every `stats_links` builder. Its whole purpose is
to guard the switch, so it does not outlive it.

The existing `stats_links` parity tests are re-pointed and kept.

New browser tests cover the archive and restore round trip and the `Archived`
facet.

Each child pull request ends on a full `make check`. The merge to `main` adds
the wave's integration gate, including the rehearsal against a restored
production copy.

## Out of scope

`PlayerGame.excluded_from_unfinished` gains no reader. #674 hands that fact to
the Purchase cutover, and the unfinished and dropped statistics keep reading
`Purchase.infinite` until then.

No legacy catalog field and no catalog adapter is removed. #770 removes
`Game.status` and `Game.mastered`; #771 removes `GameStatusChange` storage.
Both wait for the Session, access, Purchase, parity and IGDB consumers.

## Reversibility

A revert is the child commits and the branch. No migration writes a row and no
recorded event is lost, because the reads change and the event log does not.
The catalog columns freeze at their last mirrored values, so a revert to the
catalog reads returns the state the cutover left.
