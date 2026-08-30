# Write many private Editions and Releases

`save_private_game()` gets or creates exactly one default Edition and one default
Release. `Edition` holds an id, a Game, and a default mark, and no name, thus two
Editions of one Game read alike.

The service is `games/catalog_writes.py`. It gains a name column and six verbs,
and no screen. #969 is the caller.

## The name

`Edition.name` is text, and empty is allowed. An Edition with no name presents as
the Game's own name, which keeps the default Edition of an ordinary Game silent.

A conditional `UniqueConstraint` keeps a name unique among the live Editions of
one Game, the way a name and a year stay unique among platformless Games.

## The verbs

`add_edition`, `update_edition`, `remove_edition`, `add_release`,
`update_release`, `remove_release`.

Each is one transaction, and a failure leaves the graph as it was. Each is
idempotent: repeating an unchanged input creates no second Edition, no second
Release, and no second default.

A removal calls `remove()` from `games/removal.py`. Nothing here destroys a row.

## The default

A Game holds at least one live Edition, and exactly one of them is the default.
An Edition may hold no Release; when it holds any, exactly one of them is the
default. Setting a new default clears the old one in the same transaction.

Removing a default is refused while a live sibling exists, because a sibling can
take the mark and the writer must say which one. With no live sibling, removing
the last Release of an Edition is allowed and the mark goes with it, and removing
the last Edition of a Game is refused, because a Game with no Edition has nowhere
to hold a Release.

## Permission is explicit

A private Game belongs to one library, and that library writes its graph. A
shared Game has `library IS NULL`, and every verb refuses a write against one or
against its Editions and Releases. A Platform from another library is refused.

Each refusal is a rejection with a sentence. Nothing scopes the row away and
reports success.

## The adapter stops erasing

`save_legacy_game_form()` rewrites both temporal fields from the integer year
columns through `TemporalValue.from_year()`, which states no qualifier. A legacy
Game save thus clears whatever precision or qualifier this wave stored.

The adapter writes a year value only when the stored value is absent, or is a
bare year that agrees with the integer column. Otherwise it leaves the stored
value alone and writes the integer column from the stored year. #889 retires the
path.

## Boundary

No screen, route, or form; #969 owns those. No Release selector; #690 owns it. No
external reference; #896 owns it. No product relationship; #731 and #732 own
those.
