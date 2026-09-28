# Give excluded-from-unfinished its readers and a per-row control

Issue [#1315](https://github.com/KucharczykL/timetracker/issues/1315). #674 gave
`PlayerGame.excluded_from_unfinished` its event, command and column; #1270's bulk
Edit is its only writer, and nothing reads it. This issue states the flag through
the command that states the other facts, and gives it the statistics that honour
it, a filter, a list column, and a control for one game.

## One command states every PlayerGame fact

`RecordPlayerGameFacts` grows a third field,
`excluded_from_unfinished: bool | None = None`. All three fields take a `None`
default, so a caller names only the facts it states; `game_id` stays required.
`None` states nothing. `__post_init__` refuses a command whose three facts are
all `None`, and its message names the three. `build()` appends
`library.playergame.excluded_from_unfinished_changed` where the stated value
differs from the row, after the other two events, and answers `Unchanged` only
where no stated fact differs. Event type, payload and projector do not change,
so replay and #1270's Undo are untouched: `batch_fact_changes` reads events by
correlation id and type, never by key.

`record_facts` in `games/writes/playergame.py` and `record_facts_for_request` in
`games/views/playergame_writes.py` take `excluded_from_unfinished=None` and pass
it through.

`SetPlayerGameExcludedFromUnfinished`, the member
`CommandName.PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED` and the writer
`set_excluded_from_unfinished` are removed. The value
`library.playergame.set_excluded_from_unfinished` joins `RETIRED_COMMAND_NAMES`
in `games/events/dispatch.py`, so no later command reuses it and an old key never
replays as something else.

#1270's `_state` in `games/bulk_game_edit.py` becomes one `record_facts` call
under the row's key. The second dispatch under `<key>-excluded` goes, and with
it `GameEditStatement.records_facts`. One row's edit is one command, so it cannot
commit half. The tally keeps its meaning: moved when any fact moved.

One behaviour moves with it. `record_facts` answers `PlayerGameNotTracked` by
tracking the game and stating the facts again; the removed writer did not. The
bulk Edit and its Undo now track a game that lost its row, as the form already
does.

### Fingerprints move

The idempotency fingerprint hashes every field, `None` included, so the new
field changes the digest of every `RecordPlayerGameFacts`. Keys are minted per
dispatch except where a batch states one: `bulk_game_edit`,
`bulk_playthrough_acts.py` (`-status`) and `writes/playthrough_endpoints.py`. A
chunk of such a batch posted before the deploy and again after it answers
`IdempotencyKeyMismatch` (409, a visible refusal for that row). The window is
one in-flight batch. `FINGERPRINT_VERSION` stays 1: the canonical form is the
same.

## The statistics leave an excluded game out

`compute_stats` in `games/views/stats_data.py` reads
`excluded = Game.objects.tracked_by(library, tracked__excluded_from_unfinished=True)`
and adds `~Q(games__in=excluded)` to `unfinished` and to `dropped`, beside
`infinite=False`. A purchase with any excluded game leaves the figure, the rule
abandoned and done already follow. It moves `purchased_unfinished_count`,
`unfinished_purchases_percent`, the `purchased_unfinished` list,
`dropped_count` and `dropped_percentage`. No `StatsData` key is added, and
`games/stats_parity.py` classifies each as `_unchanged` already.

`stats_links.purchases_unfinished` and `purchases_dropped` each add one member
to their `AND`:

```text
PurchaseFilter(game_filter=GameFilter(
    excluded_from_unfinished=BoolCriterion(value=True),
    match=RelationMatch.NONE,
))
```

The nested Game scope is `tracked_by(library)`, so the member reads the same
set the figure reads. The flag does not go into `_not_finished_game`: that
`game_filter` asks whether some game is included, not whether none is excluded.

### Bundles

For a single-game purchase, link and figure agree, and the parity tests in
`tests/test_stats_links.py` hold both per year and all-time. A bundle holding
one excluded game leaves the figure but stays in the link. `relation_to_q`
compiles NONE as `~Q(games__id__in=...)`, and in one `Q` beside the ANY
`game_filter` Django reuses the M2M join, so the negation holds per game row.
#1337 fixes that in `relation_to_q` and adds the bundle parity case; a test here
pins the figure alone. The done-status clause has the same bundle gap.

Dropped follows the flag because `infinite` excludes from dropped today and the
flag is its successor. A separate flag for dropped is #1334.

### Purchase.infinite stays until #733

Both exclusions are read until PUR-09 (#733) backfills `infinite` into the flag
and removes the `infinite` clause. Writes stay separate, so there is no
dual-write interval.

## A list finds an excluded game

`GameFilter.excluded_from_unfinished: BoolCriterion | None`, with
`FilterField("tracked__excluded_from_unfinished",
metadata_lookup="player_games__excluded_from_unfinished")`, as `mastered`.
`QUICK_FACETS["games"]` adds `QuickFacet("excluded_from_unfinished",
"Excluded from unfinished")` last, so it moves into "More filters" first.

`game_list_columns` adds `Column("Unfinished lists", "unfinished_lists",
key="unfinished_lists", hidden_by_default=True)`, and `GAME_SORTS` in
`games/sorting.py` adds `"unfinished_lists":
SortSpec("tracked_excluded_from_unfinished")`, the annotation, as `status` does.
`list_games` appends the cell to each row, beside the Created cell: `Excluded`
or nothing, read from the annotation `tracked_by` states.

## One game states it

`GameForm` in `games/forms.py` adds `excluded_from_unfinished =
forms.BooleanField(required=False, label="Excluded from unfinished lists")`
after `mastered` in `field_order`, its initial read from the tracked row as
`mastered` is. Add Game and Edit Game in `games/views/game.py` pass
`form.cleaned_data["excluded_from_unfinished"]` to `record_facts_for_request`,
so one save is one command stating three facts.

Game detail's Status row puts a muted `Excluded from unfinished lists` beside
the crown when the flag is set. `_meta_row` has one `extra` slot, so the two are
one `Fragment`.

## Docs

- `docs/STATUSES.md`: the Unfinished and Dropped rules and the summary table
  gain the flag.
- `docs/superpowers/specs/2026-09-28-issue-1270-bulk-game-edit-design.md`: the
  `<key>-excluded` dispatch becomes one command.

## Tests

- `tests/test_playergame_command.py`: `FACTS` gains `exclusion`, so every fact
  test runs for it; the six `SetPlayerGameExcludedFromUnfinished` tests go; one
  command stating three facts appends three events; all-`None` refused.
- `tests/test_command_dispatch.py`: `test_the_retired_names_are_pinned` lists
  the third name.
- `tests/test_projection_replay_gate.py`: states the flag through
  `RecordPlayerGameFacts`.
- `tests/test_bulk_game_edit.py`: one dispatch per row under one key; Undo puts
  the flag back; a game with no tracked row is tracked.
- `tests/test_stats_links.py`: parity for single-game purchases, flagged and
  unflagged, per year and all-time; a bundle leaves the figure.
- `tests/test_quick_filter_bar.py`: `ORDERS["games"]` ends with the facet; the
  facet round-trips as editable.
- Game list: column hidden by default, shown and sorted on choice.
- `tests/test_game_form_page.py`: initial reads the row; save states the flag.
- `tests/tracked_games.py` and its `e2e/` twin: `create_tracked_game` takes
  `excluded_from_unfinished`.
- e2e: tick the box in Edit Game; detail shows the note; the stats page's
  unfinished list drops the game.

## Follow-up issues

- #1334: a separate flag for the dropped figures.
- #733 (commented): remove the `infinite` clause in both readers.
- #1337: NONE/ALL over a multi-valued relation reuses the join.
