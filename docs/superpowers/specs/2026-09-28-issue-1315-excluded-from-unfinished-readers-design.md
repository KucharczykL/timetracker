# Excluded from unfinished lists

Issue [#1315](https://github.com/KucharczykL/timetracker/issues/1315).
`PlayerGame.excluded_from_unfinished` tells the statistics to ignore a game that
does not end.

## The command

`RecordPlayerGameFacts` states `status`, `mastered`,
`excluded_from_unfinished` and `excluded_from_dropped` (#1334). Each field is `None` by default. `None` states
nothing. A command that states no fact is refused at construction.

`build()` appends one event for each fact that differs from the row, in field
order. If no fact differs, the answer is `Unchanged`.

`record_facts` and `record_facts_for_request` take each fact. The Game form
and the bulk Edit each send one fact command for each game, under one key.
Because of this, a save cannot commit half.

`library.playergame.set_excluded_from_unfinished` is in `RETIRED_COMMAND_NAMES`.
Do not use this name again.

The idempotency fingerprint includes each field. A new field changes each
digest, so it increments `FINGERPRINT_VERSION`. A key recorded at an earlier
version replays without a digest check.

## The statistics

`compute_stats` removes a purchase from the unfinished figures when one of its
games is excluded. `excluded_from_dropped` (#1334) does the same for the dropped
figures. `Purchase.infinite` stays until #733 moves it into both flags.

`purchases_unfinished` and `purchases_dropped` in `stats_links` each add one
`game_filter` with `RelationMatch.NONE`, over their own flag. Do not put the flag in
`_not_finished_game`. That filter matches if one game matches.

For a bundle, the link and the figure do not agree. Django uses the same join
for the NONE clause and the ANY clause, so a bundle with one included game
passes the link. #1337 fixes `relation_to_q`. A test examines the figure alone.

## The list

`GameFilter.excluded_from_unfinished` is a `BoolCriterion`, as `mastered` is. The
Games quick bar holds it in the Visibility facet. The Games list has a column
"Unfinished lists".
The column is hidden by default. You can sort it. Its cell shows `Excluded` or
nothing.

## One game

The Game form's Visibility fieldset has a check box "Unfinished lists". Game
detail's Visibility row names it when the flag is set.

## Tests

- `tests/test_playergame_command.py` does each fact test for the exclusion too.
- `tests/test_stats_links.py` does parity for single-game purchases, per year and
  for all time.
- `tests/test_visibility_flags.py` examines the filter, the column and the
  detail.
- `tests/test_game_form_page.py` and `e2e/test_game_form_catalog_e2e.py` examine
  the form.
