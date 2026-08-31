# Present the Game, Edition, and Release hierarchy

Game detail shows the graph a library holds under one Game. It reads. It writes
nothing.

## The read

`game_hierarchy(game, library)` in `games/reads/catalog_hierarchy.py` answers the
Editions one library may see under one Game, each with its Releases. It makes two
queries. It reads no reverse accessor, because a shared Game's accessors reach
every library that ever wrote under it. The default Edition comes first, then the
rest by name. The default Release comes first, then the rest by earliest known
day, and an undated Release comes last.

## The plain shape

Most Games hold one unnamed Edition and one Release. That shape says everything
in two header rows: the Platform, and the date. The page adds no heading and no
table.

## The section

Three things break the plain shape and bring a `Releases` section: a second
Edition, a second Release, or a name on the only Edition. The section holds one
block for each Edition. A block holds a Platform and Released table, or the words
`No releases yet.`

A block takes a heading where the name tells one Edition from another: where two
Editions meet, and where a lone Edition states a name. A lone unnamed Edition
takes no heading, because `display_name` falls back to the Game.

## The words

Every date goes through `present_temporal_value()`. A stored month reads as a
month. A qualifier reads in words. See
[the presentation specification](2026-08-30-issue-963-temporal-presentation-design.md).

A Release with no Platform reads as `Unspecified`. No Platform is inferred from
the Game, from a sibling Release, or from a display default.

## The Game keeps its own date

`Game.original_release_date` stays in the header, because it is a fact of the
work. The flattened Platform row and the flattened release year are gone from the
page. The columns stay in the database until #889.

## Boundary

The page offers no control, thus it says nothing about who may change the graph.
#969 adds controls, and only for a private Game. Game URLs do not change.
