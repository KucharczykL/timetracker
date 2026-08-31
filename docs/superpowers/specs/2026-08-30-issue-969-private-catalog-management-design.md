# Manage private Editions and Releases

A player states the Editions and Releases of a private Game. This is the last of
the seven children of #893, and the one that turns the other six into a feature.

The screens go in `games/views/`, the forms in `games/forms.py`, and the routes
in `games/urls.py`.

## The routes

| Name | Act |
| --- | --- |
| `add_edition` | add an Edition to a Game |
| `edit_edition` | change a name or the default mark |
| `remove_edition` | remove one Edition |
| `add_release` | add a Release to an Edition |
| `edit_release` | change a Platform or a date |
| `remove_release` | remove one Release |

Each add and edit is origin-aware. Each removal is one `confirm_and_remove()`
call: a `ConfirmPage` on GET, and the act on POST at the same URL. No route
changes state on GET.

Every route is classified in `games/views/returns.py`, or
`tests/test_returns_classification.py` fails. Every link to a mutating view
carries `?origin=` through `action_url()`.

## The forms

`EditionForm` holds the name and the default mark. `ReleaseForm` holds the
optional Platform and the release date, through the field of #964 and the element
of #965.

Both call the verbs of #967. Neither writes a model, and neither opens a
transaction, because the service owns both.

## The Game form gives up two fields

Platform and the release year leave the Game Edit form. Both are Release facts,
and a Game may hold several Releases; Game detail now edits each Release where it
lives.

Add Game keeps one inline Release row: a Platform and a date, which state the
default Release the service already creates. Adding a game thus stays one screen.
Further Editions and Releases are added afterwards, from Game detail.

The original release date stays on the Game form, because it is a fact of the
work.

## Isolation

Every route resolves its object through `for_library()`. Another library's
Edition or Release answers 404, including by direct UUID. A shared Game shows its
graph and offers no control that would change it.

## Tests

Focused tests cover permission, the hierarchy, accessibility, and two-library
isolation. Browser tests in `e2e/` cover add, edit, and remove, for both an
Edition and a Release.

## Boundary

No reusable Release selector; #690 owns it, as the first real consumer. No global
Catalogue page and no external reference editing; #896 owns those. No discovery,
import, or reconciliation; #783, #784, and #785 own those. No product
relationship; #731 and #732 own those. No legacy column removal; #889 owns it.

## Amendments

Two departures from the words above, taken during implementation and recorded
here so the spec does not quietly disagree with the code.

**The Game form states a temporal value, not an integer.** The spec kept
`year_released` on the Game form. The implementation removed it, and
`original_year_released` with it. The reason is issue comment 1's option 2: the
column holds a temporal value at any precision, and an integer control cannot
say what a month, a decade, a range or a qualifier holds. Keeping both meant
keeping `_reconcile_year`, which compared the posted year against the persisted
integer and guessed which to believe. The form now uses `TemporalField()`, whose
grammar matches the column, and the guessing is gone.

**The flat columns are mirrored, and the mirror checks first.** The spec did not
say what happens to `Game.platform`, `Game.year_released` and
`Game.original_year_released` while #889 is outstanding. Filters, the API and the
sample fixture still read them, so `mirror_legacy_columns()` writes them from the
default Edition's default Release, and `write_and_mirror()` wraps every catalog
write so the columns cannot lag the graph. The mirror raises
`LEGACY_IDENTITY_TAKEN` before it writes, because `(library, name, platform,
year)` still carries a unique constraint and a Release edit can otherwise walk
one Game onto another Game's identity — a database error after the form has
already reported success.
