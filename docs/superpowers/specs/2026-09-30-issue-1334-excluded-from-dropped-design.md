# Excluded from dropped figures

Issue [#1334](https://github.com/KucharczykL/timetracker/issues/1334), member
M8 of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The rule

A fact that a person states for one figure does not decide a different figure.
`excluded_from_unfinished` removes a game from the unfinished figures only.
`excluded_from_dropped` removes a game from the dropped figures only.

## The fact

`PlayerGame.excluded_from_dropped` is a boolean. Its default is false. The event
`library.playergame.excluded_from_dropped_changed` states it. The payload is
`{"excluded_from_dropped": bool}`.

`RecordPlayerGameFacts` has four facts: status, mastered,
`excluded_from_unfinished` and `excluded_from_dropped`. `None` states nothing.
The events come in that order. The fourth field changes each digest, so
`FINGERPRINT_VERSION` is 3.

No migration sets the fact. The conversion of `Purchase.infinite` (P4) states
both exclusion facts. Before this change, `excluded_from_unfinished` also
removed a game from the dropped figures. To keep such a game out of the dropped
figures, state the second fact. The bulk Edit on the Games list does this for
many games.

## The statistics

`compute_stats` removes a purchase from `unfinished` when one of its games
states `excluded_from_unfinished`. It removes a purchase from `dropped` when one
of its games states `excluded_from_dropped`. `stats_links._holding_no_game`
takes the `GameFilter` for each figure. The parity test examines each fact with
each figure.

## Visibility

"Visibility" is the name for all facts that remove a game from a figure. Each
surface groups them:

- The Game form has a "Visibility" fieldset on a section panel.
  `FormFieldGroup(look="panel")` supplies the panel.
- The bulk Edit has the same fieldset.
- Game detail shows a "Visibility" row when a fact is set.
- The Games quick bar has one "Visibility" facet.
- The Games list has one hidden column for each fact. You can sort each column.

`VISIBILITY_FIELDS` (`games/models.py`) and the Visibility `QuickFacetGroup`
group the facts. They do not add a fact. A new fact also needs a column, an
event, a command field and each reader. A test compares the fact lists of the
command, the bulk statement and the Undo reader.

## The grouped facet

`QuickFacetGroup(key, label, members)` is one dropdown for several fields.
`QuickFacet` and `QuickFacetGroup` both have `key` and `fields`.
`quick_facet_fields(mode)` gives the fields that `is_quick_editable` reads. A
group is applied when one of its fields is in the filter.

Each member is a `DropdownFieldset`. It holds a legend and one widget. A member
must be a bool, number or string field. A set or date panel sets the width of
the dialog, so a group refuses it when it renders. A contract test examines
each group.

The TypeScript bar does not change. It reads each widget that has a
`data-path`, and it moves each `[data-quick-facet]` node as one item.
