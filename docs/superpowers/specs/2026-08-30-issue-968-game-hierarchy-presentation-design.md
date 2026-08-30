# Present the Game, Edition, and Release hierarchy

Game detail prints one Platform row and one year, both read from legacy Game
columns. The Game, Edition, and Release graph exists since #649 and #650, and
nothing shows it.

The change is in `games/views/game.py`, and it reads. This is the read half of
the cutover, and it is correct while a Game holds one Edition, thus it is
reviewable before #969 can make a second one.

## The section

Game detail gains a hierarchy section. It lists each live Edition, and under each
Edition its live Releases. A Release shows its Platform and its release date.

The date goes through `present_temporal_value()` of #963, thus a stored month
reads as a month and a qualifier reads in words.

A Release with no Platform reads as explicitly unspecified. Nothing infers a
Platform from the Game, from a sibling Release, or from a display default.

## The ordinary Game reads plainly

Most Games hold one default Edition with no name, and one default Release. The
section then shows the Release facts alone: no Edition heading, and no empty
scaffolding. A second Edition or a second Release brings the full shape.

## What the flattened rows become

The Platform row and the release year row leave the Game meta list, because both
are facts of a Release and a Game may hold several.

The original release date stays on the Game, because it is a fact of the work.
It now reads through the presenter of #963 rather than through `str()`.

## A shared Game is visible and not the library's to change

A shared Game shows its Editions and Releases, marked as not editable here. This
section offers no control at all; #969 adds controls, and only for a private
Game.

Another library's private Editions and Releases never appear, because every read
goes through `for_library()`.

## Boundary

No write, route, form, or action; #969 owns those. No legacy column removal; #889
owns it, and the columns stay. Game URLs are unchanged.
