# Edit many games

The Games list tray has an "Edit…" act, as the session list has
([#1211](2026-09-25-issue-1211-bulk-edit-design.md),
[#1310](2026-09-27-issue-1310-bulk-edit-moves-design.md)): one act per list
for the facts a person sets, not one act per fact. It states the library's
facts about each selected game: status, mastered, and excluded from
unfinished lists. An empty field keeps. The act runs through the runner of
[#713](2026-09-20-issue-713-bulk-runner-design.md), in the
[wave](2026-09-19-selectable-tables-wave-design.md). The row's
`GameStatusSelector` stays the control for one row's status.

## The act

`games/bulk_game_edit.py` declares `playergame.edit`. Its scope is
`game_scope` in `games/bulk_games.py`, the list's own read through
`tracked_by`. The resolve reads the same rows with the excluded flag, and
gives a key it does not find as lost, with `GAME_GONE`. The preview shows
Game, Platform, Status, Mastered and Unfinished lists. The Undo takes
`PlayerGame` keys, because the events go on the PlayerGame's stream.

The tray shows Edit…, then Remove. The destructive act is last.

## The statement

`GameEditStatement` holds `status`, `mastered` and
`excluded_from_unfinished`; `None` keeps, and one fact at least is stated. It
travels as JSON under the runner's choice field, as `EditStatement` does.
`settle` decodes a carried statement or composes one from the form.

The form has three fields under the runner's prefix, none required. Status
is a `ChoiceSearchSelectWidget` over the six words; Mastered and Unfinished
lists are two-answer pickers. Each placeholder states what the rows hold:
"Keep: Played", or "Keep: mixed". A form that states nothing is refused.

## Forward

Status and mastered go through one `record_facts`, under the row's key.
Excluded goes through `set_excluded_from_unfinished` under `<key>-excluded`.
A game that has every stated fact answers `Unchanged`.

## The inverse

`fact_change(library, player_game_id, batch_id, event)` in
`games/reads/playergame_facts.py` reads the stream for one fact: `None`
where the batch stated none; otherwise the value before the batch's event
and the value the batch stated. The value before is the latest earlier
event of the fact, or the creation's default (Unplayed, not mastered,
included). No earlier event is `RowUnreadable`. `facts_before` reads all
three.

The inverse refuses a game the batch changed nothing on. A game that has
every earlier fact answers `Unchanged`; only then is a removed game
refused. It restates each changed fact, over a later change, as #1211's
inverse does, and logs a fact it writes over. A second Undo answers
`Unchanged`.

The #1256 Undo reads the status through `facts_before`, before its void, so
a defect leaves no half-undone row.

Nothing reads the excluded flag yet; #1315 gives it readers.
